"""Checkpointed real-provider execution, one shared call slot per task.

No network retry is implicit. Completed model results are immutable on resume;
failed protocol responses retain their usage but are platform-borne.
"""
import hashlib
import logging
from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from core.ai.providers import get_provider, provider_is_configured
from core.models import Task
from core.rescreening.errors import RescreenError
from core.rescreening.models import RescreenRun, RescreenRunItem, RescreenModelResult, RescreenCall
from core.rescreening.services import ai_billing as billing, ai_protocol as protocol
from core.services.ai_models_config import get_model_config

logger = logging.getLogger(__name__)


def _platform_borne(usage):
    usage = dict(usage or {})
    usage['call_details'] = [{**detail, 'charge_bearer': 'platform'} for detail in usage.get('call_details', [])]
    return usage


def _stop(run, task, check_stop):
    return (check_stop() or not RescreenRun.objects.filter(pk=run.pk, task=task, status='running').exists()
            or Task.objects.filter(pk=task.pk, status__in=('stopping', 'stopped', 'failed')).exists())


def _evaluate_batch(result, run, task, check_stop, package, criteria, prompt):
    item = result.item
    limits = run.config_snapshot['limits']
    input_tokens = protocol.call_budget(prompt, result.model_id, limits)
    live_config = get_model_config(result.model_id)
    if not live_config or not provider_is_configured(result.model_id):
        raise RescreenError('model_not_configured', '模型凭据不可用。', status=503)
    if item.reference.input_version != item.input_version or item.reference.removed_revision is not None:
        raise RescreenError('input_changed', '文献输入已经变化。', status=409)
    # The PDF cannot be rebuilt/deleted while cited by an item; recheck its
    # identities as well so a damaged/misbound source is never accepted.
    asset = item.asset
    if (not asset or asset.project_id != run.corpus.project_id or asset.sha256 != item.asset_sha256
            or asset.extracted_text_sha256 != item.evidence_package['text_sha256']
            or asset.chunk_index_sha256 != item.evidence_package['index_sha256']):
        raise RescreenError('input_changed', '全文资产身份或派生版本已经变化。', status=409)
    from core.services.concurrency_service import refresh_task_slots
    if not refresh_task_slots(task, stop_checker=lambda: _stop(run, task, check_stop)):
        return False
    billing.before_call(task, run, billing.estimated_call(result.model_id, input_tokens, limits['output_tokens']))
    if _stop(run, task, check_stop):
        return False
    with transaction.atomic():
        locked = RescreenModelResult.objects.select_for_update().get(pk=result.pk)
        previous = list(locked.calls.filter(criterion_ids=package['criterion_ids']).order_by('attempt'))
        attempt = locked.calls.count() + 1
        if attempt > limits['max_calls']:
            raise RescreenError('call_limit', '单文献单模型调用次数已达上限。', status=409)
        if locked.status == 'completed':
            return True
        call = RescreenCall.objects.create(result=locked, task=task, attempt=attempt,
            prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(), criterion_ids=package['criterion_ids'])
        locked.status = 'running'
        locked.save(update_fields=['status', 'updated_at'])
    config = {**live_config, **run.config_snapshot['model_configs'][result.model_id], 'reject_prompt_truncation': True,
              'max_output_tokens': limits['output_tokens']}
    try:
        response, usage = get_provider(result.model_id, config=config).generate_text(prompt)
    except Exception:
        RescreenCall.objects.filter(pk=call.pk).update(status='unknown', error_code='provider_exception', finished_at=timezone.now())
        raise RescreenError('provider_exception', '模型请求异常，其处理结果未知，请检查后重试。')
    # This write precedes parsing; a bad JSON/citation can never discard an
    # already incurred call. Provider request IDs/cache tiers remain intact.
    call.usage = dict(usage or {})
    call.usage['call_details'] = [{**detail, 'attempt_number': len(previous)+1,
        'attempt_reason': 'initial' if not previous else 'protocol_retry' if previous[-1].status == 'invalid' else 'user_retry',
        'charge_bearer': 'platform' if previous and previous[-1].status == 'invalid' else detail.get('charge_bearer', 'user')}
        for detail in call.usage.get('call_details', [])]
    call.response = response[:64000] if isinstance(response, str) else ''
    call.finished_at = timezone.now()
    call.status = 'received' if usage else 'unknown'
    with transaction.atomic():
        current = RescreenRun.objects.select_for_update().get(pk=run.pk)
        stale = current.task_id != task.pk or current.status not in ('running', 'cancelling')
        if stale:
            call.usage = _platform_borne(call.usage)
            call.status, call.error_code = 'late_received', 'stale_execution'
        call.save(update_fields=['usage', 'response', 'status', 'error_code', 'finished_at'])
    if stale:
        # Preserve late cost for audit, but never charge it after a recovery has
        # released/settled the old hold or publish over a newer generation.
        return False
    if not usage or not usage.get('call_details'):
        call.status, call.error_code = 'unknown', 'usage_missing'
        call.save(update_fields=['status', 'error_code'])
        raise RescreenError('usage_missing', '模型未返回可审计用量，未发布评价结论。')
    try:
        parsed = protocol.parse_result(response, package, criteria)
    except RescreenError as exc:
        call.usage = _platform_borne(call.usage)
        call.status, call.error_code = 'invalid', exc.code
        call.save(update_fields=['usage', 'status', 'error_code'])
        raise
    with transaction.atomic():
        current = RescreenRun.objects.select_for_update().get(pk=run.pk)
        if current.task_id != task.pk or current.status not in ('running', 'cancelling'):
            call.usage, call.status, call.error_code = _platform_borne(call.usage), 'late_received', 'stale_execution'
            call.save(update_fields=['usage', 'status', 'error_code'])
            return False
        call.status = 'completed'
        call.parsed_result = parsed
        call.save(update_fields=['status', 'parsed_result'])
    return True


