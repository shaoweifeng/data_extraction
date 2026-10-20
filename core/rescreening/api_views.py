"""文献复筛 HTTP API。"""

import io
import json
import tempfile
import zipfile

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from core.models import ActivityLog, DataFile, RescreenCriteria, RescreenReference
from core.quality.api.common import _format_validation_errors, _get_project, _json_err, _json_ok
from core.rescreening.serializers import (
    RescreenAIStartInputSerializer,
    RescreenAutoSearchInputSerializer,
    RescreenBatchIncludeInputSerializer,
    RescreenCriteriaInputSerializer,
    RescreenExportInputSerializer,
    RescreenImportInputSerializer,
    RescreenReviewInputSerializer,
)
from core.services.access_policy import ProjectAccessPolicy
from core.rescreening.services import build_fulltext_lookup_url


def _validated_json(request, serializer_class):
    try:
        body = json.loads(request.body or b'{}')
    except (TypeError, ValueError, json.JSONDecodeError):
        return None, _json_err('请求体 JSON 格式错误')
    serializer = serializer_class(data=body)
    if not serializer.is_valid():
        return None, _json_err(_format_validation_errors(serializer.errors))
    return serializer.validated_data, None


def _visible_refs(request):
    return RescreenReference.objects.filter(
        project__in=ProjectAccessPolicy.visible_projects(request.user)
    )


def _get_ref(request, ref_id):
    return _visible_refs(request).select_related('project', 'fulltext_file').filter(pk=ref_id).first()


def _serialize_ref(ref: RescreenReference) -> dict:
    return {
        'id': ref.id,
        'project_id': ref.project_id,
        'title': ref.title,
        'first_author': ref.first_author,
        'authors': ref.authors or [],
        'year': ref.year,
        'journal': ref.journal,
        'abstract': ref.abstract,
        'doi': ref.doi,
        'pmid': ref.pmid,
        'source_type': ref.source_type,
        'source_ref_id': ref.source_ref_id,
        'source_xml': ref.source_xml,
        'fulltext_status': ref.fulltext_status,
        'fulltext_error': ref.fulltext_error,
        'fulltext_source': ref.fulltext_source,
        'fulltext_source_url': ref.fulltext_source_url,
        'fulltext_license': ref.fulltext_license,
        'fulltext_resolver': ref.fulltext_resolver,
        'fulltext_checked_at': ref.fulltext_checked_at.isoformat() if ref.fulltext_checked_at else None,
        'fulltext_attempts': ref.fulltext_attempts or [],
        'fulltext_file_id': ref.fulltext_file_id,
        'fulltext_filename': ref.fulltext_file.filename if ref.fulltext_file else '',
        'fulltext_url': ref.fulltext_file.file.url if ref.fulltext_file and ref.fulltext_file.file else None,
        'fulltext_lookup_url': build_fulltext_lookup_url(ref),
        'ai_status': ref.ai_status,
        'ai_decision': ref.ai_decision,
        'ai_reason': ref.ai_reason,
        'ai_evidence': ref.ai_evidence or [],
        'consensus_status': ref.consensus_status,
        'multi_model_results': ref.multi_model_results or [],
        'human_decision': ref.human_decision,
        'exclusion_reason': ref.exclusion_reason,
        'review_note': ref.review_note,
        'reviewed_by': ref.reviewed_by.username if ref.reviewed_by else '',
        'reviewed_at': ref.reviewed_at.isoformat() if ref.reviewed_at else None,
        'created_at': ref.created_at.isoformat(),
        'updated_at': ref.updated_at.isoformat(),
    }


