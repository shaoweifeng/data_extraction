"""QA 人工结果审核 HTTP 适配层。"""

from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods

from core.models import QADomainResult
from core.quality.api.common import (
    _get_qa_ref, _get_signal_item, _json_err, _json_ok, _safe_list,
    _serialize_domain, _serialize_signal, _validated_json,
)
from core.quality.api.serializers import (
    QAProjectBatchConfirmInputSerializer, QASignalBatchConfirmInputSerializer,
    QASignalConfirmInputSerializer,
)
from core.quality.services.domain_results import recalculate_domain_results as _recalc_domain_results


@login_required
@require_http_methods(['GET'])
def signal_items_list(request):
    """GET /api/qa/signal-items/?qa_ref_id=&domain=&result_type=&is_confirmed="""
    qa_ref_id = request.GET.get('qa_ref_id')
    if not qa_ref_id:
        return _json_err('缺少 qa_ref_id')
    ref = _get_qa_ref(request, qa_ref_id)
    if not ref:
        return _json_err('无权访问该文献或文献不存在', 404)

    qs = ref.signal_items.select_related('confirmed_by').all()
    if request.GET.get('domain'):
        qs = qs.filter(domain=request.GET['domain'])
    if request.GET.get('result_type'):
        qs = qs.filter(result_type=request.GET['result_type'])
    if request.GET.get('is_confirmed') == 'false':
        qs = qs.filter(is_confirmed=False)
    elif request.GET.get('is_confirmed') == 'true':
        qs = qs.filter(is_confirmed=True)

    from core.services.access_policy import ProjectAccessPolicy

    include_audit = ProjectAccessPolicy.is_platform_admin(request.user)
    return _json_ok([_serialize_signal(i, include_audit=include_audit) for i in qs])


@login_required
@require_http_methods(['GET'])
def signal_evidence_context(request, item_id):
    """Return only the cited chunk and one bounded neighbor on either side."""
    item = _get_signal_item(request, item_id)
    if not item:
        return _json_err('无权访问该信号问题或信号问题不存在', 404)
    chunk_id = str(request.GET.get('chunk_id') or '').strip()
    if not chunk_id:
        return _json_err('缺少 chunk_id')
    model_id = str(request.GET.get('model_id') or '').strip()
    from core.quality.services.evidence_context import get_signal_evidence_context
    from core.quality.services.evidence_retrieval import EvidenceRetrievalError

    try:
        payload = get_signal_evidence_context(
            item,
            chunk_id=chunk_id,
            model_id=model_id,
        )
    except EvidenceRetrievalError as exc:
        return _json_err(str(exc), 404)
    return _json_ok(payload)


@login_required
@require_http_methods(['GET'])
def evaluation_audit(request):
    """Admin-only extraction, evidence-version and latest project usage audit."""
    from core.models_billing import TokenUsageLog
    from core.services.access_policy import ProjectAccessPolicy

    if not ProjectAccessPolicy.is_platform_admin(request.user):
        return _json_err('仅管理员可以查看评价审计信息', 403)
    qa_ref_id = request.GET.get('qa_ref_id')
    if not qa_ref_id:
        return _json_err('缺少 qa_ref_id')
    ref = _get_qa_ref(request, qa_ref_id)
    if not ref:
        return _json_err('文献不存在', 404)
    try:
        asset = ref.fulltext_asset
    except Exception:
        asset = None
    versions = set()
    for results in ref.signal_items.values_list('model_results', flat=True):
        for result in results or []:
            if isinstance(result, dict):
                versions.add(tuple(str(result.get(key) or '') for key in (
                    'prompt_version', 'retrieval_version', 'method_config_version',
                    'evidence_snapshot_sha256',
                )))
    usage = TokenUsageLog.objects.filter(
        project=ref.project,
        task__task_type='qa_eval',
    ).order_by('-created_at').first()
    return _json_ok({
        'reference_id': ref.id,
        'asset': None if not asset else {
            'id': asset.id,
            'status': asset.status,
            'page_count': asset.page_count,
            'extracted_page_count': asset.extracted_page_count,
            'extracted_text_chars': asset.extracted_text_chars,
            'extraction_truncated': asset.extraction_truncated,
            'truncated_at_page': asset.truncated_at_page,
            'extraction_version': asset.extraction_version,
            'chunking_version': asset.chunking_version,
            'chunk_count': asset.chunk_count,
        },
        'evidence_versions': [
            {
                'prompt_version': prompt,
                'retrieval_version': retrieval,
                'method_config_version': method,
                'evidence_snapshot_sha256': snapshot,
            }
            for prompt, retrieval, method, snapshot in sorted(versions)
        ],
        'latest_project_usage': None if not usage else {
            'task_id': usage.task_id,
            'model': usage.model,
            'prompt_tokens': usage.prompt_tokens,
            'completion_tokens': usage.completion_tokens,
            'total_tokens': usage.total_tokens,
            'credits_consumed': usage.credits_consumed,
            'usage_breakdown': usage.usage_breakdown,
            'pricing_version': usage.pricing_version,
            'shadow_credits': usage.shadow_credits,
            'estimated_cost_cny': (
                str(usage.estimated_cost_cny) if usage.estimated_cost_cny is not None else None
            ),
            'ref_count': usage.ref_count,
            'recorded_at': usage.created_at.isoformat(),
        },
    })


