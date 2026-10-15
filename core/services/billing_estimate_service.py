"""Model-aware credit estimates built from the immutable billing-rate table."""

from __future__ import annotations

from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from django.conf import settings

from core.ai.billing_calculator import RateSnapshot, calculate_task_pricing
from core.services.ai_models_config import get_model_config


FEATURE_BASELINES = {
    # Current screening benchmark: about 3,700 input and 60 output tokens/call.
    'ai_screen': {
        'calls_per_reference': 1,
        'input_tokens_per_call': 3700,
        'output_tokens_per_call': 60,
        'reserve_factor': Decimal('1.30'),
    },
    # QA V2 usually evaluates four domains separately.  The 25% reserve factor
    # reproduces the measured DeepSeek P75 of roughly 27 credits/model/article.
    'qa_eval': {
        'calls_per_reference': 4,
        'input_tokens_per_call': 5000,
        'output_tokens_per_call': 100,
        'reserve_factor': Decimal('1.25'),
    },
}

DISPLAY_MULTIPLIER_BASE_MODEL_ID = 'deepseek-v4-flash'


class BillingEstimateError(ValueError):
    pass


def _display_multiplier(value: Decimal) -> str:
    """Round public relative prices to 0.25×, with a readable 0.25× floor."""
    step = Decimal('0.25')
    rounded = (value / step).quantize(Decimal('1'), rounding=ROUND_HALF_UP) * step
    rounded = max(step, rounded)
    if rounded == rounded.to_integral_value():
        return f'{rounded:.1f}'
    if (rounded * 2) == (rounded * 2).to_integral_value():
        return f'{rounded:.1f}'
    return f'{rounded:.2f}'


def _rate_snapshots(pricing_version: str):
    from core.models_billing import ModelBillingRate

    statuses = ['published']
    if getattr(settings, 'MODEL_WEIGHTED_BILLING_ALLOW_DRAFT', False):
        statuses.append('draft')
    return [
        RateSnapshot.from_model(rate)
        for rate in ModelBillingRate.objects.filter(
            version=pricing_version,
            status__in=statuses,
        ).order_by('model_id', 'context_min_tokens')
    ]


def estimate_model_credits(
    ref_count: int,
    model_ids: list[str],
    *,
    feature: str = 'ai_screen',
    pricing_version: str | None = None,
) -> dict:
    """Return a model-level estimate and the conservative amount to reserve."""
    if feature not in FEATURE_BASELINES:
        raise BillingEstimateError(f'不支持的计费功能：{feature}')
    if ref_count <= 0:
        raise BillingEstimateError('文献数量必须大于 0')
    model_ids = list(dict.fromkeys(model_ids or []))
    if not model_ids:
        raise BillingEstimateError('至少选择一个模型')

    pricing_version = pricing_version or settings.MODEL_WEIGHTED_BILLING_PRICING_VERSION
    rates = _rate_snapshots(pricing_version)
    if not rates:
        raise BillingEstimateError(f'费率版本不可用：{pricing_version}')

    baseline = FEATURE_BASELINES[feature]
    def price_unit(model_id: str):
        config = get_model_config(model_id)
        if not config:
            raise BillingEstimateError(f'未知模型：{model_id}')
        calls = [{
            'provider': config['provider'],
            'region': config.get('region', ''),
            'service_tier': config.get('service_tier', 'standard'),
            'model_id': config['id'],
            # Do not constrain provider_model during preflight.  Some providers
            # return an alias while the platform ID and rate row are canonical.
            'provider_model': '',
            'context_tokens': baseline['input_tokens_per_call'],
            'input_tokens': baseline['input_tokens_per_call'],
            'output_tokens': baseline['output_tokens_per_call'],
            'cache_read_tokens': 0,
            'cache_write_tokens': 0,
            'charge_bearer': 'user',
        } for _ in range(baseline['calls_per_reference'])]
        priced = calculate_task_pricing(calls, rates, pricing_version=pricing_version)
        if priced['task_credits'] is None or priced['unknown_calls']:
            raise BillingEstimateError(f'模型 {model_id} 未匹配到可用费率')
        return config, priced['raw_chargeable_credits']

    unit_rows = [price_unit(model_id) for model_id in model_ids]
    _, display_base_raw = price_unit(DISPLAY_MULTIPLIER_BASE_MODEL_ID)

    base_raw = sum((raw for _, raw in unit_rows), Decimal('0')) * ref_count
    reserve_raw = base_raw * baseline['reserve_factor']
    base_credits = int(base_raw.to_integral_value(rounding=ROUND_CEILING))
    reserve_credits = int(reserve_raw.to_integral_value(rounding=ROUND_CEILING))
    breakdown = []
    for config, unit_raw in unit_rows:
        model_base = unit_raw * ref_count
        model_reserve = model_base * baseline['reserve_factor']
        multiplier = unit_raw / display_base_raw if display_base_raw else Decimal('1')
        breakdown.append({
            'model_id': config['id'],
            'model_name': config['name'],
            'unit_credits': str(unit_raw.quantize(Decimal('0.001'))),
            'multiplier': _display_multiplier(multiplier),
            'base_credits': int(model_base.to_integral_value(rounding=ROUND_CEILING)),
            'reserve_credits': int(model_reserve.to_integral_value(rounding=ROUND_CEILING)),
        })
    return {
        'feature': feature,
        'ref_count': ref_count,
        'pricing_version': pricing_version,
        'base_credits': base_credits,
        'reserve_credits': max(1, reserve_credits),
        'reserve_factor': str(baseline['reserve_factor']),
        'models': breakdown,
    }
