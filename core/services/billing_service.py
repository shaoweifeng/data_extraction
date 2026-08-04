"""
计费服务层（纯函数）

提供：
  - get_or_create_account(user)                : 获取/创建 CreditAccount
  - get_balance(user)                          : 查询余额
  - estimate_credits(ref_count)               : 预估所需 credits
  - tokens_to_credits(total_tokens)           : token 折算 credits
  - grant_credits(user, amount, note)          : 赠送/充值（管理员调额）
  - check_balance_sufficient(user, amount)     : 余额是否满足预估需求
  - consume_credits(user, amount, task, note)  : 按实际 token 扣费（原子操作）
  - refund_credits(user, amount, task, note)   : 退款/补偿（原子操作）
  - log_admin_usage(user, credits_equivalent, task, note) : 管理员用量审计记录（不扣费）
"""

from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

from django.db import transaction
from django.db.models import F
from django.conf import settings

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


# ============================================================================
# 内部辅助
# ============================================================================

def _get_models():
    """延迟 import，避免 AppRegistry 未就绪时的 circular import。"""
    from core.models_billing import CreditAccount, CreditTransaction, TokenUsageLog
    return CreditAccount, CreditTransaction, TokenUsageLog


# ============================================================================
# 账户操作
# ============================================================================

def get_or_create_account(user) -> 'CreditAccount':
    """获取 CreditAccount，若不存在则创建（正常情况下信号已创建）。"""
    CreditAccount, _, _ = _get_models()
    free = getattr(settings, 'BILLING_FREE_CREDITS_ON_REGISTER', 200)
    account, created = CreditAccount.objects.get_or_create(
        user=user,
        defaults={'balance': free, 'total_granted': free},
    )
    if created:
        logger.warning(f"[billing] 用户 {user.username} 缺少 CreditAccount，已补建（{free} credits）")
    return account


def get_balance(user) -> int:
    """查询用户当前余额（credits）。"""
    CreditAccount, _, _ = _get_models()
    try:
        return CreditAccount.objects.get(user=user).balance
    except CreditAccount.DoesNotExist:
        return get_or_create_account(user).balance


# ============================================================================
# 估算工具
# ============================================================================