@login_required
@require_http_methods(['PATCH'])
def signal_item_confirm(request, item_id):
    """PATCH /api/qa/signal-items/<id>/confirm/ — 确认单条信号问题"""
    item = _get_signal_item(request, item_id)
    if not item:
        return _json_err('无权访问该信号问题或信号问题不存在', 404)
    body, error = _validated_json(request, QASignalConfirmInputSerializer)
    if error:
        return error

    human_judgment = body['human_judgment']
    allowed_options = _safe_list(item.options)
    if allowed_options and human_judgment not in allowed_options:
        return _json_err({'human_judgment': ['判断值不在该信号问题的允许选项中']})

    from core.quality.services.review_service import confirm_signal

    confirm_signal(item, human_judgment, request.user)

    # ActivityLog
    from core.models import ActivityLog
    ActivityLog.objects.create(
        project=item.qa_ref.project,
        operation_type='qa_confirm_signal',
        operation_detail={
            'qa_ref_id': item.qa_ref_id,
            'signal_key': item.signal_key,
            'judgment': human_judgment,
            'modified': item.is_modified,
        },
        created_by=request.user,
    )
    from core.services.access_policy import ProjectAccessPolicy
    return _json_ok(_serialize_signal(
        item,
        include_audit=ProjectAccessPolicy.is_platform_admin(request.user),
    ))


@login_required
@require_http_methods(['POST'])
def signal_batch_confirm(request):
    """
    POST /api/qa/signal-items/batch-confirm/
    Body: {
      "qa_ref_id": 1,
      "confirm_mode": "adopt_preselected" | "adopt_ai" | "specific_keys",
      "signal_keys": [...],   # confirm_mode=specific_keys 时使用
    }
    """
    body, error = _validated_json(request, QASignalBatchConfirmInputSerializer)
    if error:
        return error

    qa_ref_id = body['qa_ref_id']
    confirm_mode = body['confirm_mode']
    signal_keys = body['signal_keys']

    ref = _get_qa_ref(request, qa_ref_id)
    if not ref:
        return _json_err('无权访问该文献或文献不存在', 404)

    from core.quality.services.review_service import batch_confirm

    confirmed_count = batch_confirm(ref, confirm_mode, signal_keys, request.user)

    # ActivityLog
    from core.models import ActivityLog
    ActivityLog.objects.create(
        project=ref.project,
        operation_type='qa_batch_confirm',
        operation_detail={
            'qa_ref_id': qa_ref_id,
            'confirm_mode': confirm_mode,
            'confirmed_count': confirmed_count,
        },
        created_by=request.user,
    )
    return _json_ok({'confirmed': confirmed_count})


@login_required
@require_http_methods(['POST'])
def project_batch_confirm(request):
    """一次确认项目内所有已有评价结果，自动排除未评价和无信号文献。"""
    body, error = _validated_json(request, QAProjectBatchConfirmInputSerializer)
    if error:
        return error
    from core.quality.api.common import _get_project

    project = _get_project(request, body['project_id'])
    if not project:
        return _json_err('无权访问该项目或项目不存在', 404)

    from core.quality.services.review_service import batch_confirm_project

    result = batch_confirm_project(project, body['confirm_mode'], request.user)
    from core.models import ActivityLog
    ActivityLog.objects.create(
        project=project,
        operation_type='qa_batch_confirm',
        operation_detail={
            'scope': 'project_evaluated_only',
            'confirm_mode': body['confirm_mode'],
            'confirmed_references': result['references'],
            'confirmed_signals': result['signals'],
        },
        created_by=request.user,
    )
    return _json_ok(result)


# ─────────────────────────────────────────────────────────────────────────────
# 领域汇总结果
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@require_http_methods(['GET'])
def domain_results(request):
    """GET /api/qa/domain-results/?qa_ref_id="""
    qa_ref_id = request.GET.get('qa_ref_id')
    if not qa_ref_id:
        return _json_err('缺少 qa_ref_id')
    ref = _get_qa_ref(request, qa_ref_id)
    if not ref:
        return _json_err('无权访问该文献或文献不存在', 404)
    qs = QADomainResult.objects.filter(qa_ref=ref)
    return _json_ok([_serialize_domain(dr) for dr in qs])


# ─────────────────────────────────────────────────────────────────────────────
# 图表
# ─────────────────────────────────────────────────────────────────────────────
