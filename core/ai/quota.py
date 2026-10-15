"""Shared AI quota policy and preflight checks."""

from django.conf import settings

from core.services.billing_service import (
    check_balance_sufficient,
    estimate_credits,
    get_balance,
)


def is_unlimited_ai_user(user) -> bool:
    """Use the application's stable administrator definition for free AI usage."""
    if not user:
        return False
    if user.is_superuser:
        return True
    profile = getattr(user, 'profile', None)
    return bool(profile and profile.role == 'admin')


class AIQuotaService:
    @staticmethod
    def preflight(
        user,
        ref_count: int,
        model_ids=None,
        *,
        feature: str = 'ai_screen',
        task=None,
    ) -> int:
        """Validate estimated balance and return the estimate for display/logging."""
        estimated = estimate_credits(
            ref_count,
            list(model_ids or []),
            feature=feature,
        )
        if not user or is_unlimited_ai_user(user):
            return estimated
        if getattr(settings, 'BILLING_RESERVATION_ENABLED', False) and task is not None:
            if not getattr(settings, 'CREDIT_BATCH_LEDGER_ENABLED', False):
                raise RuntimeError('启用积分预占前必须先启用批次账本')
            from core.services.credit_ledger_service import (
                reservation_key_for_task, reserve_credits,
            )

            reserve_credits(
                user,
                estimated,
                task=task,
                idempotency_key=reservation_key_for_task(task),
                pricing_version=(task.config or {}).get(
                    'billing_pricing_version',
                    settings.MODEL_WEIGHTED_BILLING_PRICING_VERSION,
                ),
            )
            return estimated
        if not check_balance_sufficient(user, estimated):
            balance = get_balance(user)
            raise ValueError(
                f'余额不足（预估需 {estimated} credits，当前余额 {balance} credits）'
            )
        return estimated
