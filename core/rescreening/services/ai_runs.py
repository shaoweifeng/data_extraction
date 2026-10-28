"""Version-bound AI run commands. No provider request is sent from an HTTP view."""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, F
from django.utils import timezone
from datetime import timedelta

from core.bibliography import bibliography_snapshot
from core.models import ActivityLog, Project, Task
from core.rescreening.errors import RescreenError
from core.rescreening.models import (RescreenCorpus, RescreenCriteriaRevision, RescreenRun,
    RescreenRunItem, RescreenModelResult, RescreenReference, RescreenReferenceRawMetadata, RescreenCall)
from core.rescreening.services import ai_protocol as protocol, ai_billing as billing
from core.rescreening.services.imports import _require_idle
from core.rescreening.services.source import digest
from core.services.access_policy import ProjectAccessPolicy
from core.services.ai_models_config import get_model_config
from core.workflow.services.task_launcher import create_step_task, dispatch_step_task

ACTIVE_RUN_STATUSES = ('pending', 'running', 'cancelling', 'settlement_pending')


def _permission(project, user):
    ProjectAccessPolicy.require_project(user, project.pk)
    from core.api.common import check_permission
    if not check_permission(user, 'task.start'):
        raise RescreenError('permission_denied', '没有启动 AI 任务的权限。', status=403)


def _rate(user):
    if Task.objects.filter(created_by=user, task_type='rescreen_ai',
            created_at__gte=timezone.now()-timedelta(minutes=1)).count() >= settings.RESCREEN_AI_RATE_PER_MINUTE:
        raise RescreenError('ai_rate_limited', '启动或重试过于频繁，请稍后再试。', status=429)
    if RescreenRun.objects.filter(task__created_by=user, status__in=ACTIVE_RUN_STATUSES).count() >= settings.RESCREEN_AI_MAX_ACTIVE_PER_USER:
        raise RescreenError('ai_active_limit', '当前账户的活动复筛任务过多。', status=429)


def _models(values):
    from core.ai.providers import provider_is_configured
    if not isinstance(values, list) or not 1 <= len(values) <= 6 or any(not isinstance(v, str) for v in values):
        raise RescreenError('invalid_models', '请选择 1～6 个模型。')
    result = []
    for value in values:
        config = get_model_config(value)
        if not config or not provider_is_configured(value):
            raise RescreenError('model_not_configured', '所选模型不存在或尚未配置凭据。', status=503)
        if config['id'] not in result:
            result.append(config['id'])
    return result


def _ids(values, maximum):
    if (not isinstance(values, list) or not 1 <= len(values) <= maximum
            or any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in values)):
        raise RescreenError('invalid_references', f'请选择 1～{maximum} 篇文献，ID 必须为正整数。')
    return sorted(set(values))


def prepare(project, ids, criteria, models, *, limits=None, version=None, rates=None):
    from core.rescreening.services.workspace import prompt_configuration
    template, settings_version = prompt_configuration(project)
    limits = limits or protocol.limits_snapshot()
    ids = _ids(ids, limits['max_references'])
    criteria = protocol.normalize_criteria(criteria, limits)
    models = _models(models)
    corpus = RescreenCorpus.objects.get(project=project)
    refs = list(RescreenReference.objects.active().filter(project=project, pk__in=ids)
                .select_related('current_binding__asset'))
    if len(refs) != len(ids):
        raise RescreenError('invalid_references', '文献不存在、不属于该项目或已移除。', status=409)
    version = version or settings.MODEL_WEIGHTED_BILLING_PRICING_VERSION
    rates = rates or billing.freeze_rates(version)
    rows, calls = [], []
    for ref in refs:
        if not ref.current_binding_id or ref.current_binding.input_version != ref.input_version:
            raise RescreenError('fulltext_missing', '选中的文献尚未绑定当前版本全文。', status=409)
        asset = ref.current_binding.asset
        if asset.project_id != project.pk:
            raise RescreenError('asset_project_mismatch', '全文资产不属于该项目。', status=409)
        bibliography = bibliography_snapshot(ref)
        package = protocol.build_batches(asset, bibliography, criteria, models, limits, template=template)
        for _, _, prompt in protocol.requests_for(package, bibliography, criteria, template=template):
            for model in models:
                calls.append(billing.estimated_call(model, protocol.call_budget(prompt, model, limits), limits['output_tokens']))
        rows.append((ref, asset, bibliography, package))
    priced = billing.price_calls(calls, rates, version)
    return {'corpus': corpus, 'criteria': criteria, 'models': models, 'rows': rows,
            'rates': rates, 'pricing_version': version, 'limits': limits,
            'template': template, 'settings_version': settings_version,
            'estimate': {'feature': 'ai_rescreen', 'ref_count': len(rows), 'call_count': len(calls),
                         'reserve_credits': max(1, priced['task_credits']), 'pricing_version': version}}


