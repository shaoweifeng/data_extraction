"""QA 文献管理 HTTP 适配层。"""

from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods

from core.models import DataFile, QAReference
from core.quality.api.common import (
    _get_project, _get_qa_ref, _json_err, _json_ok, _serialize_ref, _validated_json,
    _visible_qa_refs,
)
from core.quality.api.serializers import (
    QABatchMethodInputSerializer, QARefImportInputSerializer, QARefUpdateInputSerializer,
)
from core.quality.domain.methods import get_all_methods_meta


@login_required
@require_http_methods(['GET'])
def methods_list(request):
    """返回所有可用质量评价方法"""
    metas = get_all_methods_meta()
    return _json_ok(metas)


# ─────────────────────────────────────────────────────────────────────────────
# 文献管理
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@require_http_methods(['GET'])
def ref_list(request):
    """GET /api/qa/refs/?project_id="""
    project_id = request.GET.get('project_id')
    if not project_id:
        return _json_err('缺少 project_id')
    project = _get_project(request, project_id)
    if not project:
        return _json_err('无权访问该项目或项目不存在', 404)
    refs = QAReference.objects.filter(project=project).select_related('fulltext_file')
    return _json_ok([_serialize_ref(r) for r in refs])


@login_required
@require_http_methods(['POST'])
def ref_import(request):
    """POST /api/qa/refs/import/ — 清空并从初筛/复筛最终结果重建。"""
    body, error = _validated_json(request, QARefImportInputSerializer)
    if error:
        return error

    project = _get_project(request, body['project_id'])
    if not project:
        return _json_err('无权访问该项目或项目不存在', 404)

    from core.models import ActivityLog
    from core.quality.services.reference_service import rebuild_from_screening

    imported = rebuild_from_screening(project, body['source_stage'])
    ActivityLog.objects.create(
        project=project,
        operation_type='qa_import',
        operation_detail={'imported': len(imported), 'source_stage': body['source_stage']},
        created_by=request.user,
    )
    return _json_ok({'imported': len(imported), 'skipped': 0, 'ref_ids': imported})


@login_required
@require_http_methods(['POST'])
def ref_upload(request):
    """POST /api/qa/refs/upload/ — 上传全文 PDF，自动识别文献信息"""
    project_id = request.POST.get('project_id')
    if not project_id:
        return _json_err('缺少 project_id')
    project = _get_project(request, project_id)
    if not project:
        return _json_err('无权访问该项目或项目不存在', 404)

    files = request.FILES.getlist('files')
    if not files:
        return _json_err('未上传文件')

    created_refs = []
    max_pdf_bytes = 50 * 1024 * 1024
    invalid_files = [
        f.name for f in files
        if not f.name.lower().endswith('.pdf') or f.size > max_pdf_bytes
    ]
    if invalid_files:
        return _json_err({'files': [f'仅支持不超过 50MB 的 PDF: {name}' for name in invalid_files]})

    for f in files:
        # 保存文件
        data_file = DataFile.objects.create(
            project=project,
            filename=f.name,
            file=f,
            source='upload',
            data_category='input',
            description='质量评价全文PDF',
            created_by=request.user,
        )
        # 尝试从 PDF 解析基础信息（简化：仅用文件名作为标题）
        title = f.name.replace('.pdf', '').replace('_', ' ')
        ref = QAReference.objects.create(
            project=project,
            title=title,
            source_type='fulltext_upload',
            fulltext_file=data_file,
            fulltext_status='available',
        )
        # 异步触发 PDF 解析提取元数据（非阻塞）
        try:
            from core.quality.tasks import parse_qa_pdf_meta
            parse_qa_pdf_meta.delay(ref.id)
        except Exception:
            pass  # Celery 未就绪时跳过，不影响上传
        created_refs.append(_serialize_ref(ref))

    # ActivityLog
    from core.models import ActivityLog
    if created_refs:
        ActivityLog.objects.create(
            project=project,
            operation_type='qa_upload_pdf',
            operation_detail={'count': len(created_refs), 'filenames': [r['title'] for r in created_refs]},
            created_by=request.user,
        )
    return _json_ok({'created': len(created_refs), 'refs': created_refs}, status=201)


@login_required
@require_http_methods(['PATCH'])
def ref_update(request, ref_id):
    """PATCH /api/qa/refs/<id>/ — 更新单篇文献（方法选择等）"""
    ref = _get_qa_ref(request, ref_id)
    if not ref:
        return _json_err('无权访问该文献或文献不存在', 404)

    body, error = _validated_json(request, QARefUpdateInputSerializer)
    if error:
        return error

    updatable = ['quality_method', 'eval_mode', 'selected_models', 'fulltext_status', 'title', 'first_author', 'year', 'journal']
    changed = False
    for field in updatable:
        if field in body:
            setattr(ref, field, body[field])
            changed = True

    # 绑定全文
    if 'fulltext_file_id' in body:
        try:
            df = DataFile.objects.get(pk=body['fulltext_file_id'], project=ref.project)
            ref.fulltext_file = df
            ref.fulltext_status = 'available'
            changed = True
        except DataFile.DoesNotExist:
            return _json_err('文件不存在或不属于该项目')

    if changed:
        ref.save()

    return _json_ok(_serialize_ref(ref))


@login_required
@require_http_methods(['POST'])
def ref_batch_method(request):
    """POST /api/qa/refs/batch-method/ — 批量设置质量评价方法"""
    body, error = _validated_json(request, QABatchMethodInputSerializer)
    if error:
        return error

    ref_ids = list(dict.fromkeys(body['ref_ids']))
    quality_method = body['quality_method']
    refs = _visible_qa_refs(request).filter(pk__in=ref_ids)
    if refs.count() != len(ref_ids):
        return _json_err('部分文献不存在或无权访问', 404)
    if refs.values('project_id').distinct().count() != 1:
        return _json_err('批量设置仅允许同一项目内的文献')

    first_ref = refs.select_related('project').first()
    from core.quality.services.reference_service import assign_quality_method

    updated = assign_quality_method(refs, quality_method)

    # ActivityLog
    from core.models import ActivityLog
    if updated:
        if first_ref:
            ActivityLog.objects.create(
                project=first_ref.project,
                operation_type='qa_set_method',
                operation_detail={'method': quality_method, 'count': updated},
                created_by=request.user,
            )
    return _json_ok({'updated': updated})


# ─────────────────────────────────────────────────────────────────────────────
# AI 评价
# ─────────────────────────────────────────────────────────────────────────────