def _stats(project):
    refs = RescreenReference.objects.filter(project=project)
    total = refs.count()
    reviewed = refs.exclude(human_decision='').count()
    return {
        'total': total,
        'reviewed': reviewed,
        'unreviewed': total - reviewed,
        'included': refs.filter(human_decision='included').count(),
        'excluded': refs.filter(human_decision='excluded').count(),
        'pending': refs.filter(human_decision='pending').count(),
        'conflict': refs.filter(human_decision='', consensus_status='divergent').count(),
        'bound': refs.filter(fulltext_status='bound').count(),
        'unbound': refs.filter(fulltext_status='unbound').count(),
        'bind_failed': refs.filter(fulltext_status='bind_failed').count(),
        'ai_completed': refs.filter(ai_status='completed').count(),
    }


@login_required
@require_http_methods(['GET'])
def refs_list(request):
    project_id = request.GET.get('project_id')
    if not project_id:
        return _json_err('缺少 project_id')
    project = _get_project(request, project_id)
    if not project:
        return _json_err('无权访问该项目或项目不存在', 404)
    refs = RescreenReference.objects.filter(project=project).select_related('fulltext_file', 'reviewed_by')
    return _json_ok([_serialize_ref(ref) for ref in refs])


@login_required
@require_http_methods(['POST'])
def refs_import(request):
    body, error = _validated_json(request, RescreenImportInputSerializer)
    if error:
        return error
    project = _get_project(request, body['project_id'])
    if not project:
        return _json_err('无权访问该项目或项目不存在', 404)

    from core.rescreening.services import import_from_screening

    imported = import_from_screening(project, body['source_stage'], body.get('ref_ids'))
    ActivityLog.objects.create(
        project=project,
        operation_type='rescreen_import',
        operation_detail={'imported': len(imported), 'source_stage': body['source_stage']},
        created_by=request.user,
    )
    return _json_ok({'imported': len(imported), 'skipped': 0, 'ref_ids': imported})


def _uploaded_pdf_files(request):
    files = request.FILES.getlist('files') or request.FILES.getlist('file')
    if not files:
        return None, _json_err('未上传文件')
    max_pdf_bytes = 50 * 1024 * 1024
    invalid_files = [
        f.name for f in files
        if not f.name.lower().endswith('.pdf') or f.size > max_pdf_bytes
    ]
    if invalid_files:
        return None, _json_err({'files': [f'仅支持不超过 50MB 的 PDF: {name}' for name in invalid_files]})
    return files, None


def _create_data_file(project, uploaded_file, user, description):
    return DataFile.objects.create(
        project=project,
        filename=uploaded_file.name,
        file=uploaded_file,
        source='upload',
        data_category='input',
        description=description,
        created_by=user,
    )


def _authors_to_list(value):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if not value:
        return []
    return [part.strip() for part in str(value).replace('；', ';').split(';') if part.strip()]


def _safe_int(value):
    try:
        return int(value) if value not in (None, '') else None
    except (TypeError, ValueError):
        return None


def _ref_from_parsed_record(project, record, source_file):
    authors = _authors_to_list(record.get('authors'))
    return RescreenReference(
        project=project,
        title=(record.get('title') or source_file)[:500],
        first_author=(authors[0] if authors else '')[:200],
        authors=authors,
        year=_safe_int(record.get('year')),
        journal=(record.get('journal') or '')[:300],
        abstract=record.get('abstract') or '',
        doi=(record.get('doi') or '')[:200],
        pmid=(record.get('pmid') or record.get('PMID') or '')[:100],
        source_type='bibliography_upload',
        fulltext_status='unbound',
    )