def _dispatch(run_id, task_id):
    try:
        dispatch_step_task(Task.objects.get(pk=task_id), 'rescreen_ai')
    except Exception:
        task = Task.objects.get(pk=task_id)
        finish_task(task)


def _new_task(run, user, estimate, *, maintenance=False):
    from core.step_config import get_step_config
    task = create_step_task(run.corpus.project_id, 'rescreen_ai', user.pk, {
        **get_step_config('rescreen_ai'), 'rescreen_run_id': run.pk, 'model_ids': run.model_ids,
        'billing_pricing_version': run.pricing_version, 'credits_estimate': estimate,
    }, allow_during_maintenance=maintenance)
    billing.reserve(task, estimate)
    run.task = task
    run.status, run.error_code, run.finished_at = 'pending', '', None
    run.save(update_fields=['task', 'status', 'error_code', 'finished_at'])
    transaction.on_commit(lambda: _dispatch(run.pk, task.pk))
    return task


def start_run(*, project, user, ids, criteria, model_ids, expected_revision, idempotency_key, expected_settings_version=None):
    _permission(project, user)
    limits = protocol.limits_snapshot()
    ids = _ids(ids, limits['max_references'])
    fingerprint = digest({'ids': ids, 'criteria': criteria, 'models': model_ids, 'revision': expected_revision})
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=project.owner_id)
        project = Project.objects.select_for_update().get(pk=project.pk)
        corpus = RescreenCorpus.objects.get(project=project)
        from core.rescreening.services.workspace import prompt_configuration
        _, settings_version = prompt_configuration(project)
        if expected_settings_version is not None and expected_settings_version != settings_version:
            raise RescreenError('settings_conflict', '设置已变化，请刷新后重新预估。', status=409)
        old = RescreenRun.objects.filter(corpus=corpus, idempotency_key=idempotency_key).first()
        if old:
            if old.request_hash != fingerprint:
                raise RescreenError('idempotency_conflict', '相同幂等键不能用于不同复筛输入。', status=409)
            return old
        _require_idle(project)
        _rate(user)
        if corpus.revision != expected_revision:
            raise RescreenError('input_changed', '复筛输入已变化，请刷新后重试。', status=409)
        prepared = prepare(project, ids, criteria, model_ids, limits=limits)
        last = corpus.criteria_versions.order_by('-revision').first()
        revision = last if last and last.criteria == prepared['criteria'] else RescreenCriteriaRevision.objects.create(
            corpus=corpus, revision=(last.revision+1 if last else 1), criteria=prepared['criteria'], created_by=user)
        run = RescreenRun.objects.create(corpus=corpus, input_revision=corpus.revision, criteria_revision=revision,
            model_ids=prepared['models'], config_snapshot={'limits': limits, 'rates': prepared['rates'],
                'model_configs': {model: {key: get_model_config(model).get(key) for key in (
                    'id', 'model', 'provider', 'region', 'service_tier', 'is_reasoning', 'timeout')}
                    for model in prepared['models']},
                'protocol': protocol.PROTOCOL_VERSION, 'prompt_template': prepared['template'],
                'settings_version': prepared['settings_version']}, pricing_version=prepared['pricing_version'],
            prompt_version=protocol.PROTOCOL_VERSION, total_count=len(prepared['rows']),
            idempotency_key=idempotency_key, request_hash=fingerprint)
        for ref, asset, bibliography, package in prepared['rows']:
            raw = RescreenReferenceRawMetadata.objects.get(reference=ref, input_version=ref.input_version)
            item = RescreenRunItem.objects.create(run=run, reference=ref, input_version=ref.input_version,
                raw_metadata_version=raw, asset=asset, asset_sha256=asset.sha256,
                bibliography_snapshot=bibliography, evidence_package=package)
            RescreenModelResult.objects.bulk_create([RescreenModelResult(item=item, model_id=model)
                                                     for model in run.model_ids])
        _new_task(run, user, prepared['estimate']['reserve_credits'])
        corpus.current_run = run
        corpus.save(update_fields=['current_run', 'updated_at'])
        ActivityLog.objects.create(project=project, operation_type='rescreen_ai_started',
            operation_detail={'run_id': run.pk, 'count': run.total_count, 'models': run.model_ids}, created_by=user)
        return run


