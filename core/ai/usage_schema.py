"""Provider-neutral AI usage normalization.

The public dictionary keeps the legacy prompt/completion/total keys so existing
screening and quality consumers remain compatible.  Billing code should use the
explicit input/output/cache fields and the immutable call detail instead.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from core.services.ai_models_config import MODEL_ID_ALIASES


USAGE_SCHEMA_VERSION = 'ai-usage-v2'

# Some OpenAI-compatible providers return a public/served model name that is
# different from the model name used in our request configuration.  Billing
# rates are keyed by the observed provider value, so normalize the known aliases
# at ingestion and replay time instead of maintaining duplicate rate rows.
PROVIDER_MODEL_ALIASES = {
    'deepseek-v4-flash': 'deepseek-flash',
}

# OpenAI-compatible APIs may describe the ordinary on-demand tier as either
# ``default`` (provider response) or ``standard`` (our configured/rate-table
# value).  They represent the same non-priority tier for the currently enabled
# providers, so canonicalize both live ingestion and historical replay.
SERVICE_TIER_ALIASES = {
    'default': 'standard',
}


def _non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def canonical_model_id(model_id: str | None) -> str:
    value = str(model_id or '').strip()
    return MODEL_ID_ALIASES.get(value, value)


def canonical_provider_model(provider_model: str | None) -> str:
    value = str(provider_model or '').strip()
    return PROVIDER_MODEL_ALIASES.get(value, value)


def canonical_service_tier(service_tier: str | None) -> str:
    value = str(service_tier or 'standard').strip().casefold()
    return SERVICE_TIER_ALIASES.get(value, value)


def normalize_provider_usage(
    raw_usage: Mapping[str, Any] | None,
    *,
    provider: str,
    model_id: str,
    provider_model: str,
    region: str = '',
    service_tier: str = 'standard',
    provider_request_id: str = '',
    attempt_number: int = 1,
    attempt_reason: str = 'initial',
    charge_bearer: str = 'user',
) -> dict | None:
    """Return one normalized, backward-compatible provider usage record."""
    if not raw_usage:
        return None

    prompt_details = raw_usage.get('prompt_tokens_details') or {}
    input_tokens = _non_negative_int(
        raw_usage.get('prompt_tokens', raw_usage.get('input_tokens', 0))
    )
    output_tokens = _non_negative_int(
        raw_usage.get('completion_tokens', raw_usage.get('output_tokens', 0))
    )
    total_tokens = _non_negative_int(raw_usage.get('total_tokens', 0))
    if not total_tokens:
        total_tokens = input_tokens + output_tokens

    cache_read_tokens = _non_negative_int(
        prompt_details.get('cached_tokens')
        or raw_usage.get('cache_read_input_tokens')
        or raw_usage.get('cached_tokens')
    )
    cache_write_tokens = _non_negative_int(
        raw_usage.get('cache_creation_input_tokens')
        or raw_usage.get('cache_write_input_tokens')
        or prompt_details.get('cache_write_tokens')
    )
    # Cached/write input is normally included in prompt/input tokens.  Clamp the
    # two categories so malformed provider payloads cannot produce negatives.
    cache_read_tokens = min(input_tokens, cache_read_tokens)
    cache_write_tokens = min(input_tokens - cache_read_tokens, cache_write_tokens)

    canonical_id = canonical_model_id(model_id)
    detail = {
        'schema_version': USAGE_SCHEMA_VERSION,
        'provider': str(provider or ''),
        'region': str(region or ''),
        'service_tier': canonical_service_tier(service_tier),
        'model_id': canonical_id,
        'provider_model': canonical_provider_model(provider_model),
        'provider_request_id': str(provider_request_id or ''),
        'context_tokens': input_tokens,
        'input_tokens': input_tokens,
        'output_tokens': output_tokens,
        'cache_read_tokens': cache_read_tokens,
        'cache_write_tokens': cache_write_tokens,
        'attempt_number': max(1, _non_negative_int(attempt_number)),
        'attempt_reason': str(attempt_reason or 'initial'),
        'charge_bearer': 'platform' if charge_bearer == 'platform' else 'user',
    }

    return {
        # Legacy keys used throughout the current execution pipeline.
        'prompt': input_tokens,
        'completion': output_tokens,
        'total': total_tokens,
        'cached_prompt_tokens': cache_read_tokens,
        'cache_write_prompt_tokens': cache_write_tokens,
        # Explicit v2 keys and a per-call immutable record.
        'schema_version': USAGE_SCHEMA_VERSION,
        'provider': detail['provider'],
        'region': detail['region'],
        'service_tier': detail['service_tier'],
        'model_id': canonical_id,
        'provider_model': detail['provider_model'],
        'provider_request_id': detail['provider_request_id'],
        'context_tokens': input_tokens,
        'input_tokens': input_tokens,
        'output_tokens': output_tokens,
        'cache_read_tokens': cache_read_tokens,
        'cache_write_tokens': cache_write_tokens,
        'attempt_number': detail['attempt_number'],
        'attempt_reason': detail['attempt_reason'],
        'charge_bearer': detail['charge_bearer'],
        'calls': 1,
        'call_details': [detail],
        # Keep only the provider usage object, never response content/prompts.
        'raw_usage': deepcopy(dict(raw_usage)),
    }


def normalize_call_detail(detail: Mapping[str, Any], *, fallback_model_id: str = '') -> dict:
    """Normalize persisted/legacy call details before aggregation or storage."""
    input_tokens = _non_negative_int(
        detail.get('input_tokens', detail.get('prompt_tokens', detail.get('prompt', 0)))
    )
    output_tokens = _non_negative_int(
        detail.get('output_tokens', detail.get('completion_tokens', detail.get('completion', 0)))
    )
    cache_read = min(
        input_tokens,
        _non_negative_int(
            detail.get('cache_read_tokens', detail.get('cached_prompt_tokens', 0))
        ),
    )
    cache_write = min(
        input_tokens - cache_read,
        _non_negative_int(
            detail.get('cache_write_tokens', detail.get('cache_write_prompt_tokens', 0))
        ),
    )
    return {
        'schema_version': str(detail.get('schema_version') or USAGE_SCHEMA_VERSION),
        'provider': str(detail.get('provider') or ''),
        'region': str(detail.get('region') or ''),
        'service_tier': canonical_service_tier(detail.get('service_tier')),
        'model_id': canonical_model_id(detail.get('model_id') or fallback_model_id),
        'provider_model': canonical_provider_model(detail.get('provider_model')),
        'provider_request_id': str(detail.get('provider_request_id') or ''),
        'context_tokens': _non_negative_int(detail.get('context_tokens') or input_tokens),
        'input_tokens': input_tokens,
        'output_tokens': output_tokens,
        'cache_read_tokens': cache_read,
        'cache_write_tokens': cache_write,
        'attempt_number': max(1, _non_negative_int(detail.get('attempt_number') or 1)),
        'attempt_reason': str(detail.get('attempt_reason') or 'initial'),
        'charge_bearer': 'platform' if detail.get('charge_bearer') == 'platform' else 'user',
    }


def merge_call_usage(target: dict, usage: Mapping[str, Any] | None, model_id: str) -> None:
    """Merge one provider call without losing cache or request-level metadata."""
    if not usage:
        return
    prompt = _non_negative_int(usage.get('input_tokens', usage.get('prompt', 0)))
    completion = _non_negative_int(usage.get('output_tokens', usage.get('completion', 0)))
    total = _non_negative_int(usage.get('total', usage.get('total_tokens', 0)))
    total = total or prompt + completion
    target['prompt'] = _non_negative_int(target.get('prompt')) + prompt
    target['completion'] = _non_negative_int(target.get('completion')) + completion
    target['total'] = _non_negative_int(target.get('total')) + total

    canonical_id = canonical_model_id(usage.get('model_id') or model_id)
    model_usage = target.setdefault('model_usage', {}).setdefault(canonical_id, {
        'prompt_tokens': 0,
        'completion_tokens': 0,
        'total_tokens': 0,
        'cached_prompt_tokens': 0,
        'cache_write_prompt_tokens': 0,
        'calls': 0,
        'call_details': [],
    })
    model_usage['prompt_tokens'] += prompt
    model_usage['completion_tokens'] += completion
    model_usage['total_tokens'] += total
    model_usage['cached_prompt_tokens'] += min(
        prompt,
        _non_negative_int(usage.get('cache_read_tokens', usage.get('cached_prompt_tokens', 0))),
    )
    model_usage['cache_write_prompt_tokens'] += _non_negative_int(
        usage.get('cache_write_tokens', usage.get('cache_write_prompt_tokens', 0))
    )

    details = usage.get('call_details') or []
    if not details:
        details = [usage]
    for detail in details:
        if isinstance(detail, Mapping):
            model_usage['call_details'].append(
                normalize_call_detail(detail, fallback_model_id=canonical_id)
            )
    model_usage['calls'] += max(1, _non_negative_int(usage.get('calls') or len(details)))


def summarize_complete_call_details(model_usage: Mapping | None) -> dict | None:
    """Return authoritative totals only when every recorded call has a detail."""
    expected_calls = 0
    details = []
    for model_id, stats in (model_usage or {}).items():
        expected_calls += _non_negative_int(stats.get('calls'))
        for item in stats.get('call_details') or []:
            if isinstance(item, Mapping):
                details.append(normalize_call_detail(item, fallback_model_id=model_id))
    if not details or len(details) != expected_calls:
        return None
    return {
        'prompt_tokens': sum(item['input_tokens'] for item in details),
        'completion_tokens': sum(item['output_tokens'] for item in details),
        'total_tokens': sum(item['input_tokens'] + item['output_tokens'] for item in details),
        'cached_prompt_tokens': sum(item['cache_read_tokens'] for item in details),
        'cache_write_prompt_tokens': sum(item['cache_write_tokens'] for item in details),
        'calls': len(details),
    }
