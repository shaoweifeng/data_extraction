"""Single source of truth for free, plan and administrator entitlements."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone


class EntitlementError(ValueError):
    pass


@dataclass(frozen=True)
class ResolvedEntitlements:
    plan_code: str
    plan_name: str
    source: str
    project_limit: int
    ai_call_slots: int
    storage_limit_mb: int
    entitlement_id: int | None = None
    starts_at: str | None = None
    expires_at: str | None = None

    def as_dict(self):
        return asdict(self)


def _is_admin(user) -> bool:
    profile = getattr(user, 'profile', None)
    return bool(user.is_superuser or (profile and profile.role == 'admin'))


def _grant_period(period):
    from core.services.credit_ledger_service import grant_batch_credits

    if period.grant_status == 'granted' and period.grant_batch_id:
        return period.grant_batch
    entitlement = period.entitlement
    amount = entitlement.price_version.included_credits
    txn = grant_batch_credits(
        entitlement.user,
        amount,
        batch_type='PLAN',
        batch_key=f'plan-period:{period.pk}:{period.period_start.isoformat()}',
        note=(
            f'{entitlement.price_version.plan.name} 套餐积分 '
            f'{period.period_start.date()}～{period.period_end.date()}'
        ),
        expires_at=period.period_end,
        entitlement=entitlement,
        txn_type='grant',
    )
    batch = txn.grant_batch
    period.grant_batch = batch
    period.grant_status = 'granted'
    period.save(update_fields=['grant_batch', 'grant_status', 'updated_at'])
    return batch


def _sync_locked(user, now):
    from core.models_billing import PlanBillingPeriod, UserPlanEntitlement

    entitlements = list(
        UserPlanEntitlement.objects.select_for_update()
        .filter(user=user).exclude(status='cancelled')
        .select_related('price_version__plan')
        .order_by('starts_at', 'pk')
    )
    for entitlement in entitlements:
        target = (
            'expired' if entitlement.expires_at <= now
            else 'active' if entitlement.starts_at <= now
            else 'scheduled'
        )
        if entitlement.status != target:
            entitlement.status = target
            entitlement.save(update_fields=['status', 'updated_at'])

    periods = list(
        PlanBillingPeriod.objects.select_for_update()
        .filter(entitlement__user=user, grant_status='pending')
        .select_related('entitlement__price_version__plan', 'entitlement__user')
        .order_by('period_start', 'pk')
    )
    for period in periods:
        if period.period_end <= now:
            period.grant_status = 'expired'
            period.save(update_fields=['grant_status', 'updated_at'])
        elif period.period_start <= now:
            _grant_period(period)


@transaction.atomic
def sync_user_plan(user, *, now=None):
    """Advance statuses and grant a currently due monthly period exactly once."""
    if not getattr(settings, 'PLAN_BILLING_ENABLED', False):
        return
    now = now or timezone.now()
    user = get_user_model().objects.select_for_update().get(pk=user.pk)
    _sync_locked(user, now)


def _active_entitlement(user, now):
    from core.models_billing import UserPlanEntitlement

    return (
        UserPlanEntitlement.objects.filter(
            user=user,
            status='active',
            starts_at__lte=now,
            expires_at__gt=now,
            price_version__status='published',
            price_version__plan__is_active=True,
        )
        .select_related('price_version__plan')
        .order_by('-starts_at', '-pk')
        .first()
    )


def resolve_user_entitlements(user, *, sync=True) -> ResolvedEntitlements:
    """Resolve administrator override > active plan > free defaults."""
    if sync and getattr(settings, 'PLAN_BILLING_ENABLED', False):
        sync_user_plan(user)
    profile = getattr(user, 'profile', None)
    project_override = getattr(profile, 'quota_projects_override', None)
    slots_override = getattr(profile, 'ai_call_slots_override', None)
    storage_override = getattr(profile, 'quota_storage_mb_override', None)

    if _is_admin(user):
        return ResolvedEntitlements(
            plan_code='ADMIN',
            plan_name='管理员',
            source='admin_override' if any(
                value is not None
                for value in (project_override, slots_override, storage_override)
            ) else 'admin',
            project_limit=project_override if project_override is not None else -1,
            ai_call_slots=slots_override if slots_override is not None else int(
                getattr(settings, 'AI_SCREEN_ADMIN_CONCURRENCY', 16)
            ),
            storage_limit_mb=storage_override if storage_override is not None else -1,
        )

    now = timezone.now()
    active = _active_entitlement(user, now) if getattr(settings, 'PLAN_BILLING_ENABLED', False) else None
    if active:
        version = active.price_version
        project_limit = version.project_limit
        ai_call_slots = version.ai_call_slots
        storage_limit_mb = version.storage_limit_mb
        source = 'plan'
        code = version.plan.code
        name = version.plan.name
        entitlement_id = active.pk
        starts_at = active.starts_at.isoformat()
        expires_at = active.expires_at.isoformat()
    else:
        project_limit = int(getattr(settings, 'PLAN_FREE_PROJECT_LIMIT', 1))
        ai_call_slots = int(getattr(settings, 'PLAN_FREE_AI_CALL_SLOTS', 2))
        storage_limit_mb = int(getattr(settings, 'PLAN_FREE_STORAGE_MB', 5120))
        source = 'free'
        code = 'FREE'
        name = '免费体验'
        entitlement_id = None
        starts_at = None
        expires_at = None

    if any(
        value is not None
        for value in (project_override, slots_override, storage_override)
    ):
        source = 'admin_override'
    return ResolvedEntitlements(
        plan_code=code,
        plan_name=name,
        source=source,
        project_limit=project_override if project_override is not None else project_limit,
        ai_call_slots=slots_override if slots_override is not None else ai_call_slots,
        storage_limit_mb=(
            storage_override if storage_override is not None else storage_limit_mb
        ),
        entitlement_id=entitlement_id,
        starts_at=starts_at,
        expires_at=expires_at,
    )


def _create_periods(entitlement, start, months):
    from core.models_billing import PlanBillingPeriod

    current = start
    anchor_day = entitlement.starts_at.day
    created = []
    for _ in range(months):
        # Preserve the original calendar-day anchor.  Jan 31 -> Feb 28/29 ->
        # Mar 31 instead of drifting permanently to the 28th.
        end = current + relativedelta(months=1, day=anchor_day)
        period, _ = PlanBillingPeriod.objects.get_or_create(
            entitlement=entitlement,
            period_start=current,
            defaults={'period_end': end},
        )
        created.append(period)
        current = end
    return created, current


@transaction.atomic
def redeem_plan_code(user, code_str: str, *, now=None):
    """Open, renew or schedule one plan code under a single user lock."""
    from core.models_billing import RechargeCode, UserPlanEntitlement

    if not getattr(settings, 'PLAN_BILLING_ENABLED', False):
        raise EntitlementError('plan_billing_disabled')
    if not getattr(settings, 'CREDIT_BATCH_LEDGER_ENABLED', False):
        raise EntitlementError('batch_ledger_required')
    now = now or timezone.now()
    user = get_user_model().objects.select_for_update().get(pk=user.pk)
    code = (
        RechargeCode.objects.select_for_update()
        .select_related('plan_price_version__plan')
        .filter(code=code_str)
        .first()
    )
    if code is None:
        raise EntitlementError('code_not_found')
    if not code.is_valid():
        raise EntitlementError('code_invalid')
    if code.code_type != 'PLAN' or not code.plan_price_version_id:
        raise EntitlementError('invalid_plan_code')
    version = code.plan_price_version
    if version.status != 'published' or not version.plan.is_active:
        raise EntitlementError('plan_version_unavailable')
    if version.effective_from and version.effective_from > now:
        raise EntitlementError('plan_version_unavailable')
    if version.effective_until and version.effective_until <= now:
        raise EntitlementError('plan_version_unavailable')

    _sync_locked(user, now)
    chain = list(
        UserPlanEntitlement.objects.select_for_update()
        .filter(user=user, expires_at__gt=now)
        .exclude(status='cancelled')
        .select_related('price_version__plan')
        .order_by('starts_at', 'pk')
    )
    active = next((item for item in chain if item.starts_at <= now < item.expires_at), None)
    future = [item for item in chain if item.starts_at > now]
    if active and version.plan_id != active.price_version.plan_id:
        different_future = [
            item for item in future
            if item.price_version.plan_id != active.price_version.plan_id
        ]
        if different_future and any(
            item.price_version.plan_id != version.plan_id for item in different_future
        ):
            raise EntitlementError('future_plan_change_exists')
    elif future and any(item.price_version.plan_id != version.plan_id for item in future):
        raise EntitlementError('future_plan_change_exists')

    months = max(1, int(code.valid_months or version.valid_months or 1))
    tail = max(chain, key=lambda item: item.expires_at) if chain else None
    starts_at = tail.expires_at if tail else now
    if tail and tail.price_version_id == version.pk:
        entitlement = tail
        period_start = tail.expires_at
        periods, expires_at = _create_periods(entitlement, period_start, months)
        entitlement.expires_at = expires_at
        entitlement.save(update_fields=['expires_at', 'updated_at'])
    else:
        expires_at = starts_at + relativedelta(months=months)
        entitlement = UserPlanEntitlement.objects.create(
            user=user,
            price_version=version,
            status='active' if starts_at <= now else 'scheduled',
            starts_at=starts_at,
            expires_at=expires_at,
            source_recharge_code=code,
        )
        periods, _ = _create_periods(entitlement, starts_at, months)

    for period in periods:
        if period.period_start <= now < period.period_end:
            _grant_period(period)

    code.is_used = True
    code.used_by = user
    code.used_at = now
    code.save(update_fields=['is_used', 'used_by', 'used_at'])
    return entitlement


def process_due_plan_periods(*, now=None) -> dict:
    from core.models_billing import UserPlanEntitlement

    now = now or timezone.now()
    user_ids = list(
        UserPlanEntitlement.objects.exclude(status='cancelled')
        .filter(starts_at__lte=now)
        .values_list('user_id', flat=True).distinct()
    )
    for user in get_user_model().objects.filter(pk__in=user_ids).iterator():
        sync_user_plan(user, now=now)
    return {'users_processed': len(user_ids)}