@login_required
@require_http_methods(['POST'])
def refs_upload_bibliography(request):
    """上传题录文件，解析为复筛题录，全文状态默认未绑定。"""
    project_id = request.POST.get('project_id')
    if not project_id:
        return _json_err('缺少 project_id')
    project = _get_project(request, project_id)
    if not project:
        return _json_err('无权访问该项目或项目不存在', 404)

    uploaded_file = request.FILES.get('file') or request.FILES.get('files')
    if not uploaded_file:
        return _json_err('未上传题录文件')

    from core.screening.parsers import parse_file, supported_extensions

    suffix = '.' + uploaded_file.name.rsplit('.', 1)[-1].lower() if '.' in uploaded_file.name else ''
    if suffix not in supported_extensions():
        return _json_err(f'不支持的题录格式: {suffix or uploaded_file.name}')

    data_file = _create_data_file(project, uploaded_file, request.user, '文献复筛题录文件')

    try:
        data_file.file.open('rb')
        with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
            for chunk in data_file.file.chunks():
                tmp.write(chunk)
            tmp.flush()
            records = parse_file(tmp.name)
    except Exception as exc:
        data_file.metadata = {**(data_file.metadata or {}), 'parse_error': str(exc)}
        data_file.save(update_fields=['metadata', 'updated_at'])
        return _json_err(f'题录解析失败: {exc}')
    finally:
        try:
            data_file.file.close()
        except Exception:
            pass

    # 同一入口可多次上传：新增题录会追加到复筛文献列表，不替换既有文献。
    refs = [_ref_from_parsed_record(project, record, uploaded_file.name) for record in records]
    created_refs = RescreenReference.objects.bulk_create(refs)
    ActivityLog.objects.create(
        project=project,
        operation_type='rescreen_upload_bibliography',
        operation_detail={'count': len(created_refs), 'filename': uploaded_file.name},
        created_by=request.user,
    )
    return _json_ok({'created': len(created_refs), 'refs': [_serialize_ref(ref) for ref in created_refs]}, status=201)


@login_required
@require_http_methods(['POST'])
def fulltext_upload(request):
    """上传 PDF。带 ref_id 时绑定到既有题录；不带时创建 PDF 来源文献。"""
    project_id = request.POST.get('project_id')
    if not project_id:
        return _json_err('缺少 project_id')
    project = _get_project(request, project_id)
    if not project:
        return _json_err('无权访问该项目或项目不存在', 404)
    files, error = _uploaded_pdf_files(request)
    if error:
        return error
    ref_id = request.POST.get('ref_id')
    if ref_id and len(files) != 1:
        return _json_err('绑定到单篇题录时只能上传 1 个 PDF')

    target_ref = None
    if ref_id:
        target_ref = RescreenReference.objects.filter(project=project, pk=ref_id).first()
        if not target_ref:
            return _json_err('文献不存在或无权访问', 404)

    refs = []
    with transaction.atomic():
        # 同一入口可多次上传：新增 PDF 会追加到复筛文献列表，不替换既有文献；
        # 带 ref_id 的场景属于后续全文绑定/更改。
        for uploaded_file in files:
            data_file = _create_data_file(project, uploaded_file, request.user, '文献复筛全文PDF')
            if target_ref:
                ref = target_ref
                ref.fulltext_file = data_file
                ref.fulltext_status = 'bound'
                ref.fulltext_error = ''
                ref.fulltext_source = 'manual_upload'
                ref.fulltext_source_url = ''
                ref.fulltext_license = ''
                ref.fulltext_resolver = 'manual_upload'
                ref.fulltext_checked_at = timezone.now()
                ref.save(update_fields=['fulltext_file', 'fulltext_status', 'fulltext_error', 'fulltext_source', 'fulltext_source_url', 'fulltext_license', 'fulltext_resolver', 'fulltext_checked_at', 'updated_at'])
                try:
                    from core.rescreening.services import apply_pdf_meta_to_rescreen_ref
                    ref = apply_pdf_meta_to_rescreen_ref(ref)
                except Exception:
                    pass
            else:
                title = uploaded_file.name.rsplit('.', 1)[0].replace('_', ' ')
                ref = RescreenReference.objects.create(
                    project=project,
                    title=title,
                    source_type='pdf_upload',
                    fulltext_file=data_file,
                    fulltext_status='bound',
                    fulltext_source='manual_upload',
                    fulltext_resolver='manual_upload',
                    fulltext_checked_at=timezone.now(),
                )
                try:
                    from core.rescreening.services import apply_pdf_meta_to_rescreen_ref
                    ref = apply_pdf_meta_to_rescreen_ref(ref)
                except Exception:
                    pass
            refs.append(ref)
        ActivityLog.objects.create(
            project=project,
            operation_type='rescreen_upload_pdf',
            operation_detail={'count': len(refs), 'filenames': [f.name for f in files]},
            created_by=request.user,
        )
    return _json_ok({'created': len(refs), 'refs': [_serialize_ref(ref) for ref in refs]}, status=201)


