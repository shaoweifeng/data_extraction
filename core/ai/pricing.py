"""Versioned, model-aware shadow pricing for AI usage."""

from __future__ import annotations

from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from core.services.ai_models_config import MODEL_ID_ALIASES


PRICING_VERSION = 'ai-credit-v1'
# Public list prices normalized to CNY per million tokens for the first shadow run.
MODEL_RATES_CNY_PER_MILLION = {
    'qwen3-7-flash': {'prompt': Decimal('0.20'), 'completion': Decimal('0.80')},
    'qwen3-7-plus': {'prompt': Decimal('2.00'), 'completion': Decimal('8.00')},
    'deepseek-v4-flash': {'prompt': Decimal('2.16'), 'completion': Decimal('8.64')},
    'doubao-seed-2-1-turbo': {'prompt': Decimal('3.00'), 'completion': Decimal('15.00')},
    'deepseek-v4-pro': {'prompt': Decimal('9.504'), 'completion': Decimal('28.512')},
    'qwen3-7-max': {'prompt': Decimal('12.00'), 'completion': Decimal('36.00')},
}
BASE_CNY_PER_CREDIT = Decimal('0.00216')


def calculate_shadow_pricing(model_usage: dict | None) -> dict:
    """Calculate a deterministic cost estimate without changing the charged credits."""
    breakdown = {}
    total_cost = Decimal('0')
    raw_credits = Decimal('0')
    unknown_models = []

    for supplied_model_id, usage in sorted((model_usage or {}).items()):
        model_id = MODEL_ID_ALIASES.get(supplied_model_id, supplied_model_id)
        rates = MODEL_RATES_CNY_PER_MILLION.get(model_id)
        if not rates:
            unknown_models.append(supplied_model_id)
            continue
        prompt_tokens = max(0, int(usage.get('prompt_tokens', usage.get('prompt', 0)) or 0))
        completion_tokens = max(
            0, int(usage.get('completion_tokens', usage.get('completion', 0)) or 0)
        )
        cached_prompt_tokens = min(
            prompt_tokens, max(0, int(usage.get('cached_prompt_tokens', 0) or 0))
        )
        ordinary_prompt_tokens = prompt_tokens - cached_prompt_tokens
        # v1 records cache use but prices it conservatively as normal input until each
        # enabled provider/model has a verified cache-read price.
        cached_rate = rates.get('cached_prompt', rates['prompt'])
        prompt_cost = (
            Decimal(ordinary_prompt_tokens) * rates['prompt']
            + Decimal(cached_prompt_tokens) * cached_rate
        ) / Decimal(1_000_000)
        completion_cost = (
            Decimal(completion_tokens) * rates['completion'] / Decimal(1_000_000)
        )
        cost = prompt_cost + completion_cost
        credits = cost / BASE_CNY_PER_CREDIT
        total_cost += cost
        raw_credits += credits
        breakdown[supplied_model_id] = {
            'prompt_tokens': prompt_tokens,
            'completion_tokens': completion_tokens,
            'cached_prompt_tokens': cached_prompt_tokens,
            'total_tokens': prompt_tokens + completion_tokens,
            'calls': max(0, int(usage.get('calls', 0) or 0)),
            'prompt_rate_cny_per_million': str(rates['prompt']),
            'completion_rate_cny_per_million': str(rates['completion']),
            'cached_prompt_rate_cny_per_million': str(cached_rate),
            'estimated_cost_cny': str(cost.quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP)),
            'raw_credits': str(credits.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)),
        }

    shadow_credits = int(raw_credits.quantize(Decimal('1'), rounding=ROUND_CEILING)) if breakdown else None
    return {
        'pricing_version': PRICING_VERSION,
        'model_usage': breakdown,
        'estimated_cost_cny': (
            total_cost.quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP)
            if breakdown else None
        ),
        'shadow_credits': shadow_credits,
        'unknown_models': unknown_models,
    }
