"""Validation and normalization for quality-assessment method configurations."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Callable, Mapping


SUPPORTED_RESULT_TYPES = frozenset({'bias_risk', 'applicability'})


class MethodConfigError(ValueError):
    """Raised when a method configuration violates the shared contract."""


@dataclass(frozen=True)
class AggregationPolicy:
    key: str
    calculator: Callable[[str, list[str]], str]


def _quadas2_calculator(result_type: str, judgments: list[str]) -> str:
    if result_type == 'applicability':
        if '高' in judgments:
            return 'high'
        if '不清楚' in judgments:
            return 'unclear'
        return 'low'
    if '否' in judgments:
        return 'high'
    if '不清楚' in judgments:
        return 'unclear'
    return 'low'


def _nos_calculator(result_type: str, judgments: list[str]) -> str:
    del result_type
    if any(value.startswith('✗') for value in judgments):
        return 'high'
    if any(value == '不清楚' for value in judgments):
        return 'unclear'
    return 'low'


AGGREGATION_POLICIES: Mapping[str, AggregationPolicy] = {
    'quadas2_v1': AggregationPolicy('quadas2_v1', _quadas2_calculator),
    'nos_v1': AggregationPolicy('nos_v1', _nos_calculator),
}


def aggregate_judgments(policy_key: str, result_type: str, judgments: list[str]) -> str:
    try:
        policy = AGGREGATION_POLICIES[policy_key]
    except KeyError as exc:
        raise MethodConfigError(f'未知的聚合策略: {policy_key}') from exc
    return policy.calculator(result_type, judgments)


def _require_nonempty_text(config: dict, field: str, context: str) -> None:
    if not isinstance(config.get(field), str) or not config[field].strip():
        raise MethodConfigError(f'{context} 缺少非空字段 {field}')


def _validate_domains(domains: object, context: str) -> set[str]:
    if not isinstance(domains, list) or not domains:
        raise MethodConfigError(f'{context} domains 必须是非空列表')
    keys = []
    for index, domain in enumerate(domains):
        if not isinstance(domain, dict):
            raise MethodConfigError(f'{context} domains[{index}] 必须是对象')
        _require_nonempty_text(domain, 'key', f'{context} domains[{index}]')
        _require_nonempty_text(domain, 'name', f'{context} domains[{index}]')
        keys.append(domain['key'])
    if len(keys) != len(set(keys)):
        raise MethodConfigError(f'{context} 存在重复领域 key')
    return set(keys)


def _validate_signal_items(items: object, domain_keys: set[str], ai_supported: bool, context: str) -> None:
    if not isinstance(items, list):
        raise MethodConfigError(f'{context} signal_items 必须是列表')
    if ai_supported and not items:
        raise MethodConfigError(f'{context} 启用 AI 时 signal_items 不能为空')

    signal_keys = []
    for index, item in enumerate(items):
        item_context = f'{context} signal_items[{index}]'
        if not isinstance(item, dict):
            raise MethodConfigError(f'{item_context} 必须是对象')
        for field in ('domain', 'signal_key', 'signal_question', 'signal_description', 'result_type'):
            _require_nonempty_text(item, field, item_context)
        if item['domain'] not in domain_keys:
            raise MethodConfigError(f"{item_context} 引用了未知领域 {item['domain']}")
        if item['result_type'] not in SUPPORTED_RESULT_TYPES:
            raise MethodConfigError(f"{item_context} result_type 无效: {item['result_type']}")
        options = item.get('options')
        if not isinstance(options, list) or not options or any(not str(value).strip() for value in options):
            raise MethodConfigError(f'{item_context} options 必须是非空字符串列表')
        signal_keys.append(item['signal_key'])

        if ai_supported:
            retrieval = item.get('retrieval')
            if not isinstance(retrieval, dict):
                raise MethodConfigError(f'{item_context} 缺少 retrieval 配置')
            queries = retrieval.get('queries')
            sections = retrieval.get('preferred_sections')
            max_chunks = retrieval.get('max_chunks')
            if not isinstance(queries, list) or not queries or any(not str(q).strip() for q in queries):
                raise MethodConfigError(f'{item_context} retrieval.queries 必须是非空字符串列表')
            if not isinstance(sections, list) or not sections:
                raise MethodConfigError(f'{item_context} retrieval.preferred_sections 必须是非空列表')
            if not isinstance(max_chunks, int) or not 1 <= max_chunks <= 20:
                raise MethodConfigError(f'{item_context} retrieval.max_chunks 必须在 1～20 之间')
            if item.get('evidence_required') is not True:
                raise MethodConfigError(f'{item_context} 启用 AI 时 evidence_required 必须为 True')

    if len(signal_keys) != len(set(signal_keys)):
        raise MethodConfigError(f'{context} 存在重复信号问题 key')


def _validate_variant(config: dict, method: dict, context: str) -> None:
    domains = config.get('domains', method.get('domains'))
    items = config.get('signal_items', method.get('signal_items'))
    domain_keys = _validate_domains(domains, context)
    _validate_signal_items(items, domain_keys, bool(method['ai_supported']), context)


def validate_method_config(config: dict, *, registry_key: str | None = None) -> dict:
    """Return a defensive copy after validating the complete method contract."""
    if not isinstance(config, dict):
        raise MethodConfigError('方法配置必须是对象')
    method = deepcopy(config)
    context = f"方法 {registry_key or method.get('key', '?')}"
    for field in ('key', 'name', 'description', 'config_version', 'evaluation_strategy', 'aggregation_policy'):
        _require_nonempty_text(method, field, context)
    if registry_key and method['key'] != registry_key:
        raise MethodConfigError(f'{context} 的 key 与注册表不一致')
    if not isinstance(method.get('ai_supported'), bool):
        raise MethodConfigError(f'{context} ai_supported 必须为布尔值')
    if method['aggregation_policy'] not in AGGREGATION_POLICIES:
        raise MethodConfigError(f"{context} 聚合策略不存在: {method['aggregation_policy']}")

    variants = method.get('variants')
    if variants:
        if not isinstance(variants, dict):
            raise MethodConfigError(f'{context} variants 必须是对象')
        default_variant = method.get('default_variant')
        if default_variant not in variants:
            raise MethodConfigError(f'{context} default_variant 不存在')
        for variant_key, variant in variants.items():
            if not isinstance(variant, dict):
                raise MethodConfigError(f'{context} 变体 {variant_key} 必须是对象')
            _require_nonempty_text(variant, 'name', f'{context} 变体 {variant_key}')
            _validate_variant(variant, method, f'{context} 变体 {variant_key}')
    else:
        _validate_variant(method, method, context)

    if not method['ai_supported'] and not method.get('ai_unavailable_reason'):
        raise MethodConfigError(f'{context} AI 不可用时必须提供 ai_unavailable_reason')
    return method