@login_required
@require_http_methods(['POST'])
def fulltext_replace(request):
    """更改已绑定全文。"""
    ref_id = request.POST.get('ref_id')
    if not ref_id:
        return _json_err('缺少 ref_id')
    ref = _get_ref(request, ref_id)
    if not ref:
        return _json_err('文献不存在或无权访问', 404)
    files, error = _uploaded_pdf_files(request)
    if error:
        return error
    if len(files) != 1:
        return _json_err('更改全文时只能上传 1 个 PDF')
    data_file = _create_data_file(ref.project, files[0], request.user, '文献复筛全文PDF（更改）')
    ref.fulltext_file = data_file
    ref.fulltext_status = 'bound'
    ref.fulltext_error = ''
    ref.fulltext_source = 'manual_upload'
    ref.fulltext_source_url = ''
    ref.fulltext_license = ''
    ref.fulltext_resolver = 'manual_upload'
    ref.fulltext_checked_at = timezone.now()
    ref.save(update_fields=['fulltext_file', 'fulltext_status', 'fulltext_error', 'fulltext_source', 'fulltext_source_url', 'fulltext_license', 'fulltext_resolver', 'fulltext_checked_at', 'updated_at'])
    try:
        from core.rescreening.services import apply_pdf_meta_to_rescreen_ref
        ref = apply_pdf_meta_to_rescreen_ref(ref)
    except Exception:
        pass
    return _json_ok(_serialize_ref(ref))


@login_required
@require_http_methods(['POST'])
def fulltext_auto_search(request):
    """自动查找全文。

    按顺序复用项目内已上传 PDF，并从 Europe PMC / Unpaywall 等开放获取来源
    自动下载 PDF 后直接绑定；找不到则进入“绑定失败”，用户可人工上传。
    """
    body, error = _validated_json(request, RescreenAutoSearchInputSerializer)
    if error:
        return error
    project = _get_project(request, body['project_id'])
    if not project:
        return _json_err('无权访问该项目或项目不存在', 404)
    qs = RescreenReference.objects.filter(project=project)
    if body.get('ref_ids'):
        qs = qs.filter(pk__in=list(dict.fromkeys(body['ref_ids'])))

    from core.rescreening.services import auto_bind_fulltexts

    result = auto_bind_fulltexts(project, body.get('ref_ids'), user=request.user)
    ActivityLog.objects.create(
        project=project,
        operation_type='rescreen_auto_fulltext_search',
        operation_detail=result,
        created_by=request.user,
    )
    return _json_ok({
        **result,
        'refs': [_serialize_ref(ref) for ref in qs.select_related('fulltext_file')],
    })


@login_required
@require_http_methods(['GET', 'POST'])
def criteria(request):
    if request.method == 'GET':
        project_id = request.GET.get('project_id')
        if not project_id:
            return _json_err('缺少 project_id')
        project = _get_project(request, project_id)
        if not project:
            return _json_err('无权访问该项目或项目不存在', 404)
        obj = RescreenCriteria.objects.filter(project=project).first()
        return _json_ok({'project_id': project.id, 'criteria_list': obj.criteria_list if obj else []})

    body, error = _validated_json(request, RescreenCriteriaInputSerializer)
    if error:
        return error
    project = _get_project(request, body['project_id'])
    if not project:
        return _json_err('无权访问该项目或项目不存在', 404)
    obj, _ = RescreenCriteria.objects.update_or_create(
        project=project,
        defaults={'criteria_list': body['criteria_list'], 'updated_by': request.user},
    )
    return _json_ok({'project_id': project.id, 'criteria_list': obj.criteria_list, 'updated_at': obj.updated_at.isoformat()})


