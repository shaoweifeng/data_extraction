"""QA 人工结果审核 HTTP 适配层。"""

from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods

from core.models import QADomainResult
from core.quality.api.common import (
    _get_qa_ref, _get_signal_item, _json_err, _json_ok, _safe_list,
    _serialize_domain, _serialize_signal, _validated_json,
)
from core.quality.api.serializers import (
    QASignalBatchConfirmInputSerializer, QASignalConfirmInputSerializer,
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

    return _json_ok([_serialize_signal(i) for i in qs])


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
    return _json_ok(_serialize_signal(item))


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