def tokens_to_credits(total_tokens: int) -> int:
    """
    将 token 数折算为 credits。
    1 credit = settings.BILLING_CREDIT_TOKEN_RATIO tokens，最低 1。
    """
    ratio = getattr(settings, 'BILLING_CREDIT_TOKEN_RATIO', 1000)
    return max(1, total_tokens // ratio)


def estimate_credits(ref_count: int) -> int:
    """
    预估筛选 N 篇文献所需的 credits（用于阶段三余额校验）。
    单篇均值由 settings.BILLING_ESTIMATE_CREDITS_PER_REF 控制（默认 2）。
    """
    per_ref = getattr(settings, 'BILLING_ESTIMATE_CREDITS_PER_REF', 2)
    return max(1, ref_count * per_ref)


# ============================================================================
# 额度变更（原子操作，使用 select_for_update 防并发竞态）
# ============================================================================

@transaction.atomic
def grant_credits(user, amount: int, note: str = '', operator=None) -> 'CreditTransaction':
    """
    赠送/充值/管理员调额（正数加，负数减）。
    txn_type 根据 amount 和调用场景自动选择：
      - amount > 0 且 operator 为 None → 'grant'（系统赠送）
      - amount > 0 且 operator 非空  → 'recharge'（充值/调额）
      - amount < 0                    → 'adjust'（管理员扣减）
    """
    CreditAccount, CreditTransaction, _ = _get_models()

    account = CreditAccount.objects.select_for_update().get(user=user)
    account.balance = F('balance') + amount
    if amount > 0:
        account.total_granted = F('total_granted') + amount
    account.save(update_fields=['balance', 'total_granted', 'updated_at'])
    account.refresh_from_db()

    if amount > 0:
        txn_type = 'grant' if operator is None else 'recharge'
    else:
        txn_type = 'adjust'

    txn = CreditTransaction.objects.create(
        account=account,
        txn_type=txn_type,
        amount=amount,
        balance_after=account.balance,
        note=note or ('注册赠送' if txn_type == 'grant' else ''),
        created_by=operator,
    )
    logger.info(f"[billing] grant {user.username} {amount:+d} credits → 余额 {account.balance}")
    return txn


def check_balance_sufficient(user, required: int) -> bool:
    """快速检查余额是否 >= required credits（不加锁，仅预检）。"""
    return get_balance(user) >= required


@transaction.atomic
def consume_credits(user, amount: int, task=None, note: str = '') -> Optional['CreditTransaction']:
    """
    按实际 token 用量扣减 credits（原子操作，select_for_update 防并发竞态）。

    Args:
        user:   操作用户
        amount: 扣减 credits 数（正整数）
        task:   关联的 Task 对象（可空）
        note:   备注

    Returns:
        创建的 CreditTransaction，若 amount<=0 则跳过返回 None

    Raises:
        ValueError: 余额不足
    """
    if amount <= 0:
        return None

    CreditAccount, CreditTransaction, _ = _get_models()
    account = CreditAccount.objects.select_for_update().get(user=user)

    if account.balance < amount:
        raise ValueError(f"余额不足（需 {amount}，现有 {account.balance} credits）")

    account.balance = F('balance') - amount
    account.total_consumed = F('total_consumed') + amount
    account.save(update_fields=['balance', 'total_consumed', 'updated_at'])
    account.refresh_from_db()

    txn = CreditTransaction.objects.create(
        account=account,
        txn_type='consume',
        amount=-amount,
        balance_after=account.balance,
        task=task,
        note=note or 'AI筛选扣费',
    )
    logger.info(f"[billing] consume {user.username} -{amount} credits → 余额 {account.balance}")
    return txn


@transaction.atomic
def refund_credits(user, amount: int, task=None, note: str = '') -> Optional['CreditTransaction']:
    """
    退款/多退少补（原子操作）。

    Args:
        user:   操作用户
        amount: 退还 credits 数（正整数）
        task:   关联的 Task 对象（可空）
        note:   备注

    Returns:
        创建的 CreditTransaction，若 amount<=0 则跳过返回 None
    """
    if amount <= 0:
        return None

    CreditAccount, CreditTransaction, _ = _get_models()
    account = CreditAccount.objects.select_for_update().get(user=user)
    account.balance = F('balance') + amount
    account.save(update_fields=['balance', 'updated_at'])
    account.refresh_from_db()

    txn = CreditTransaction.objects.create(
        account=account,
        txn_type='refund',
        amount=amount,
        balance_after=account.balance,
        task=task,
        note=note or 'AI筛选退款',
    )
    logger.info(f"[billing] refund {user.username} +{amount} credits → 余额 {account.balance}")
    return txn


def log_admin_usage(user, credits_equivalent: int, task=None, note: str = '') -> Optional['CreditTransaction']:
    """
    管理员筛选用量审计记录（不扣费，amount=0，仅写流水供统计/审计使用）。

    Args:
        user:               管理员用户
        credits_equivalent: 折算后的 credits 等值（不实际扣除）
        task:               关联的 Task 对象（可空）
        note:               备注

    Returns:
        创建的 CreditTransaction（txn_type='admin_usage'，amount=0）
        若账户不存在则静默失败返回 None
    """
    if credits_equivalent <= 0:
        return None

    CreditAccount, CreditTransaction, _ = _get_models()
    try:
        account = get_or_create_account(user)
        txn = CreditTransaction.objects.create(
            account=account,
            txn_type='admin_usage',
            amount=0,                          # 不扣费
            balance_after=account.balance,     # 余额不变
            task=task,
            note=note or f'管理员用量记录（≈{credits_equivalent} credits 等值）',
        )
        logger.info(
            f"[billing] admin_usage {user.username} ≈{credits_equivalent} credits"
            f"（不扣费，余额维持 {account.balance}）"
        )
        return txn
    except Exception as e:
        logger.warning(f"[billing] log_admin_usage 写入失败: {e}")
        return None