def _evaluate(result, run, task, check_stop):
    item = result.item
    done = {tuple(call.criterion_ids): call for call in result.calls.filter(status='completed')}
    for package, criteria, prompt in protocol.requests_for(item.evidence_package, item.bibliography_snapshot,
            run.criteria_revision.criteria, template=run.config_snapshot['prompt_template']):
        if tuple(package['criterion_ids']) in done:
            continue
        if not _evaluate_batch(result, run, task, check_stop, package, criteria, prompt):
            return False
    calls = list(result.calls.filter(status='completed').order_by('attempt'))
    by_batch = {tuple(call.criterion_ids): call.parsed_result for call in calls}
    rows = [row for value in by_batch.values() for row in value['criteria_results']]
    result.decision = ('excluded' if any(row['judgment'] == 'violated' for row in rows) else
        'included' if all(row['judgment'] == 'satisfied' for row in rows) else 'pending')
    result.reason = '\n'.join(value['reason'] for value in by_batch.values())[:4000]
    result.criteria_results = rows
    evidence = {row['id']: row for value in by_batch.values() for row in value['evidence']}
    result.evidence = list(evidence.values())
    from core.ai import TokenUsageAccumulator
    total = TokenUsageAccumulator()
    for call in result.calls.all():
        total.add(call.usage, result.model_id)
    result.usage = total.as_dict()
    result.status, result.error_code, result.error_message = 'completed', '', ''
    with transaction.atomic():
        current = RescreenRun.objects.select_for_update().get(pk=run.pk)
        if current.task_id != task.pk or current.status not in ('running', 'cancelling'):
            return False
        result.save()
    return True


def _item_state(item):
    results = list(item.model_results.all())
    item.consensus = protocol.consensus(results)
    done = sum(row.status == 'completed' for row in results)
    item.status = 'completed' if done == len(results) else 'partial' if done else 'failed'
    from django.db.models import F
    item.result_revision = F('result_revision') + 1
    item.save(update_fields=['status', 'consensus', 'result_revision'])
    item.refresh_from_db(fields=['result_revision'])


def process_run(run_id, *, expected_task_id, check_stop=lambda: False, progress=lambda current, total: None):
    with transaction.atomic():
        run = RescreenRun.objects.select_for_update().get(pk=run_id, task_id=expected_task_id)
        if run.status != 'pending':
            return run
        run.status = 'running'
        run.save(update_fields=['status'])
    task = run.task
    stopped, fatal = False, ''
    try:
        # Iterator keeps the DB corpus out of worker memory; model calls are
        # serial and lease exactly one shared global/user slot.
        for item in run.items.exclude(status='completed').select_related('reference', 'asset').iterator(chunk_size=25):
            if _stop(run, task, check_stop):
                stopped = True
                break
            item.status = 'running'
            item.save(update_fields=['status'])
            for result in item.model_results.exclude(status='completed').order_by('pk'):
                if _stop(run, task, check_stop):
                    stopped = True
                    break
                result.item = item
                try:
                    if not _evaluate(result, run, task, check_stop):
                        stopped = True
                        break
                except RescreenError as exc:
                    result.status, result.error_code, result.error_message = 'failed', exc.code, str(exc)[:500]
                    result.save(update_fields=['status', 'error_code', 'error_message', 'updated_at'])
                    if exc.code in ('insufficient_credits', 'input_changed', 'rate_not_matched'):
                        stopped, fatal = True, exc.code
                        break
            if not RescreenRun.objects.filter(pk=run.pk, task=task).exists():
                stopped = True
                break
            _item_state(item)
            processed = run.items.exclude(status__in=('pending', 'running')).count()
            RescreenRun.objects.filter(pk=run.pk, task=task).update(processed_count=processed)
            progress(processed, run.total_count)
            if stopped:
                break
    except Exception:
        fatal = 'execution_failed'
        logger.exception('全文复筛运行异常 run=%s task=%s', run.pk, task.pk)
        raise
    finally:
        # A concurrent stop request waits here until the current provider call
        # has returned and its real usage is accounted for.
        run.refresh_from_db()
        try:
            billing.settle_task(task)
        except Exception:
            RescreenRun.objects.filter(pk=run.pk, task=task).update(status='settlement_pending', error_code='settlement_failed')
            raise
        counts = {row['status']: row['count'] for row in run.items.values('status').annotate(count=Count('pk'))}
        successful = counts.get('completed', 0)
        state = ('paused' if stopped or run.status == 'cancelling' else 'failed' if fatal else
                 'completed' if successful == run.total_count else 'partial' if successful or counts.get('partial') else 'failed')
        RescreenRun.objects.filter(pk=run.pk, task=task).update(status=state, error_code=fatal,
            processed_count=sum(value for key, value in counts.items() if key not in ('pending', 'running')),
            finished_at=timezone.now())
        run.refresh_from_db()
    return run
