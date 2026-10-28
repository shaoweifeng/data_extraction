"""Batch-backed credit ledger and reservation state machine.

The account balance is the immediately available amount.  Grant batches retain
source and expiry information; reservations move amounts from ``remaining`` to
``reserved`` before any provider call starts.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Case, IntegerField, Q, Sum, Value, When
from django.utils import timezone


class CreditLedgerError(ValueError):
    pass


def reservation_key_for_task(task) -> str:
    return f'ai-task:{task.pk}:reservation'


def _transaction_key(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode('utf-8')).hexdigest()[:48]
    return f'{prefix}:{digest}'


def _grant_transaction_key(batch_key: str) -> str:
    """Keep short business keys readable; hash only keys too long for the GL."""
    if len(batch_key) <= 128:
        return batch_key
    return _transaction_key('ledger-grant', batch_key)


def _lock_account(user):
    from core.models_billing import CreditAccount

    CreditAccount.objects.get_or_create(
        user=user,
        defaults={'balance': 0, 'total_granted': 0, 'total_consumed': 0},
    )
    return CreditAccount.objects.select_for_update().get(user=user)


def _batch_ordering():
    return Case(
        When(expires_at__isnull=True, then=Value(1)),
        default=Value(0),
        output_field=IntegerField(),
    )


def _active_batches(account, *, now=None):
    from core.models_billing import CreditGrantBatch

    now = now or timezone.now()
    return CreditGrantBatch.objects.select_for_update().filter(
        account=account,
        remaining_amount__gt=0,
    ).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now),
    ).order_by(_batch_ordering(), 'expires_at', 'created_at', 'pk')


def _expire_due_locked(account, *, now=None) -> int:
    from core.models_billing import CreditAllocation, CreditGrantBatch, CreditTransaction

    now = now or timezone.now()
    expired_total = 0
    batches = CreditGrantBatch.objects.select_for_update().filter(
        account=account,
        expires_at__isnull=False,
        expires_at__lte=now,
        remaining_amount__gt=0,
    ).order_by('expires_at', 'pk')
    for batch in batches:
        amount = batch.remaining_amount
        if account.balance < amount:
            raise CreditLedgerError(
                f'积分账本不一致：账户可用余额 {account.balance} 小于到期批次 {amount}'
            )
        account.balance -= amount
        batch.remaining_amount = 0
        batch.save(update_fields=['remaining_amount', 'updated_at'])
        txn, created = CreditTransaction.objects.get_or_create(
            idempotency_key=f'expire-batch:{batch.pk}',
            defaults={
                'account': account,
                'txn_type': 'expire',
                'amount': -amount,
                'balance_after': account.balance,
                'note': f'积分批次到期：{batch.batch_key}',
            },
        )
        if created:
            CreditAllocation.objects.create(
                transaction=txn,
                batch=batch,
                allocation_type='expire',
                amount=amount,
            )
        expired_total += amount
    if expired_total:
        account.save(update_fields=['balance', 'updated_at'])
    return expired_total


@transaction.atomic
def expire_due_batches(user, *, now=None) -> int:
    account = _lock_account(user)
    return _expire_due_locked(account, now=now)


@transaction.atomic
def grant_batch_credits(
    user,
    amount: int,
    *,
    batch_type: str,
    batch_key: str,
    note: str = '',
    operator=None,
    expires_at=None,
    entitlement=None,
    txn_type: str = 'grant',
):
    """Grant one immutable source batch and its matching general-ledger row."""
    from core.models_billing import CreditGrantBatch, CreditTransaction

    if amount <= 0:
        raise CreditLedgerError('发放积分必须为正整数')
    if len(batch_key) > 160:
        raise CreditLedgerError('积分批次幂等键长度不能超过 160 个字符')

    account = _lock_account(user)
    existing = CreditGrantBatch.objects.select_for_update().filter(batch_key=batch_key).first()
    if existing:
        if (
            existing.account_id != account.pk
            or existing.granted_amount != amount
            or existing.batch_type != batch_type
        ):
            raise CreditLedgerError('积分批次幂等键已被其他发放操作使用')
        if not existing.grant_transaction_id:
            raise CreditLedgerError('积分批次缺少发放流水')
        return existing.grant_transaction

    account.balance += amount
    account.total_granted += amount
    account.save(update_fields=['balance', 'total_granted', 'updated_at'])
    txn = CreditTransaction.objects.create(
        account=account,
        txn_type=txn_type,
        amount=amount,
        balance_after=account.balance,
        note=note,
        created_by=operator,
        idempotency_key=_grant_transaction_key(batch_key),
    )
    CreditGrantBatch.objects.create(
        account=account,
        batch_type=batch_type,
        batch_key=batch_key,
        granted_amount=amount,
        remaining_amount=amount,
        expires_at=expires_at,
        entitlement=entitlement,
        grant_transaction=txn,
    )
    return txn


def _consume_available_locked(account, amount: int):
    """Consume available batches and return ``[(batch, amount), ...]``."""
    _expire_due_locked(account)
    batches = list(_active_batches(account))
    available = sum(batch.remaining_amount for batch in batches)
    if account.balance < amount or available < amount:
        raise CreditLedgerError(
            f'余额不足（需 {amount}，现有 {min(account.balance, available)} credits）'
        )

    remaining = amount
    consumed = []
    for batch in batches:
        take = min(batch.remaining_amount, remaining)
        if not take:
            continue
        batch.remaining_amount -= take
        batch.save(update_fields=['remaining_amount', 'updated_at'])
        consumed.append((batch, take))
        remaining -= take
        if remaining == 0:
            break
    return consumed


@transaction.atomic
def consume_batch_credits(
    user,
    amount: int,
    *,
    task=None,
    note: str = '',
    idempotency_key: str | None = None,
    txn_type: str = 'consume',
):
    from core.models_billing import CreditAllocation, CreditTransaction

    if amount <= 0:
        return None
    account = _lock_account(user)
    if idempotency_key:
        existing = CreditTransaction.objects.select_for_update().filter(
            idempotency_key=idempotency_key,
        ).first()
        if existing:
            if existing.account_id != account.pk or existing.amount != -amount:
                raise CreditLedgerError('幂等键已被其他额度操作使用')
            return existing

    consumed = _consume_available_locked(account, amount)
    account.balance -= amount
    if txn_type == 'consume':
        account.total_consumed += amount
    account.save(update_fields=['balance', 'total_consumed', 'updated_at'])
    txn = CreditTransaction.objects.create(
        account=account,
        txn_type=txn_type,
        amount=-amount,
        balance_after=account.balance,
        task=task,
        note=note,
        idempotency_key=idempotency_key,
    )
    CreditAllocation.objects.bulk_create([
        CreditAllocation(
            transaction=txn,
            batch=batch,
            allocation_type='consume',
            amount=used,
        )
        for batch, used in consumed
    ])
    return txn


@transaction.atomic
def refund_consumption(
    original_transaction,
    amount: int,
    *,
    note: str = '',
    idempotency_key: str | None = None,
):
    """Refund against the exact source batches used by one consume transaction."""
    from core.models_billing import (
        CreditAccount, CreditAllocation, CreditGrantBatch, CreditTransaction,
    )

    if amount <= 0:
        return None
    original_ref = CreditTransaction.objects.only('account_id').get(pk=original_transaction.pk)
    account = CreditAccount.objects.select_for_update().get(pk=original_ref.account_id)
    original = CreditTransaction.objects.select_for_update().get(pk=original_transaction.pk)
    if original.txn_type != 'consume':
        raise CreditLedgerError('只能针对消费流水退款')
    if idempotency_key:
        existing = CreditTransaction.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            if existing.reverses_transaction_id != original.pk or existing.amount != amount:
                raise CreditLedgerError('退款幂等键已被其他操作使用')
            return existing

    prior_refunded = CreditAllocation.objects.filter(
        transaction__reverses_transaction=original,
        allocation_type='refund',
    ).values('batch_id').annotate(total=Sum('amount'))
    refunded_by_batch = {row['batch_id']: row['total'] for row in prior_refunded}
    sources = list(CreditAllocation.objects.filter(
        transaction=original,
        allocation_type='consume',
    ).select_related('batch').order_by('-batch__expires_at', '-batch_id'))
    refundable = sum(
        max(0, row.amount - refunded_by_batch.get(row.batch_id, 0)) for row in sources
    )
    if refundable < amount:
        raise CreditLedgerError(f'退款超过原消费可退额度（最多 {refundable}）')

    txn = CreditTransaction.objects.create(
        account=account,
        txn_type='refund',
        amount=amount,
        balance_after=account.balance + amount,
        task=original.task,
        note=note or f'退回消费流水 #{original.pk}',
        idempotency_key=idempotency_key,
        reverses_transaction=original,
    )
    remaining = amount
    now = timezone.now()
    for source in sources:
        available = max(0, source.amount - refunded_by_batch.get(source.batch_id, 0))
        restore = min(available, remaining)
        if not restore:
            continue
        batch = CreditGrantBatch.objects.select_for_update().get(pk=source.batch_id)
        batch.remaining_amount += restore
        batch.save(update_fields=['remaining_amount', 'updated_at'])
        CreditAllocation.objects.create(
            transaction=txn,
            batch=batch,
            allocation_type='refund',
            amount=restore,
        )
        account.balance += restore
        remaining -= restore
        if remaining == 0:
            break
    account.total_consumed = max(0, account.total_consumed - amount)
    account.save(update_fields=['balance', 'total_consumed', 'updated_at'])
    txn.balance_after = account.balance
    txn.save(update_fields=['balance_after'])
    _expire_due_locked(account, now=now)
    return txn


@transaction.atomic
def reserve_credits(
    user,
    amount: int,
    *,
    task,
    idempotency_key: str,
    pricing_version: str,
    expires_at=None,
):
    from core.models_billing import CreditReservation, CreditReservationAllocation

    if amount <= 0:
        raise CreditLedgerError('预占积分必须为正整数')
    account = _lock_account(user)
    existing = CreditReservation.objects.select_for_update().filter(
        idempotency_key=idempotency_key,
    ).first()
    if existing:
        if (
            existing.account_id != account.pk
            or existing.pricing_version != pricing_version
        ):
            raise CreditLedgerError('预占幂等键已被其他任务使用')
        # Worker/Celery retry may resume only the unfinished subset of the same
        # task.  Keep the original, larger reservation instead of reserving or
        # releasing funds again mid-task.
        if amount > existing.estimated_credits:
            raise CreditLedgerError('重试任务的预估额度超过原预占')
        return existing

    allocations = _consume_available_locked(account, amount)
    reservation = CreditReservation.objects.create(
        account=account,
        task=task,
        idempotency_key=idempotency_key,
        pricing_version=pricing_version,
        status='reserved',
        estimated_credits=amount,
        reserved_credits=amount,
        expires_at=expires_at or timezone.now() + timedelta(
            seconds=getattr(settings, 'BILLING_RESERVATION_TTL_SECONDS', 86400),
        ),
    )
    rows = []
    for batch, reserved in allocations:
        batch.reserved_amount += reserved
        batch.save(update_fields=['reserved_amount', 'updated_at'])
        rows.append(CreditReservationAllocation(
            reservation=reservation,
            batch=batch,
            reserved_amount=reserved,
        ))
    CreditReservationAllocation.objects.bulk_create(rows)
    account.balance -= amount
    account.save(update_fields=['balance', 'updated_at'])
    return reservation


@transaction.atomic
def extend_reservation(reservation, required_credits: int):
    """Grow a live hold atomically before another provider call (never after it)."""
    from core.models_billing import CreditAccount, CreditReservation, CreditReservationAllocation

    ref = CreditReservation.objects.only('account_id').get(pk=reservation.pk)
    account = CreditAccount.objects.select_for_update().get(pk=ref.account_id)
    reservation = CreditReservation.objects.select_for_update().get(pk=reservation.pk)
    if reservation.status != 'reserved':
        raise CreditLedgerError('只有活动预占可补充额度')
    amount = max(0, int(required_credits) - reservation.reserved_credits)
    if not amount:
        return reservation
    allocations = _consume_available_locked(account, amount)
    for batch, reserved in allocations:
        batch.reserved_amount += reserved
        batch.save(update_fields=['reserved_amount', 'updated_at'])
        allocation, _ = CreditReservationAllocation.objects.get_or_create(
            reservation=reservation, batch=batch, defaults={'reserved_amount': 0})
        allocation.reserved_amount += reserved
        allocation.save(update_fields=['reserved_amount', 'updated_at'])
    reservation.reserved_credits += amount
    reservation.estimated_credits = max(reservation.estimated_credits, reservation.reserved_credits)
    reservation.save(update_fields=['reserved_credits', 'estimated_credits', 'updated_at'])
    account.balance -= amount
    account.save(update_fields=['balance', 'updated_at'])
    return reservation


@transaction.atomic
def settle_reservation(reservation, actual_credits: int, *, note: str = ''):
    from core.models_billing import (
        CreditAccount, CreditAllocation, CreditGrantBatch, CreditReservation,
        CreditReservationAllocation, CreditTransaction,
    )

    actual_credits = max(0, int(actual_credits))
    reservation_ref = CreditReservation.objects.only('account_id').get(pk=reservation.pk)
    account = CreditAccount.objects.select_for_update().get(pk=reservation_ref.account_id)
    reservation = CreditReservation.objects.select_for_update().get(pk=reservation.pk)
    if reservation.status == 'settled':
        return reservation.settlement_transaction
    if reservation.status != 'reserved':
        raise CreditLedgerError(f'预占状态 {reservation.status} 不能结算')
    allocation_rows = list(CreditReservationAllocation.objects.select_for_update().filter(
        reservation=reservation,
    ).select_related('batch').order_by('batch__expires_at', 'batch_id'))

    remaining_actual = actual_credits
    consumed_by_batch = defaultdict(int)
    for allocation in allocation_rows:
        available_reserved = max(
            0,
            allocation.reserved_amount - allocation.consumed_amount - allocation.released_amount,
        )
        consume = min(available_reserved, remaining_actual)
        if consume:
            batch = CreditGrantBatch.objects.select_for_update().get(pk=allocation.batch_id)
            if batch.reserved_amount < consume:
                raise CreditLedgerError('积分批次预占余额不一致')
            batch.reserved_amount -= consume
            batch.save(update_fields=['reserved_amount', 'updated_at'])
            allocation.consumed_amount += consume
            allocation.save(update_fields=['consumed_amount', 'updated_at'])
            consumed_by_batch[batch.pk] += consume
            remaining_actual -= consume
        if remaining_actual == 0:
            break

    # Actual usage may exceed the estimate.  Consume currently available batches;
    # if those are exhausted, the platform bears the remainder instead of creating
    # a negative user balance after the provider has already charged the platform.
    if remaining_actual:
        _expire_due_locked(account)
        for batch in list(_active_batches(account)):
            consume = min(batch.remaining_amount, remaining_actual)
            if not consume:
                continue
            batch.remaining_amount -= consume
            batch.save(update_fields=['remaining_amount', 'updated_at'])
            allocation, _ = CreditReservationAllocation.objects.get_or_create(
                reservation=reservation,
                batch=batch,
            )
            allocation.additional_consumed_amount += consume
            allocation.save(update_fields=['additional_consumed_amount', 'updated_at'])
            consumed_by_batch[batch.pk] += consume
            account.balance -= consume
            remaining_actual -= consume
            if remaining_actual == 0:
                break

    charged = actual_credits - remaining_actual
    now = timezone.now()
    for allocation in allocation_rows:
        allocation.refresh_from_db()
        unused = max(
            0,
            allocation.reserved_amount - allocation.consumed_amount - allocation.released_amount,
        )
        if not unused:
            continue
        batch = CreditGrantBatch.objects.select_for_update().get(pk=allocation.batch_id)
        if batch.reserved_amount < unused:
            raise CreditLedgerError('积分批次待释放预占余额不一致')
        batch.reserved_amount -= unused
        if batch.expires_at is None or batch.expires_at > now:
            batch.remaining_amount += unused
            account.balance += unused
        batch.save(update_fields=['remaining_amount', 'reserved_amount', 'updated_at'])
        allocation.released_amount += unused
        allocation.save(update_fields=['released_amount', 'updated_at'])

    txn = None
    if charged:
        txn = CreditTransaction.objects.create(
            account=account,
            txn_type='consume',
            amount=-charged,
            balance_after=account.balance,
            task=reservation.task,
            note=note or f'AI任务结算（实际 {actual_credits}，用户承担 {charged}）',
            idempotency_key=_transaction_key('reservation-settle', reservation.idempotency_key),
        )
        batches = {
            batch.pk: batch for batch in CreditGrantBatch.objects.filter(
                pk__in=consumed_by_batch,
            )
        }
        CreditAllocation.objects.bulk_create([
            CreditAllocation(
                transaction=txn,
                batch=batches[batch_id],
                allocation_type='consume',
                amount=amount,
            )
            for batch_id, amount in consumed_by_batch.items()
        ])
        account.total_consumed += charged

    account.save(update_fields=['balance', 'total_consumed', 'updated_at'])
    reservation.status = 'settled'
    reservation.settled_credits = charged
    reservation.actual_credits = actual_credits
    reservation.platform_covered_credits = remaining_actual
    reservation.settlement_transaction = txn
    reservation.save(update_fields=[
        'status', 'settled_credits', 'actual_credits', 'platform_covered_credits',
        'settlement_transaction', 'updated_at',
    ])
    return txn


@transaction.atomic
def release_reservation(reservation, *, status: str = 'released', reason: str = '') -> int:
    from core.models_billing import (
        CreditAccount, CreditGrantBatch, CreditReservation, CreditReservationAllocation,
    )

    if status not in {'released', 'cancelled', 'expired'}:
        raise CreditLedgerError('无效的预占释放状态')
    reservation_ref = CreditReservation.objects.only('account_id').get(pk=reservation.pk)
    account = CreditAccount.objects.select_for_update().get(pk=reservation_ref.account_id)
    reservation = CreditReservation.objects.select_for_update().get(pk=reservation.pk)
    if reservation.status in {'settled', 'released', 'cancelled', 'expired'}:
        return 0
    if reservation.status != 'reserved':
        raise CreditLedgerError(f'预占状态 {reservation.status} 不能释放')
    now = timezone.now()
    released = 0
    for allocation in CreditReservationAllocation.objects.select_for_update().filter(
        reservation=reservation,
    ):
        amount = max(
            0,
            allocation.reserved_amount - allocation.consumed_amount - allocation.released_amount,
        )
        if not amount:
            continue
        batch = CreditGrantBatch.objects.select_for_update().get(pk=allocation.batch_id)
        if batch.reserved_amount < amount:
            raise CreditLedgerError('积分批次预占余额不一致')
        batch.reserved_amount -= amount
        if batch.expires_at is None or batch.expires_at > now:
            batch.remaining_amount += amount
            account.balance += amount
            released += amount
        batch.save(update_fields=['remaining_amount', 'reserved_amount', 'updated_at'])
        allocation.released_amount += amount
        allocation.save(update_fields=['released_amount', 'updated_at'])
    account.save(update_fields=['balance', 'updated_at'])
    reservation.status = status
    reservation.failure_reason = reason[:255]
    reservation.save(update_fields=['status', 'failure_reason', 'updated_at'])
    return released


def release_task_reservation(task, *, status='released', reason='') -> int:
    from core.models_billing import CreditReservation

    reservation = CreditReservation.objects.filter(task=task, status='reserved').first()
    if not reservation:
        return 0
    return release_reservation(reservation, status=status, reason=reason)


@transaction.atomic
def redeem_credit_code(user, code_str: str):
    from core.models_billing import RechargeCode
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.select_for_update().get(pk=user.pk)
    code = RechargeCode.objects.select_for_update().filter(code=code_str).first()
    if code is None:
        raise CreditLedgerError('code_not_found')
    if not code.is_valid():
        raise CreditLedgerError('code_invalid')
    if code.code_type != 'CREDIT':
        raise CreditLedgerError('plan_code_not_available')
    if code.credits <= 0:
        raise CreditLedgerError('兑换码积分必须大于 0')

    txn = grant_batch_credits(
        user,
        code.credits,
        batch_type='PURCHASED',
        batch_key=f'recharge-code:{code.pk}',
        note=f'兑换码 {code.code}',
        operator=user,
        txn_type='recharge',
    )
    code.is_used = True
    code.used_by = user
    code.used_at = timezone.now()
    code.save(update_fields=['is_used', 'used_by', 'used_at'])
    return txn


def account_reconciliation(account) -> dict:
    from core.models_billing import CreditGrantBatch

    now = timezone.now()
    available = CreditGrantBatch.objects.filter(
        account=account,
    ).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now),
    ).aggregate(total=Sum('remaining_amount'))['total'] or 0
    reserved = CreditGrantBatch.objects.filter(account=account).aggregate(
        total=Sum('reserved_amount'),
    )['total'] or 0
    return {
        'account_id': account.pk,
        'user_id': account.user_id,
        'balance': account.balance,
        'batch_available': available,
        'reserved': reserved,
        'difference': account.balance - available,
    }
