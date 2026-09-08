"""Shared AI quota policy and preflight checks."""

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
    def preflight(user, ref_count: int, model_ids=None) -> int:
        """Validate estimated balance and return the estimate for display/logging."""
        estimated = estimate_credits(ref_count, list(model_ids or []))
        if not user or is_unlimited_ai_user(user):
            return estimated
        if not check_balance_sufficient(user, estimated):
            balance = get_balance(user)
            raise ValueError(
                f'余额不足（预估需 {estimated} credits，当前余额 {balance} credits）'
            )
        return estimated
