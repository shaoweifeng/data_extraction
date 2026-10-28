"""Shared token accumulation, audit logging and credit settlement."""

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

from django.conf import settings
from django.db import transaction

from core.ai.quota import is_unlimited_ai_user
from core.ai.usage_schema import (
    canonical_model_id, normalize_call_detail, summarize_complete_call_details,
)
from core.models_billing import CreditReservation, ModelBillingRate, ModelUsageDetail, TokenUsageLog
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
            nested_model_id = canonical_model_id(nested_model_id)
            target = self.model_usage.setdefault(nested_model_id, {
                'prompt_tokens': 0,
                'completion_tokens': 0,
                'total_tokens': 0,
                'cached_prompt_tokens': 0,
                'cache_write_prompt_tokens': 0,
                'calls': 0,
                'call_details': [],
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
                model_stats.get('cache_read_tokens', model_stats.get('cached_prompt_tokens', 0)) or 0
            )
            target['cache_write_prompt_tokens'] += int(
                model_stats.get(
                    'cache_write_tokens', model_stats.get('cache_write_prompt_tokens', 0)
                ) or 0
            )
            target['calls'] += int(model_stats.get('calls', 1) or 1)
            call_details = model_stats.get('call_details') or []
            for detail in call_details:
                if isinstance(detail, dict):
                    target['call_details'].append(
                        normalize_call_detail(detail, fallback_model_id=nested_model_id)
                    )

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
    pricing_version: str | None = None
    rate_snapshots: Any = None


class AIUsageSettlementService:
    @staticmethod
    @transaction.atomic
    def settle(context: AIUsageContext, usage) -> Dict:
        """Persist one task-level usage log and settle its credits atomically."""
        stats = usage.as_dict() if isinstance(usage, TokenUsageAccumulator) else dict(usage or {})
        canonical_totals = summarize_complete_call_details(stats.get('model_usage'))
        if canonical_totals:
            reported_totals = {
                key: int(stats.get(key, 0) or 0)
                for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')
            }
            canonical_summary = {
                key: canonical_totals[key]
                for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')
            }
            if reported_totals != canonical_summary:
                stats['usage_reconciliation'] = {
                    'reported': reported_totals,
                    'canonical': canonical_summary,
                }
            stats.update(canonical_summary)
        total_tokens = int(stats.get('total_tokens', 0) or 0)
        if not context.user or total_tokens <= 0:
            return stats

        legacy_credits = tokens_to_credits(total_tokens)
        ratio = getattr(settings, 'BILLING_CREDIT_TOKEN_RATIO', 1000)

        from core.ai.pricing import calculate_shadow_pricing
        shadow = calculate_shadow_pricing(stats.get('model_usage'))
        weighted = None
        pricing_version = shadow['pricing_version']
        credits = legacy_credits
        estimated_cost = shadow['estimated_cost_cny']
        if context.pricing_version or getattr(settings, 'MODEL_WEIGHTED_BILLING_ENABLED', False):
            from core.ai.pricing import calculate_versioned_pricing

            reservation = None
            if context.task:
                reservation = CreditReservation.objects.filter(task=context.task).first()
            pricing_version = (
                reservation.pricing_version if reservation
                else context.pricing_version or (
                    (context.task.config or {}).get('billing_pricing_version', settings.MODEL_WEIGHTED_BILLING_PRICING_VERSION)
                    if context.task else settings.MODEL_WEIGHTED_BILLING_PRICING_VERSION)
            )
            weighted = calculate_versioned_pricing(
                stats.get('model_usage'),
                pricing_version=pricing_version,
                allow_draft=getattr(settings, 'MODEL_WEIGHTED_BILLING_ALLOW_DRAFT', False),
                rates=context.rate_snapshots,
            )
            if weighted['task_credits'] is None:
                raise ValueError(f'存在未匹配费率，拒绝结算: {weighted["unknown_calls"]}')
            credits = weighted['task_credits']
            estimated_cost = weighted['estimated_cost_cny']

        stats.update({
            'credits_consumed': credits,
            'credits_actual': credits,
            'credits_estimate': credits,
            'credit_token_ratio': ratio,
        })
        stats.update({
            'pricing_version': pricing_version,
            'shadow_credits': shadow['shadow_credits'],
            'estimated_cost_cny': (
                str(estimated_cost) if estimated_cost is not None else None
            ),
            'pricing_unknown_models': shadow['unknown_models'],
        })

        model_name = ', '.join(context.model_ids) or 'unknown'
        project_name = context.project.name if context.project else '未知项目'
        detail = (
            f'{context.feature} · {project_name} · 模型:{model_name}'
            f'（{stats.get("ref_count", 0)}篇/{total_tokens} tokens）'
        )
        if context.feature == 'ai_rescreen':
            from core.ai.features import AI_FEATURE_LABELS
            detail = f'{AI_FEATURE_LABELS[context.feature]} · {project_name} · 模型:{model_name}（{stats.get("ref_count", 0)}篇）'[:255]

        if is_unlimited_ai_user(context.user):
            transaction_record = log_admin_usage(
                context.user,
                credits,
                task=context.task,
                idempotency_key=context.idempotency_key,
                note=(f'{detail}（管理员免费，等值{credits}积分）'[:255]
                      if context.feature == 'ai_rescreen' else
                      f'{context.feature}(免费) · {project_name} · 模型:{model_name}'
                      f'（{stats.get("ref_count", 0)}篇/{total_tokens} tokens，等值{credits} credits）'),
            )
        elif context.pricing_version or getattr(settings, 'BILLING_RESERVATION_ENABLED', False):
            if not context.task:
                raise ValueError('启用积分预占后，AI 结算必须关联任务')
            reservation = CreditReservation.objects.select_for_update().filter(
                task=context.task,
            ).first()
            if reservation is None:
                raise ValueError('任务缺少积分预占，拒绝结算')
            from core.services.credit_ledger_service import settle_reservation

            # An interrupted request can return after recovery released its
            # hold. Such late calls are explicitly platform-borne; keep their
            # audit without reopening or charging a terminal reservation.
            if (context.pricing_version and credits == 0 and reservation.status in ('released', 'cancelled', 'expired')):
                transaction_record = None
            else:
                transaction_record = settle_reservation(reservation, credits, note=detail)
            reservation.refresh_from_db()
            stats['credits_consumed'] = reservation.settled_credits
            stats['credits_actual'] = reservation.actual_credits
            stats['credits_estimate'] = reservation.estimated_credits
            stats['platform_covered_credits'] = reservation.platform_covered_credits
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
            'credits_consumed': stats['credits_consumed'],
            'ref_count': stats.get('ref_count', 0),
            'usage_breakdown': stats.get('model_usage', {}),
            'pricing_version': pricing_version,
            'shadow_credits': shadow['shadow_credits'],
            'estimated_cost_cny': estimated_cost,
        }
        if transaction_record is not None:
            usage_log, _ = TokenUsageLog.objects.update_or_create(
                transaction=transaction_record,
                defaults=usage_defaults,
            )
        elif context.task and (context.pricing_version or getattr(settings, 'BILLING_RESERVATION_ENABLED', False)):
            usage_log, _ = TokenUsageLog.objects.update_or_create(
                task=context.task,
                pricing_version=pricing_version,
                defaults=usage_defaults,
            )
        else:
            usage_log = TokenUsageLog.objects.create(
                transaction=None,
                **usage_defaults,
            )

        # Rebuild the task-level per-call audit rows from the normalized payload.
        # The enclosing transaction and usage_log/call_index uniqueness make a
        # repeated idempotent settlement deterministic without double records.
        priced_by_index = {
            item['call_index']: item for item in (weighted or {}).get('priced_calls', [])
        }
        rate_keys = {item['rate_key'] for item in priced_by_index.values()}
        rates_by_key = {
            rate.rate_key: rate for rate in ModelBillingRate.objects.filter(rate_key__in=rate_keys)
        }
        call_rows = []
        call_index = 0
        for supplied_model_id, model_stats in (stats.get('model_usage') or {}).items():
            for raw_detail in model_stats.get('call_details') or []:
                detail = normalize_call_detail(
                    raw_detail, fallback_model_id=canonical_model_id(supplied_model_id),
                )
                call_index += 1
                priced = priced_by_index.get(call_index, {})
                call_rows.append(ModelUsageDetail(
                    usage_log=usage_log,
                    task=context.task,
                    user=context.user,
                    call_index=call_index,
                    provider=detail['provider'],
                    region=detail['region'],
                    service_tier=detail['service_tier'],
                    model_id=detail['model_id'],
                    provider_model=detail['provider_model'],
                    provider_request_id=detail['provider_request_id'],
                    context_tokens=detail['context_tokens'],
                    input_tokens=detail['input_tokens'],
                    output_tokens=detail['output_tokens'],
                    cache_read_tokens=detail['cache_read_tokens'],
                    cache_write_tokens=detail['cache_write_tokens'],
                    attempt_number=detail['attempt_number'],
                    attempt_reason=detail['attempt_reason'],
                    charge_bearer=detail['charge_bearer'],
                    rate=rates_by_key.get(priced.get('rate_key')),
                    estimated_cost_cny=priced.get('estimated_cost_cny'),
                    raw_credits=priced.get('raw_credits'),
                    raw_payload=detail,
                ))
        if call_rows:
            ModelUsageDetail.objects.filter(usage_log=usage_log).delete()
            ModelUsageDetail.objects.bulk_create(call_rows)

        if context.task:
            result = dict(context.task.result or {})
            result['token_stats'] = stats
            context.task.result = result
            context.task.save(update_fields=['result', 'updated_at'])

        stats['usage_log_id'] = usage_log.pk
        stats['transaction_id'] = transaction_record.pk if transaction_record else None
        stats['is_unlimited'] = is_unlimited_ai_user(context.user)
        return stats
