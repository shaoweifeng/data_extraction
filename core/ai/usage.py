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

    def add(self, usage: Optional[Dict]) -> None:
        if not usage:
            return
        self.prompt_tokens += int(usage.get('prompt', usage.get('prompt_tokens', 0)) or 0)
        self.completion_tokens += int(
            usage.get('completion', usage.get('completion_tokens', 0)) or 0
        )
        self.total_tokens += int(usage.get('total', usage.get('total_tokens', 0)) or 0)
        self.ref_count += 1

    def as_dict(self) -> Dict[str, int]:
        return {
            'prompt_tokens': self.prompt_tokens,
            'completion_tokens': self.completion_tokens,
            'total_tokens': self.total_tokens,
            'ref_count': self.ref_count,
        }


@dataclass(frozen=True)
class AIUsageContext:
    feature: str
    user: Any
    project: Any
    task: Any
    model_ids: Iterable[str]


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
                note=f'{context.feature}(免费) · {project_name} · 模型:{model_name}'
                     f'（{stats.get("ref_count", 0)}篇/{total_tokens} tokens，等值{credits} credits）',
            )
        else:
            transaction_record = consume_credits(
                context.user, credits, task=context.task, note=detail,
            )

        usage_log = TokenUsageLog.objects.create(
            task=context.task,
            project=context.project,
            user=context.user,
            model=model_name,
            prompt_tokens=stats.get('prompt_tokens', 0),
            completion_tokens=stats.get('completion_tokens', 0),
            total_tokens=total_tokens,
            credits_consumed=credits,
            ref_count=stats.get('ref_count', 0),
            transaction=transaction_record,
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
