"""Pure, versioned model-cost and credit calculation.

No balance is changed here.  A caller supplies immutable rate snapshots and
normalized call details, making historical tasks replayable without consulting
today's provider prices.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from typing import Iterable, Mapping, Sequence

from core.ai.usage_schema import canonical_model_id, normalize_call_detail


BASE_CNY_PER_CREDIT = Decimal('0.00216')
MILLION = Decimal('1000000')


def _decimal(value) -> Decimal:
    return Decimal(str(value or 0))


@dataclass(frozen=True)
class RateSnapshot:
    rate_key: str
    version: str
    provider: str
    region: str
    service_tier: str
    model_id: str
    provider_model: str
    context_min_tokens: int
    context_max_tokens: int
    input_cny_per_million: Decimal
    output_cny_per_million: Decimal
    cache_read_cny_per_million: Decimal
    cache_write_cny_per_million: Decimal

    @classmethod
    def from_model(cls, rate) -> 'RateSnapshot':
        return cls(
            rate_key=rate.rate_key,
            version=rate.version,
            provider=rate.provider,
            region=rate.region,
            service_tier=rate.service_tier,
            model_id=canonical_model_id(rate.model_id),
            provider_model=rate.provider_model,
            context_min_tokens=rate.context_min_tokens,
            context_max_tokens=rate.context_max_tokens,
            input_cny_per_million=rate.input_cny_per_million,
            output_cny_per_million=rate.output_cny_per_million,
            cache_read_cny_per_million=rate.cache_read_cny_per_million,
            cache_write_cny_per_million=rate.cache_write_cny_per_million,
        )


def select_rate(detail: Mapping, rates: Sequence[RateSnapshot]) -> RateSnapshot | None:
    """Select exactly one model/context tier from one already-frozen version."""
    model_id = canonical_model_id(detail.get('model_id'))
    context_tokens = max(0, int(detail.get('context_tokens') or detail.get('input_tokens') or 0))
    candidates = []
    for rate in rates:
        if canonical_model_id(rate.model_id) != model_id:
            continue
        if detail.get('provider') and rate.provider != detail['provider']:
            continue
        if detail.get('region') and rate.region and rate.region != detail['region']:
            continue
        if detail.get('service_tier') and rate.service_tier != detail['service_tier']:
            continue
        if detail.get('provider_model') and rate.provider_model != detail['provider_model']:
            continue
        if context_tokens < rate.context_min_tokens:
            continue
        if rate.context_max_tokens and context_tokens > rate.context_max_tokens:
            continue
        candidates.append(rate)
    if len(candidates) != 1:
        return None
    return candidates[0]


def calculate_task_pricing(
    call_details: Iterable[Mapping],
    rates: Sequence[RateSnapshot],
    *,
    pricing_version: str,
) -> dict:
    """Price all calls, then round chargeable credits once at task level."""
    rates = tuple(rate for rate in rates if rate.version == pricing_version)
    total_cost = Decimal('0')
    chargeable_raw_credits = Decimal('0')
    priced_calls = []
    unknown_calls = []

    for index, supplied in enumerate(call_details, start=1):
        detail = normalize_call_detail(supplied)
        rate = select_rate(detail, rates)
        if rate is None:
            unknown_calls.append({
                'call_index': index,
                'provider': detail['provider'],
                'model_id': detail['model_id'],
                'provider_model': detail['provider_model'],
                'context_tokens': detail['context_tokens'],
            })
            continue

        input_tokens = detail['input_tokens']
        cache_read_tokens = min(input_tokens, detail['cache_read_tokens'])
        cache_write_tokens = min(
            input_tokens - cache_read_tokens, detail['cache_write_tokens'],
        )
        ordinary_input_tokens = input_tokens - cache_read_tokens - cache_write_tokens
        cost = (
            _decimal(ordinary_input_tokens) * rate.input_cny_per_million
            + _decimal(cache_read_tokens) * rate.cache_read_cny_per_million
            + _decimal(cache_write_tokens) * rate.cache_write_cny_per_million
            + _decimal(detail['output_tokens']) * rate.output_cny_per_million
        ) / MILLION
        raw_credits = cost / BASE_CNY_PER_CREDIT
        total_cost += cost
        if detail['charge_bearer'] == 'user':
            chargeable_raw_credits += raw_credits
        priced_calls.append({
            **detail,
            'call_index': index,
            'rate_key': rate.rate_key,
            'ordinary_input_tokens': ordinary_input_tokens,
            'estimated_cost_cny': cost.quantize(Decimal('0.00000001'), rounding=ROUND_HALF_UP),
            'raw_credits': raw_credits.quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP),
        })

    if unknown_calls:
        task_credits = None
    elif chargeable_raw_credits > 0:
        task_credits = int(chargeable_raw_credits.to_integral_value(rounding=ROUND_CEILING))
    else:
        task_credits = 0

    return {
        'pricing_version': pricing_version,
        'base_cny_per_credit': BASE_CNY_PER_CREDIT,
        'estimated_cost_cny': total_cost.quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP),
        'raw_chargeable_credits': chargeable_raw_credits.quantize(
            Decimal('0.000001'), rounding=ROUND_HALF_UP,
        ),
        'task_credits': task_credits,
        'priced_calls': priced_calls,
        'unknown_calls': unknown_calls,
    }


def flatten_model_usage(model_usage: Mapping | None) -> list[dict]:
    """Expand current task-level model usage into normalized call details."""
    details = []
    for supplied_model_id, stats in (model_usage or {}).items():
        call_details = stats.get('call_details') or []
        if call_details:
            details.extend(
                normalize_call_detail(item, fallback_model_id=supplied_model_id)
                for item in call_details
                if isinstance(item, Mapping)
            )
            continue
        # Historical logs only contain one aggregate per model.  They remain
        # replayable as one synthetic line, explicitly without request metadata.
        details.append(normalize_call_detail(stats, fallback_model_id=supplied_model_id))
    return details
