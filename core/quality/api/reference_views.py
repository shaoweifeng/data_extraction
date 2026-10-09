"""QA 文献管理 HTTP 适配层。"""

from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.core.paginator import EmptyPage, Paginator
from django.db.models import Count, Q
from django.http import FileResponse
from django.views.decorators.http import require_http_methods

from core.models import DataFile, QAFulltextAsset, QAReference
from core.quality.api.common import (
    _get_project, _get_qa_ref, _json_err, _json_ok, _serialize_ref, _validated_json,
    _visible_qa_refs,
)
from core.quality.api.serializers import (
    QABatchMethodInputSerializer, QARefImportInputSerializer, QARefUpdateInputSerializer,
)
from core.quality.domain.methods import get_all_methods_meta
from core.services.access_policy import ProjectAccessPolicy


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
    base_refs = QAReference.objects.filter(project=project)
    refs = base_refs.select_related('fulltext_file', 'fulltext_asset').order_by('id')

    query = (request.GET.get('q') or '').strip()
    if query:
        refs = refs.filter(
            Q(title__icontains=query)
            | Q(first_author__icontains=query)
            | Q(doi__icontains=query)
        )

    view = request.GET.get('view', 'all')
    if view == 'reviewable':
        refs = refs.filter(
            ai_eval_status__in=['completed', 'abstract_only'],
            signal_items__isnull=False,
        ).distinct()
        review_status = request.GET.get('review_status', 'all')
        if review_status == 'pending':
            refs = refs.exclude(review_status='confirmed')
        elif review_status == 'confirmed':
            refs = refs.filter(review_status='confirmed')

    # 兼容旧调用：只有明确传入 page 时才启用分页响应结构。
    if 'page' not in request.GET:
        return _json_ok([_serialize_ref(r) for r in refs])

    try:
        page_number = max(1, int(request.GET.get('page', 1)))
        page_size = min(100, max(10, int(request.GET.get('page_size', 30))))
    except (TypeError, ValueError):
        return _json_err('page 和 page_size 必须是整数')

    paginator = Paginator(refs, page_size)
    try:
        page_obj = paginator.page(page_number)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages or 1)

    summary = base_refs.aggregate(
        total=Count('id', distinct=True),
        fulltext_available=Count('id', filter=Q(fulltext_status='available'), distinct=True),
        method_assigned=Count('id', filter=~Q(quality_method=''), distinct=True),
        reviewable=Count(
            'id',
            filter=Q(
                ai_eval_status__in=['completed', 'abstract_only'],
                signal_items__isnull=False,
            ),
            distinct=True,
        ),
        confirmed_reviewable=Count(
            'id',
            filter=Q(
                ai_eval_status__in=['completed', 'abstract_only'],
                signal_items__isnull=False,
                review_status='confirmed',
            ),
            distinct=True,
        ),
    )
    summary['fulltext_pending'] = summary['total'] - summary['fulltext_available']
    summary['pending_reviewable'] = summary['reviewable'] - summary['confirmed_reviewable']
    return _json_ok({
        'results': [_serialize_ref(ref) for ref in page_obj.object_list],
        'count': paginator.count,
        'page': page_obj.number,
        'page_size': page_size,
        'total_pages': paginator.num_pages,
        'summary': summary,
    })


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
    from core.quality.services.reference_service import QualityImportError, rebuild_from_screening

    try:
        result = rebuild_from_screening(project, body['source_stage'])
    except QualityImportError as exc:
        return _json_err({'code': exc.code, 'message': exc.message}, 409)
    ActivityLog.objects.create(
        project=project,
        operation_type='qa_import',
        operation_detail={
            'imported': result['imported'],
            'skipped': result['skipped'],
            'source_stage': body['source_stage'],
            'screening_run_id': result['screening_run_id'],
            'corpus_revision': result['corpus_revision'],
        },
        created_by=request.user,
    )
    return _json_ok(result)


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

    from core.quality.services.fulltext import FulltextUploadError, create_fulltext_assets
    from core.quality.tasks import parse_qa_pdf_meta

    try:
        refs = create_fulltext_assets(project, files)
    except FulltextUploadError as exc:
        return _json_err({'code': exc.code, 'message': exc.message}, exc.status)

    for ref in refs:
        try:
            parse_qa_pdf_meta.delay(ref.id)
        except Exception:
            QAFulltextAsset.objects.filter(qa_reference=ref).update(
                status='failed',
                error_code='dispatch_failed',
                error_message='PDF 处理任务暂时无法提交，请稍后重试。',
            )
            QAReference.objects.filter(pk=ref.id).update(fulltext_status='error')
    refs = list(QAReference.objects.filter(pk__in=[r.pk for r in refs]).select_related('fulltext_asset'))
    created_refs = [_serialize_ref(ref) for ref in refs]

    # ActivityLog
    from core.models import ActivityLog
    if created_refs:
        ActivityLog.objects.create(
            project=project,
            operation_type='qa_upload_pdf',
            operation_detail={'count': len(created_refs), 'reference_ids': [r['id'] for r in created_refs]},
            created_by=request.user,
        )
    return _json_ok({'created': len(created_refs), 'refs': created_refs}, status=201)


