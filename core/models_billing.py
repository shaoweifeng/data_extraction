"""
阶段二：额度账户与计费基建

数据模型：
  User 1—1 CreditAccount 1—* CreditTransaction
  Task 1—* TokenUsageLog

表均以 plat_ 前缀命名，与 core app 其他表保持一致。
"""

from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings


# ============================================================================
# 额度账户
# ============================================================================

class CreditAccount(models.Model):
    """用户额度账户（1:1 User）"""

    user = models.OneToOneField(
        User, on_delete=models.CASCADE,
        related_name='credit_account', verbose_name="用户",
    )
    balance = models.IntegerField(default=0, verbose_name="当前余额(credits)")
    total_granted = models.IntegerField(default=0, verbose_name="累计赠送(credits)")
    total_consumed = models.IntegerField(default=0, verbose_name="累计消耗(credits)")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = 'plat_creditaccount'
        verbose_name = "额度账户"
        verbose_name_plural = "额度账户"

    def __str__(self):
        return f"{self.user.username} | 余额 {self.balance} credits"


# ============================================================================
# 额度流水
# ============================================================================

class CreditTransaction(models.Model):
    """额度流水（每次充值/赠送/扣费/退款各一条）"""

    TXN_TYPE_CHOICES = [
        ('grant',    '赠送'),        # 注册赠送 / 管理员充值
        ('recharge', '充值'),        # 兑换码充值（阶段六）
        ('consume',  '消耗'),        # AI 筛选预扣（阶段三）
        ('refund',   '退款'),        # 多退少补退差额（阶段三）
        ('adjust',   '管理员调整'),  # 管理员手动加减
    ]

    account = models.ForeignKey(
        CreditAccount, on_delete=models.CASCADE,
        related_name='transactions', verbose_name="账户",
    )
    txn_type = models.CharField(
        max_length=20, choices=TXN_TYPE_CHOICES, verbose_name="类型",
    )
    amount = models.IntegerField(verbose_name="金额(credits, 正=加/负=减)")
    balance_after = models.IntegerField(verbose_name="操作后余额")
    # 关联任务（AI 筛选消耗/退款时填写，赠送/充值时为空）
    task = models.ForeignKey(
        'core.Task', null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='credit_transactions', verbose_name="关联任务",
    )
    note = models.CharField(max_length=255, blank=True, verbose_name="备注")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    created_by = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='credit_ops', verbose_name="操作人",
    )

    class Meta:
        db_table = 'plat_credittransaction'
        verbose_name = "额度流水"
        verbose_name_plural = "额度流水"
        ordering = ['-created_at']

    def __str__(self):
        sign = '+' if self.amount >= 0 else ''
        return f"{self.account.user.username} {self.get_txn_type_display()} {sign}{self.amount}"


# ============================================================================
# Token 用量日志（旁路记录，不影响筛选主流程）
# ============================================================================

class TokenUsageLog(models.Model):
    """每次 AI API 调用的 token 用量明细"""

    task = models.ForeignKey(
        'core.Task', on_delete=models.CASCADE,
        related_name='token_logs', verbose_name="任务",
    )
    user = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='token_logs', verbose_name="用户",
    )
    model = models.CharField(max_length=100, verbose_name="模型名称")
    prompt_tokens = models.IntegerField(default=0, verbose_name="输入 tokens")
    completion_tokens = models.IntegerField(default=0, verbose_name="输出 tokens")
    total_tokens = models.IntegerField(default=0, verbose_name="总 tokens")
    # 1 credit = CREDIT_TOKEN_RATIO tokens（settings 里配置，此处冗余存快照）
    credits_consumed = models.IntegerField(default=0, verbose_name="折算 credits")
    ref_count = models.IntegerField(default=1, verbose_name="本次处理文献篇数")
    # 阶段三接入计费后，这里记录对应的 CreditTransaction；阶段二为 null
    transaction = models.ForeignKey(
        CreditTransaction, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='token_logs', verbose_name="对应流水",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        db_table = 'plat_tokenusagelog'
        verbose_name = "Token 用量日志"
        verbose_name_plural = "Token 用量日志"
        ordering = ['-created_at']

    def __str__(self):
        return f"Task#{self.task_id} {self.model} {self.total_tokens}tokens"


# ============================================================================
# 信号：User 创建时自动建 CreditAccount 并赠送免费额度
# ============================================================================

@receiver(post_save, sender=User)
def ensure_credit_account(sender, instance, created, **kwargs):
    """
    User 创建时自动建立 CreditAccount，并写入注册赠送流水。
    赠送额度由 settings.BILLING_FREE_CREDITS_ON_REGISTER 控制（默认 200）。
    使用 get_or_create 防止重复触发。
    """
    if not created:
        return

    free_credits = getattr(settings, 'BILLING_FREE_CREDITS_ON_REGISTER', 200)

    account, account_created = CreditAccount.objects.get_or_create(
        user=instance,
        defaults={
            'balance': free_credits,
            'total_granted': free_credits,
        },
    )

    if account_created and free_credits > 0:
        CreditTransaction.objects.create(
            account=account,
            txn_type='grant',
            amount=free_credits,
            balance_after=free_credits,
            note='注册赠送',
        )