@login_required
@require_http_methods(['GET'])
def review_list(request):
    project_id = request.GET.get('project_id') or request.GET.get('project')
    if not project_id:
        return _json_err('缺少 project_id')
    project = _get_project(request, project_id)
    if not project:
        return _json_err('无权访问该项目或项目不存在', 404)

    decision = request.GET.get('decision', '')
    q = (request.GET.get('q') or '').strip().lower()
    try:
        page = max(int(request.GET.get('page', 1)), 1)
        page_size = max(min(int(request.GET.get('page_size', 50)), 200), 1)
    except (TypeError, ValueError):
        return _json_err('page 和 page_size 必须是正整数')

    refs = RescreenReference.objects.filter(project=project).select_related('fulltext_file', 'reviewed_by')
    if q:
        refs = refs.filter(title__icontains=q)
    if decision == 'unreviewed':
        refs = refs.filter(human_decision='')
    elif decision == 'conflict':
        refs = refs.filter(human_decision='', consensus_status='divergent')
    elif decision in ('included', 'excluded', 'pending'):
        refs = refs.filter(human_decision=decision)

    total = refs.count()
    start = (page - 1) * page_size
    return JsonResponse({
        'total': total,
        'page': page,
        'page_size': page_size,
        'results': [_serialize_ref(ref) for ref in refs[start:start + page_size]],
    })


@login_required
@require_http_methods(['PATCH'])
def review_update(request, ref_id):
    ref = _get_ref(request, ref_id)
    if not ref:
        return _json_err('文献不存在或无权访问', 404)
    body, error = _validated_json(request, RescreenReviewInputSerializer)
    if error:
        return error
    ref.human_decision = body['human_decision']
    ref.exclusion_reason = body.get('exclusion_reason', '').strip() if body['human_decision'] == 'excluded' else ''
    ref.review_note = body.get('review_note', '').strip()
    ref.reviewed_by = request.user
    ref.reviewed_at = timezone.now()
    ref.save(update_fields=['human_decision', 'exclusion_reason', 'review_note', 'reviewed_by', 'reviewed_at', 'updated_at'])
    return _json_ok(_serialize_ref(ref))


@login_required
@require_http_methods(['POST'])
def review_batch_include(request):
    body, error = _validated_json(request, RescreenBatchIncludeInputSerializer)
    if error:
        return error
    project = _get_project(request, body['project_id'])
    if not project:
        return _json_err('无权访问该项目或项目不存在', 404)
    from core.rescreening.services import batch_include_consistent

    updated = batch_include_consistent(project, request.user, body.get('ref_ids'))
    return _json_ok({'updated': updated})


@login_required
@require_http_methods(['GET'])
def review_stats(request):
    project_id = request.GET.get('project_id') or request.GET.get('project')
    if not project_id:
        return _json_err('缺少 project_id')
    project = _get_project(request, project_id)
    if not project:
        return _json_err('无权访问该项目或项目不存在', 404)
    return _json_ok(_stats(project))


