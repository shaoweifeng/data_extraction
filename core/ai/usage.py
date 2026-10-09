"""Shared token accumulation, audit logging and credit settlement."""

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

from django.conf import settings
from django.db import transaction

from core.ai.quota import is_unlimited_ai_user
from core.models_billing import TokenUsageLog
from core.services.billing_service import consume_credits, log_admin_usage, tokens_to_credits


class TokenUsageAccumulator:
    """Accumulate provider usage dictionaries without feature-specific arithmetic."""

    def __init__(self):
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.ref_count = 0
        self.model_usage = {}

    def add(self, usage: Optional[Dict], model_id: str | None = None) -> None:
        if not usage:
            return
        self.prompt_tokens += int(usage.get('prompt', usage.get('prompt_tokens', 0)) or 0)
        self.completion_tokens += int(
            usage.get('completion', usage.get('completion_tokens', 0)) or 0
        )
        self.total_tokens += int(usage.get('total', usage.get('total_tokens', 0)) or 0)
        self.ref_count += 1

        nested_usage = usage.get('model_usage') or {}
        if model_id:
            nested_usage = {model_id: usage}
        for nested_model_id, model_stats in nested_usage.items():
            if not isinstance(model_stats, dict):
                continue
            target = self.model_usage.setdefault(nested_model_id, {
                'prompt_tokens': 0,
                'completion_tokens': 0,
                'total_tokens': 0,
                'cached_prompt_tokens': 0,
                'calls': 0,
            })
            prompt = int(model_stats.get('prompt_tokens', model_stats.get('prompt', 0)) or 0)
            completion = int(
                model_stats.get('completion_tokens', model_stats.get('completion', 0)) or 0
            )
            total = int(model_stats.get('total_tokens', model_stats.get('total', 0)) or 0)
            target['prompt_tokens'] += prompt
            target['completion_tokens'] += completion
            target['total_tokens'] += total or prompt + completion
            target['cached_prompt_tokens'] += int(
                model_stats.get('cached_prompt_tokens', 0) or 0
            )
            target['calls'] += int(model_stats.get('calls', 1) or 1)

    def as_dict(self) -> Dict[str, int]:
        result = {
            'prompt_tokens': self.prompt_tokens,
            'completion_tokens': self.completion_tokens,
            'total_tokens': self.total_tokens,
            'ref_count': self.ref_count,
        }
        if self.model_usage:
            result['model_usage'] = self.model_usage
        return result


@dataclass(frozen=True)
class AIUsageContext:
    feature: str
    user: Any
    project: Any
    task: Any
    model_ids: Iterable[str]
    idempotency_key: str | None = None


class AIUsageSettlementService:
    @staticmethod
    @transaction.atomic
    def settle(context: AIUsageContext, usage) -> Dict:
        """Persist one task-level usage log and settle its credits atomically."""
        stats = usage.as_dict() if isinstance(usage, TokenUsageAccumulator) else dict(usage or {})
        total_tokens = int(stats.get('total_tokens', 0) or 0)
        if not context.user or total_tokens <= 0:
            return stats

        credits = tokens_to_credits(total_tokens)
        ratio = getattr(settings, 'BILLING_CREDIT_TOKEN_RATIO', 1000)
        stats.update({
            'credits_consumed': credits,
            'credits_actual': credits,
            'credits_estimate': credits,
            'credit_token_ratio': ratio,
        })

        from core.ai.pricing import calculate_shadow_pricing
        shadow = calculate_shadow_pricing(stats.get('model_usage'))
        stats.update({
            'pricing_version': shadow['pricing_version'],
            'shadow_credits': shadow['shadow_credits'],
            'estimated_cost_cny': (
                str(shadow['estimated_cost_cny'])
                if shadow['estimated_cost_cny'] is not None else None
            ),
            'pricing_unknown_models': shadow['unknown_models'],
        })

        model_name = ', '.join(context.model_ids) or 'unknown'
        project_name = context.project.name if context.project else '未知项目'
        detail = (
            f'{context.feature} · {project_name} · 模型:{model_name}'
            f'（{stats.get("ref_count", 0)}篇/{total_tokens} tokens）'
        )

        if is_unlimited_ai_user(context.user):
            transaction_record = log_admin_usage(
                context.user,
                credits,
                task=context.task,
                idempotency_key=context.idempotency_key,
                note=f'{context.feature}(免费) · {project_name} · 模型:{model_name}'
                     f'（{stats.get("ref_count", 0)}篇/{total_tokens} tokens，等值{credits} credits）',
            )
        else:
            transaction_record = consume_credits(
                context.user,
                credits,
                task=context.task,
                note=detail,
                idempotency_key=context.idempotency_key,
            )

        usage_defaults = {
            'task': context.task,
            'project': context.project,
            'user': context.user,
            'model': model_name,
            'prompt_tokens': stats.get('prompt_tokens', 0),
            'completion_tokens': stats.get('completion_tokens', 0),
            'total_tokens': total_tokens,
            'credits_consumed': credits,
            'ref_count': stats.get('ref_count', 0),
            'usage_breakdown': stats.get('model_usage', {}),
            'pricing_version': shadow['pricing_version'],
            'shadow_credits': shadow['shadow_credits'],
            'estimated_cost_cny': shadow['estimated_cost_cny'],
        }
        if transaction_record is not None:
            usage_log, _ = TokenUsageLog.objects.update_or_create(
                transaction=transaction_record,
                defaults=usage_defaults,
            )
        else:
            usage_log = TokenUsageLog.objects.create(
                transaction=None,
                **usage_defaults,
            )

        if context.task:
            result = dict(context.task.result or {})
            result['token_stats'] = stats
            context.task.result = result
            context.task.save(update_fields=['result', 'updated_at'])

        stats['usage_log_id'] = usage_log.pk
        stats['transaction_id'] = transaction_record.pk if transaction_record else None
        stats['is_unlimited'] = is_unlimited_ai_user(context.user)
        return stats
