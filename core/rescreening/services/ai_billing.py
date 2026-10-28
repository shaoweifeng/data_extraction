"""Actual evidence-package estimates and shared-ledger settlement for SCREEN_2."""
from dataclasses import asdict
from decimal import Decimal
from django.conf import settings
from core.ai import AIUsageContext, AIUsageSettlementService, TokenUsageAccumulator, is_unlimited_ai_user
from core.ai.features import AI_TASK_FEATURES
from core.ai.billing_calculator import RateSnapshot, calculate_task_pricing, flatten_model_usage
from core.models_billing import CreditReservation, ModelBillingRate
from core.rescreening.errors import RescreenError
from core.services.ai_models_config import get_model_config


def freeze_rates(version):
    statuses = ['published'] + (['draft'] if settings.MODEL_WEIGHTED_BILLING_ALLOW_DRAFT else [])
    rates = ModelBillingRate.objects.filter(version=version, status__in=statuses)
    snapshot = [{key: str(value) if isinstance(value, Decimal) else value
                 for key, value in asdict(RateSnapshot.from_model(rate)).items()} for rate in rates]
    if not snapshot:
        raise RescreenError('rates_unavailable', '复筛计费费率不可用。', status=503)
    return snapshot


def price_calls(calls, snapshot, version):
    rates = [RateSnapshot(**{key: Decimal(value) if key.endswith('_per_million') else value
                            for key, value in row.items()}) for row in snapshot]
    priced = calculate_task_pricing(calls, rates, pricing_version=version)
    if priced['task_credits'] is None:
        raise RescreenError('rate_not_matched', '模型或上下文区间未匹配到冻结费率。', status=503)
    return priced


def estimated_call(model_id, input_tokens, output_tokens):
    config = get_model_config(model_id)
    return {'model_id': config['id'], 'provider': config['provider'], 'provider_model': '',
            'region': config.get('region', ''), 'service_tier': config.get('service_tier', 'standard'),
            'input_tokens': input_tokens, 'context_tokens': input_tokens, 'output_tokens': output_tokens,
            'charge_bearer': 'user'}


def reserve(task, estimate):
    if is_unlimited_ai_user(task.created_by):
        return
    if not (settings.MODEL_WEIGHTED_BILLING_ENABLED and settings.CREDIT_BATCH_LEDGER_ENABLED
            and settings.BILLING_RESERVATION_ENABLED):
        raise RescreenError('billing_not_ready', '复筛需要开启新版模型计费、批次账本和积分预占。', status=503)
    from core.services.credit_ledger_service import reserve_credits, reservation_key_for_task, CreditLedgerError
    try:
        reserve_credits(task.created_by, max(1, estimate), task=task,
            idempotency_key=reservation_key_for_task(task), pricing_version=task.config['billing_pricing_version'])
    except CreditLedgerError as exc:
        raise RescreenError('insufficient_credits', '可用积分不足，无法预占本次复筛额度。', status=402) from exc


def task_usage(task):
    from core.rescreening.models import RescreenCall
    total = TokenUsageAccumulator()
    for call in RescreenCall.objects.filter(task=task).select_related('result').iterator(chunk_size=100):
        if call.usage:
            total.add(call.usage, call.result.model_id)
    stats = total.as_dict()
    stats['ref_count'] = RescreenCall.objects.filter(task=task).values('result__item_id').distinct().count()
    return stats


def before_call(task, run, next_call):
    """Reprice incurred calls + next upper bound, extending a hold before sending."""
    if is_unlimited_ai_user(task.created_by):
        return
    from core.services.credit_ledger_service import extend_reservation, CreditLedgerError
    usage = task_usage(task)
    target = price_calls(flatten_model_usage(usage.get('model_usage')) + [next_call],
                         run.config_snapshot['rates'], run.pricing_version)['task_credits']
    try:
        reservation = CreditReservation.objects.get(task=task, status='reserved')
        extend_reservation(reservation, max(1, target))
    except (CreditLedgerError, CreditReservation.DoesNotExist) as exc:
        raise RescreenError('insufficient_credits', '积分预占不足，已暂停未执行部分。', status=402) from exc


def settle_task(task):
    """Repeatable recovery boundary: settle journaled usage before releasing a hold."""
    from core.services.credit_ledger_service import release_task_reservation
    stats = task_usage(task)
    if stats['total_tokens']:
        from core.rescreening.models import RescreenRun
        run = RescreenRun.objects.get(pk=task.config['rescreen_run_id'])
        rates = [RateSnapshot(**{key: Decimal(value) if key.endswith('_per_million') else value
                                for key, value in row.items()}) for row in run.config_snapshot['rates']]
        AIUsageSettlementService.settle(AIUsageContext(feature=AI_TASK_FEATURES[task.task_type], user=task.created_by,
            project=task.project, task=task, model_ids=task.config.get('model_ids', []),
            idempotency_key=f'rescreen-settle:{task.pk}', pricing_version=run.pricing_version,
            rate_snapshots=rates), stats)
    else:
        release_task_reservation(task, reason='复筛未产生已知模型用量')