@login_required
@require_http_methods(['POST'])
def ai_start(request):
    """启动真实 AI 全文复筛任务。"""
    body, error = _validated_json(request, RescreenAIStartInputSerializer)
    if error:
        return error
    project = _get_project(request, body['project_id'])
    if not project:
        return _json_err('无权访问该项目或项目不存在', 404)

    criteria_obj = RescreenCriteria.objects.filter(project=project).first()
    criteria_list = [str(item).strip() for item in (criteria_obj.criteria_list if criteria_obj else []) if str(item).strip()]
    if not criteria_list:
        return _json_err('请先填写复筛纳排标准后再启动 AI 全文复筛')

    ref_ids = body.get('ref_ids') or []
    qs = RescreenReference.objects.filter(project=project)
    if ref_ids:
        qs = qs.filter(pk__in=list(dict.fromkeys(ref_ids)))

    bound_qs = qs.filter(fulltext_status='bound', fulltext_file__isnull=False)
    queued_count = bound_qs.count()
    if queued_count == 0:
        skipped = qs.exclude(fulltext_status='bound').update(ai_status='skipped_unbound')
        return _json_err({'detail': '没有已绑定全文的文献可进入 AI 复筛', 'skipped_unbound': skipped})

    config = {
        'ref_ids': list(bound_qs.values_list('id', flat=True)),
        'ai_models': body.get('ai_models') or ([body.get('ai_model')] if body.get('ai_model') else []),
        'enable_thinking': body.get('enable_thinking') is True,
    }

    # 先落库为 queued，避免 Celery worker 抢先执行后又被 API 线程覆盖结果。
    bound_qs.update(ai_status='queued', ai_decision='', ai_reason='', consensus_status='', ai_evidence=[], multi_model_results=[])
    skipped = qs.exclude(fulltext_status='bound').update(ai_status='skipped_unbound')

    try:
        from core.services import start_task
        task = start_task(project.id, 'rescreen_ai', config, request.user)
    except PermissionError as exc:
        bound_qs.update(ai_status='not_started')
        return _json_err(str(exc), 403)
    except ValueError as exc:
        bound_qs.update(ai_status='not_started')
        return _json_err(str(exc))
    except Exception as exc:
        bound_qs.update(ai_status='not_started')
        return _json_err(f'启动 AI 全文复筛失败: {exc}')
    ActivityLog.objects.create(
        project=project,
        operation_type='task_start_rescreen_ai',
        operation_detail={'task_id': task.id, 'queued': queued_count, 'skipped_unbound': skipped},
        created_by=request.user,
    )
    return _json_ok({'task_id': task.id, 'queued': queued_count, 'skipped_unbound': skipped})


@login_required
@require_http_methods(['GET'])
def ai_progress(request):
    project_id = request.GET.get('project_id')
    if not project_id:
        return _json_err('缺少 project_id')
    project = _get_project(request, project_id)
    if not project:
        return _json_err('无权访问该项目或项目不存在', 404)
    refs = RescreenReference.objects.filter(project=project)
    total = refs.count()
    finished = refs.filter(ai_status__in=['completed', 'failed', 'skipped_unbound']).count()
    progress = round(finished / total * 100, 1) if total else 0
    return _json_ok({'total': total, 'finished': finished, 'progress': progress})


def _refs_for_export(project, scope):
    refs = RescreenReference.objects.filter(project=project).select_related('fulltext_file', 'reviewed_by')
    if scope == 'included':
        refs = refs.filter(human_decision='included')
    elif scope == 'excluded':
        refs = refs.filter(human_decision='excluded')
    elif scope == 'missing_pdf':
        refs = refs.exclude(fulltext_status='bound')
    return refs.order_by('id')


def _decision_label(value):
    return {'included': '纳入', 'excluded': '排除', 'pending': '待定', '': ''}.get(value, value)


def _fulltext_label(value):
    return {'bound': '已绑定', 'unbound': '未绑定', 'bind_failed': '绑定失败'}.get(value, value)


def _safe_filename(value):
    import re
    cleaned = re.sub(r'[\\/:*?"<>|]+', '_', str(value or 'paper')).strip(' ._')
    return (cleaned[:120] or 'paper')


