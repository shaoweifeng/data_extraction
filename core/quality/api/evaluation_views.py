"""QA AI 评价 HTTP 适配层。"""

import logging

from django.contrib.auth.decorators import login_required
from django.db import models
from django.views.decorators.http import require_http_methods

from core.models import QAReference, QASignalItem
from core.quality.api.common import _get_project, _json_err, _json_ok, _validated_json
from core.quality.api.serializers import QAEvalStartInputSerializer


logger = logging.getLogger(__name__)


@login_required
@require_http_methods(['POST'])
def eval_start(request):
    """POST /api/qa/eval/start/ — 启动统一 QA 评价任务。"""
    body, error = _validated_json(request, QAEvalStartInputSerializer)
    if error:
        return error
    project = _get_project(request, body['project_id'])
    if not project:
        return _json_err('无权访问该项目或项目不存在', 404)

    from core.quality.services.evaluation_service import start_evaluation

    try:
        result = start_evaluation(
            project,
            request.user,
            list(dict.fromkeys(body['ref_ids'])),
            body['model_ids'],
        )
    except ValueError as exc:
        return _json_err(str(exc))
    except Exception as exc:
        logger.exception('QA 评价任务提交失败')
        return _json_err(f'任务提交失败: {exc}', 500)
    return _json_ok(result)


def _get_qa_token_stats(project, user):
    """从 TokenUsageLog 查本项目最近一次 QA 评价的实际 token/积分消耗。"""
    try:
        from core.models_billing import TokenUsageLog
        # 优先通过 project 字段直接关联（新写法），兼容通过 task 关联的旧记录
        log = (
            TokenUsageLog.objects
            .filter(user=user)
            .filter(
                models.Q(project=project) | models.Q(task__project=project)
            )
            .order_by('-created_at')
            .first()
        )
        if log:
            return {
                'total_tokens':      log.total_tokens,
                'prompt_tokens':     log.prompt_tokens,
                'completion_tokens': log.completion_tokens,
                'credits_consumed':  log.credits_consumed,
                'ref_count':         log.ref_count,
                'model':             log.model,
                'recorded_at':       log.created_at.isoformat(),
            }
    except Exception:
        pass
    return None


@login_required
@require_http_methods(['GET'])
def eval_progress(request):
    """GET /api/qa/eval/progress/?project_id="""
    project_id = request.GET.get('project_id')
    if not project_id:
        return _json_err('缺少 project_id')
    project = _get_project(request, project_id)
    if not project:
        return _json_err('项目不存在', 404)

    refs = QAReference.objects.filter(project=project)
    total       = refs.count()
    pending     = refs.filter(ai_eval_status='pending').count()
    running     = refs.filter(ai_eval_status='running').count()
    completed   = refs.filter(ai_eval_status='completed').count()
    failed      = refs.filter(ai_eval_status__in=['failed', 'skipped_no_fulltext', 'skipped_no_method']).count()
    abstract_only = refs.filter(ai_eval_status='abstract_only').count()

    # 双模型信号问题一致性统计
    divergent_count = QASignalItem.objects.filter(
        qa_ref__project=project,
        consistency='divergent',
    ).count()

    unconfirmed_count = QASignalItem.objects.filter(
        qa_ref__project=project,
        qa_ref__ai_eval_status__in=['completed', 'abstract_only'],
        is_confirmed=False,
    ).count()

    # 文献级进度列表
    ref_list_data = []
    for ref in refs.select_related('fulltext_file'):
        # 双模型分歧数
        div = QASignalItem.objects.filter(qa_ref=ref, consistency='divergent').count() if ref.eval_mode == 'dual' else 0
        ref_list_data.append({
            'id':             ref.id,
            'title':          ref.title,
            'quality_method': ref.quality_method,
            'eval_mode':      ref.eval_mode,
            'ai_eval_status': ref.ai_eval_status,
            'review_status':  ref.review_status,
            'divergent_count': div,
        })

    return _json_ok({
        'summary': {
            'total':        total,
            'pending':      pending,
            'running':      running,
            'completed':    completed + abstract_only,
            'failed':       failed,
            'abstract_only': abstract_only,
            'divergent_signal_count': divergent_count,
        },
        'refs': ref_list_data,
        'token_stats': _get_qa_token_stats(project, request.user),
    })


# ─────────────────────────────────────────────────────────────────────────────
# 信号问题
# ─────────────────────────────────────────────────────────────────────────────