@login_required
@require_http_methods(['GET'])
def fulltext_download(request, asset_id):
    """Stream a private QA PDF only to users who can access its project."""
    asset = QAFulltextAsset.objects.select_related('qa_reference__project').filter(
        pk=asset_id,
        qa_reference__project__in=ProjectAccessPolicy.visible_projects(request.user),
    ).first()
    if not asset or not asset.raw_file:
        return _json_err('无权访问该全文或文件不存在', 404)
    asset.raw_file.open('rb')
    return FileResponse(
        asset.raw_file,
        as_attachment=False,
        filename=Path(asset.original_filename).name,
        content_type='application/pdf',
    )


@login_required
@require_http_methods(['POST'])
def fulltext_retry(request, asset_id):
    """Retry transient worker/scanner failures without creating another asset."""
    asset = QAFulltextAsset.objects.select_related('qa_reference').filter(
        pk=asset_id,
        qa_reference__project__in=ProjectAccessPolicy.visible_projects(request.user),
    ).first()
    if not asset:
        return _json_err('无权访问该全文或全文不存在', 404)
    if asset.status != 'failed':
        return _json_err({'code': 'not_retryable', 'message': '仅处理失败的全文可以重试。'}, 409)
    if not asset.raw_file or not asset.raw_file.storage.exists(asset.raw_file.name):
        return _json_err({'code': 'source_file_missing', 'message': '原始 PDF 已清理，请重新上传。'}, 409)

    asset.status = 'pending'
    asset.scan_status = 'pending'
    asset.extraction_status = 'pending'
    asset.error_code = ''
    asset.error_message = ''
    asset.save(update_fields=[
        'status', 'scan_status', 'extraction_status', 'error_code', 'error_message', 'updated_at',
    ])
    QAReference.objects.filter(pk=asset.qa_reference_id).update(fulltext_status='pending')
    try:
        from core.quality.tasks import parse_qa_pdf_meta

        parse_qa_pdf_meta.delay(asset.qa_reference_id)
    except Exception:
        asset.status = 'failed'
        asset.error_code = 'dispatch_failed'
        asset.error_message = 'PDF 处理任务暂时无法提交，请稍后重试。'
        asset.save(update_fields=['status', 'error_code', 'error_message', 'updated_at'])
        QAReference.objects.filter(pk=asset.qa_reference_id).update(fulltext_status='error')
        return _json_err({'code': asset.error_code, 'message': asset.error_message}, 503)
    return _json_ok({'asset_id': asset.id, 'status': 'pending'}, status=202)


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

    if 'quality_method_variant' in body and 'quality_method' not in body:
        from core.quality.domain.methods import get_method_config
        try:
            get_method_config(ref.quality_method, body['quality_method_variant'] or None)
        except ValueError as exc:
            return _json_err({'quality_method_variant': str(exc)})

    updatable = ['quality_method', 'quality_method_variant', 'eval_mode', 'selected_models', 'fulltext_status', 'title', 'first_author', 'year', 'journal']
    changed = False
    for field in updatable:
        if field in body:
            setattr(ref, field, body[field])
            changed = True

    if 'quality_method' in body and 'quality_method_variant' not in body:
        method = body['quality_method']
        ref.quality_method_variant = 'cohort' if method == 'NOS' else ''
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
    quality_method_variant = body['quality_method_variant'] or ('cohort' if quality_method == 'NOS' else '')
    refs = _visible_qa_refs(request).filter(pk__in=ref_ids)
    if refs.count() != len(ref_ids):
        return _json_err('部分文献不存在或无权访问', 404)
    if refs.values('project_id').distinct().count() != 1:
        return _json_err('批量设置仅允许同一项目内的文献')

    first_ref = refs.select_related('project').first()
    from core.quality.services.reference_service import assign_quality_method

    updated = assign_quality_method(refs, quality_method, quality_method_variant)

    # ActivityLog
    from core.models import ActivityLog
    if updated:
        if first_ref:
            ActivityLog.objects.create(
                project=first_ref.project,
                operation_type='qa_set_method',
                operation_detail={
                    'method': quality_method,
                    'method_variant': quality_method_variant,
                    'count': updated,
                },
                created_by=request.user,
            )
    return _json_ok({'updated': updated})


# ─────────────────────────────────────────────────────────────────────────────
# AI 评价
# ─────────────────────────────────────────────────────────────────────────────
