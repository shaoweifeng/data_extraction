"""
阶段二：计费服务层（纯函数，本阶段只写不接入扣费）

提供：
  - get_or_create_account(user)        : 获取/创建 CreditAccount
  - get_balance(user)                  : 查询余额
  - estimate_credits(ref_count)        : 预估所需 credits
  - tokens_to_credits(total_tokens)    : token 折算 credits
  - grant_credits(user, amount, note)  : 赠送/充值（管理员调额）
  - consume_credits(user, amount, task, note) : 扣费（阶段三接入）
  - refund_credits(user, amount, task, note)  : 退款（阶段三接入）

阶段三前，consume_credits/refund_credits 均为空操作，调用方不用判断阶段。
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


@transaction.atomic
def consume_credits(user, amount: int, task=None, note: str = '') -> Optional['CreditTransaction']:
    """
    扣费（阶段三接入，阶段二为空操作，直接返回 None）。

    阶段三开启时：取消注释并实现余额校验 + 扣减逻辑。
    """
    # ── 阶段三激活后在此实现 ─────────────────────────────────────────────
    # CreditAccount, CreditTransaction, _ = _get_models()
    # account = CreditAccount.objects.select_for_update().get(user=user)
    # if account.balance < amount:
    #     raise ValueError(f"余额不足（需 {amount}，现有 {account.balance}）")
    # account.balance = F('balance') - amount
    # account.total_consumed = F('total_consumed') + amount
    # account.save(update_fields=['balance', 'total_consumed', 'updated_at'])
    # account.refresh_from_db()
    # return CreditTransaction.objects.create(
    #     account=account, txn_type='consume', amount=-amount,
    #     balance_after=account.balance, task=task, note=note,
    # )
    # ────────────────────────────────────────────────────────────────────
    return None   # 阶段二：空操作


@transaction.atomic
def refund_credits(user, amount: int, task=None, note: str = '') -> Optional['CreditTransaction']:
    """
    退款/多退少补（阶段三接入，阶段二为空操作，直接返回 None）。
    """
    # ── 阶段三激活后在此实现 ─────────────────────────────────────────────
    # CreditAccount, CreditTransaction, _ = _get_models()
    # account = CreditAccount.objects.select_for_update().get(user=user)
    # account.balance = F('balance') + amount
    # account.save(update_fields=['balance', 'updated_at'])
    # account.refresh_from_db()
    # return CreditTransaction.objects.create(
    #     account=account, txn_type='refund', amount=amount,
    #     balance_after=account.balance, task=task, note=note,
    # )
    # ────────────────────────────────────────────────────────────────────
    return None   # 阶段二：空操作