def retry_run(*, run_id, user, acknowledge_unknown=False, maintenance=False):
    run = RescreenRun.objects.select_related('corpus__project', 'task').get(pk=run_id)
    _permission(run.corpus.project, user)
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=run.corpus.project.owner_id)
        Project.objects.select_for_update().get(pk=run.corpus.project_id)
        # Lock only the run here. Locking joined historical Task rows would
        # invert the ledger's account -> Task settlement order on MySQL.
        run = RescreenRun.objects.select_for_update().get(pk=run_id)
        if run.status not in ('paused', 'failed', 'partial', 'cancelled'):
            raise RescreenError('not_retryable', '请等待运行和计费结束后重试。', status=409)
        _require_idle(run.corpus.project)
        _rate(user)
        if run.input_revision != run.corpus.revision or run.criteria_revision_id != run.corpus.criteria_versions.latest('revision').pk:
            raise RescreenError('input_changed', '输入或标准已变化，请创建新运行。', status=409)
        if run.prompt_version != protocol.PROTOCOL_VERSION:
            raise RescreenError('protocol_changed', '复筛协议已更新，请创建新运行。', status=409)
        from core.rescreening.services.workspace import prompt_configuration
        if run.config_snapshot.get('settings_version', 0) != prompt_configuration(run.corpus.project)[1]:
            raise RescreenError('settings_conflict', '复筛设置已变化，请创建新运行。', status=409)
        if run.items.exclude(reference__input_version=F('input_version')).exists():
            raise RescreenError('input_changed', '文献版本已变化，请创建新运行。', status=409)
        unknown = RescreenCall.objects.filter(result__item__run=run, status__in=('calling', 'unknown'))
        if unknown.exists() and not acknowledge_unknown:
            raise RescreenError('unknown_call_requires_ack', '存在结果或用量未知的历史请求，重试可能再次产生费用，请显式确认。', status=409)
        candidates = RescreenModelResult.objects.filter(item__run=run).exclude(status='completed')
        if not candidates.exists():
            raise RescreenError('nothing_to_retry', '没有未完成的模型结果。', status=409)
        calls = []
        for result in candidates.select_related('item'):
            if result.calls.count() >= run.config_snapshot['limits']['max_calls']:
                raise RescreenError('call_limit', '已达到单文献单模型调用上限，请检查后创建新运行。', status=409)
            completed = {tuple(call.criterion_ids) for call in result.calls.filter(status='completed')}
            for package, _, prompt in protocol.requests_for(result.item.evidence_package, result.item.bibliography_snapshot,
                    run.criteria_revision.criteria, template=run.config_snapshot['prompt_template']):
                if tuple(package['criterion_ids']) in completed:
                    continue
                calls.append(billing.estimated_call(result.model_id, protocol.call_budget(prompt, result.model_id,
                    run.config_snapshot['limits']), run.config_snapshot['limits']['output_tokens']))
        estimate = billing.price_calls(calls, run.config_snapshot['rates'], run.pricing_version)['task_credits']
        # Known previous usage must already be settled before creating another hold.
        if run.task_id:
            billing.settle_task(run.task)
        if acknowledge_unknown:
            unknown.update(status='acknowledged_unknown')
        candidates.update(status='pending', error_code='', error_message='')
        run.items.exclude(status='completed').update(status='pending', error_code='')
        _new_task(run, user, max(1, estimate), maintenance=maintenance)
        return run


def finish_task(task, *, cancelled=False, requested=False):
    """Do not release journaled usage on stop/crash; finish billing first."""
    if task.task_type != 'rescreen_ai':
        return
    failure = None
    with transaction.atomic():
        run = RescreenRun.objects.select_for_update().filter(task=task).first()
        if not run or run.status in ('completed', 'partial', 'paused', 'failed', 'cancelled'):
            return
        if requested and run.status in ('running', 'cancelling'):
            run.status = 'cancelling'
            run.save(update_fields=['status'])
            return
        RescreenCall.objects.filter(task=task, status='calling').update(status='unknown', error_code='worker_interrupted')
        # On a hard interruption, only persisted usage is recoverable. Unknown
        # calls remain explicit and require user acknowledgement on retry.
        try:
            billing.settle_task(task)
        except Exception as exc:
            run.status, run.error_code = 'settlement_pending', 'settlement_failed'
            run.save(update_fields=['status', 'error_code'])
            failure = exc
        else:
            completed = run.items.filter(status='completed').count()
            some_success = run.items.filter(model_results__status='completed').exists()
            run.status = ('paused' if cancelled else 'completed' if completed == run.total_count
                          else 'partial' if some_success else 'failed')
            run.error_code = 'cancelled' if cancelled else 'task_failed'
            run.finished_at = timezone.now()
            run.save(update_fields=['status', 'error_code', 'finished_at'])
    # Raise only after committing the recovery marker, not from inside the
    # surrounding transaction (which would silently roll the marker back).
    if failure:
        raise failure


def run_stats(run):
    return {row['status']: row['count'] for row in run.items.values('status').annotate(count=Count('pk'))}
