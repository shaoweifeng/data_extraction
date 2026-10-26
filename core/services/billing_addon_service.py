"""Versioned add-on catalogue and atomic, subscription-aware redemption."""

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.models_billing import AddonProductVersion, RechargeCode, UserConcurrencyGrant
from core.services.entitlement_service import _active_entitlement, _sync_locked


class AddonError(ValueError):
    pass


def active_concurrency_grant(user, now):
    return (UserConcurrencyGrant.objects.filter(
        user=user, cancelled=False, starts_at__lte=now, expires_at__gt=now,
    ).select_related('version__product').order_by('-expires_at', '-pk').first())


def eligibility(user, version, *, now=None):
    """Evaluate actual plan rights, ignoring an existing add-on's slot increase."""
    now = now or timezone.now()
    plan = _active_entitlement(user, now) if settings.PLAN_BILLING_ENABLED else None
    if version.requires_subscription and not plan:
        return '请先开通有效的个人套餐'
    if version.kind == 'CONCURRENCY':
        base = plan.price_version.ai_call_slots if plan else settings.PLAN_FREE_AI_CALL_SLOTS
        override = getattr(getattr(user, 'profile', None), 'ai_call_slots_override', None)
        if override is not None:
            base = override
        if user.is_superuser or getattr(getattr(user, 'profile', None), 'role', '') == 'admin':
            return '管理员无需购买并发升级'
        if version.target_slots <= base:
            return '当前基础并发已达到或超过此档位'
        outstanding = UserConcurrencyGrant.objects.filter(
            user=user, cancelled=False, expires_at__gt=now,
        ).exclude(version__target_slots=version.target_slots)
        if outstanding.exists():
            return '已有其他档位的并发包，请到期后再更换'
    return ''


def catalog(user):
    from core.services.entitlement_service import sync_user_plan
    sync_user_plan(user)
    now = timezone.now()
    versions = AddonProductVersion.objects.filter(
        status='published', product__is_active=True,
    ).select_related('product').order_by('product__sort_order', 'product_id', '-created_at', '-pk')
    result, seen = [], set()
    for version in versions:
        if version.product_id in seen:
            continue
        seen.add(version.product_id)
        reason = eligibility(user, version, now=now)
        result.append({
            'id': version.pk, 'code': version.product.code, 'name': version.product.name,
            'version': version.version, 'kind': version.kind,
            'reference_price_cny': str(version.reference_price_cny),
            'credits': version.credits, 'target_slots': version.target_slots,
            'valid_months': version.valid_months,
            'requires_subscription': version.requires_subscription,
            'eligible': not reason, 'ineligible_reason': reason,
        })
    return result


@transaction.atomic
def redeem_addon_code(user, code_str):
    from core.services.credit_ledger_service import grant_batch_credits

    if not settings.CREDIT_BATCH_LEDGER_ENABLED:
        raise AddonError('积分批次账本尚未启用')
    # All commercial redemption follows user -> code -> account lock order.
    user = get_user_model().objects.select_for_update().get(pk=user.pk)
    code = RechargeCode.objects.select_for_update().filter(code=code_str).first()
    now = timezone.now()
    if code is None or not code.is_valid() or (code.expires_at and code.expires_at <= now):
        raise AddonError('兑换码不存在、已使用或已过期')
    if code.code_type != 'ADDON' or not code.addon_version_id:
        raise AddonError('不是有效的加购商品码')
    version = code.addon_version
    if version.status != 'published':
        raise AddonError('商品版本已撤销或尚未发布')
    # Listing status does not invalidate previously issued codes.
    try:
        version.full_clean()
    except ValidationError as exc:
        raise AddonError('商品配置无效，请联系管理员') from exc
    if settings.PLAN_BILLING_ENABLED:
        _sync_locked(user, now)
    reason = eligibility(user, version, now=now)
    if reason:
        raise AddonError(reason)

    result = {'message': '兑换成功', 'credits_added': 0}
    if version.kind == 'CONCURRENCY':
        tail = UserConcurrencyGrant.objects.filter(
            user=user, cancelled=False, expires_at__gt=now,
        ).order_by('-expires_at', '-pk').first()
        start = tail.expires_at if tail else now
        # Anchor renewal to the first grant, including month-end renewals.
        anchor_day = tail.anchor_day if tail else start.day
        end = start + relativedelta(months=version.valid_months, day=anchor_day)
        grant = UserConcurrencyGrant.objects.create(
            user=user, version=version, source_code=code, starts_at=start, expires_at=end,
            anchor_day=anchor_day,
        )
        result.update(message='并发升级兑换成功', grant_id=grant.pk, expires_at=end.isoformat())
    else:
        end = now + relativedelta(months=version.valid_months)
        txn = grant_batch_credits(
            user, version.credits, batch_type='PURCHASED',
            batch_key=f'addon-code:{code.pk}', note=f'{version.product.name} · {version.version}',
            operator=user, txn_type='recharge', expires_at=end,
        )
        txn.grant_batch.addon_version = version
        txn.grant_batch.save(update_fields=['addon_version'])
        result.update(message='积分补充成功', credits_added=version.credits, expires_at=end.isoformat())
    code.is_used, code.used_by, code.used_at = True, user, now
    code.save(update_fields=['is_used', 'used_by', 'used_at'])
    return result