@login_required
@require_http_methods(['POST'])
def export_excel(request):
    """导出复筛结果 Excel。"""
    body, error = _validated_json(request, RescreenExportInputSerializer)
    if error:
        return error
    project = _get_project(request, body['project_id'])
    if not project:
        return _json_err('无权访问该项目或项目不存在', 404)

    import openpyxl

    scope = body.get('scope') or 'all'
    refs = list(_refs_for_export(project, scope))
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '文献复筛结果'
    headers = [
        '序号', '标题', '第一作者', '年份', '期刊', 'DOI', 'PMID',
        '来源', '全文状态', 'PDF文件', 'AI状态', 'AI建议', 'AI理由',
        'AI一致性', '人工最终决定', '人工排除理由', '人工备注', '审阅人', '审阅时间',
    ]
    ws.append(headers)
    for index, ref in enumerate(refs, start=1):
        ws.append([
            index,
            ref.title,
            ref.first_author,
            ref.year or '',
            ref.journal,
            ref.doi,
            ref.pmid,
            ref.get_source_type_display(),
            _fulltext_label(ref.fulltext_status),
            ref.fulltext_file.filename if ref.fulltext_file else '',
            ref.get_ai_status_display(),
            _decision_label(ref.ai_decision),
            ref.ai_reason,
            ref.get_consensus_status_display() if ref.consensus_status else '',
            _decision_label(ref.human_decision),
            ref.exclusion_reason,
            ref.review_note,
            ref.reviewed_by.username if ref.reviewed_by else '',
            ref.reviewed_at.strftime('%Y-%m-%d %H:%M:%S') if ref.reviewed_at else '',
        ])

    widths = [8, 44, 16, 10, 24, 20, 16, 14, 12, 28, 12, 12, 42, 12, 14, 36, 30, 14, 20]
    for column, width in zip(ws.columns, widths):
        ws.column_dimensions[column[0].column_letter].width = width
    stream = io.BytesIO()
    wb.save(stream)
    filename = f'rescreening_{scope}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    response = HttpResponse(
        stream.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    ActivityLog.objects.create(
        project=project,
        operation_type='rescreen_export_excel',
        operation_detail={'scope': scope, 'count': len(refs), 'filename': filename},
        created_by=request.user,
    )
    return response


@login_required
@require_http_methods(['POST'])
def export_pdf_package(request):
    """打包导出人工最终纳入文献对应 PDF。"""
    body, error = _validated_json(request, RescreenExportInputSerializer)
    if error:
        return error
    project = _get_project(request, body['project_id'])
    if not project:
        return _json_err('无权访问该项目或项目不存在', 404)

    refs = list(_refs_for_export(project, 'included').filter(fulltext_status='bound', fulltext_file__isnull=False))
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        manifest_rows = ['序号,文献ID,标题,PDF文件']
        used_names = set()
        for index, ref in enumerate(refs, start=1):
            data_file = ref.fulltext_file
            if not data_file or not data_file.file:
                continue
            try:
                path = data_file.file.path
                base = f'{index:03d}_{_safe_filename(ref.first_author or ref.title)}_{ref.year or ""}.pdf'
                name = base
                suffix = 1
                while name in used_names:
                    suffix += 1
                    name = base.replace('.pdf', f'_{suffix}.pdf')
                used_names.add(name)
                zf.write(path, arcname=name)
                manifest_rows.append(f'{index},{ref.id},"{ref.title.replace(chr(34), chr(34)*2)}","{name}"')
            except Exception as exc:
                manifest_rows.append(f'{index},{ref.id},"{ref.title.replace(chr(34), chr(34)*2)}","导出失败: {exc}"')
        if len(manifest_rows) == 1:
            zf.writestr('README.txt', '没有可导出的人工最终纳入 PDF。请先完成人工审阅并确保文献已绑定 PDF。')
        zf.writestr('manifest.csv', '\n'.join(manifest_rows).encode('utf-8-sig'))

    filename = f'rescreening_included_pdfs_{timezone.now().strftime("%Y%m%d_%H%M%S")}.zip'
    response = HttpResponse(stream.getvalue(), content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    ActivityLog.objects.create(
        project=project,
        operation_type='rescreen_export_pdf_package',
        operation_detail={'count': len(refs), 'filename': filename},
        created_by=request.user,
    )
    return response
