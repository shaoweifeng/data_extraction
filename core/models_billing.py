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
        ('grant',       '赠送'),         # 注册赠送 / 管理员充值
        ('recharge',    '充值'),         # 兑换码充值
        ('consume',     '消耗'),         # AI 筛选实际用量扣费
        ('refund',      '退款'),         # 多退少补退差额
        ('adjust',      '管理员调整'),   # 管理员手动加减
        ('expire',      '到期'),         # 批次到期扣减可用余额
        ('admin_usage', '管理员用量'),   # 管理员筛选用量记录（不扣费，仅审计）
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
    idempotency_key = models.CharField(
        max_length=128,
        null=True,
        blank=True,
        unique=True,
        verbose_name="业务幂等键",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    created_by = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='credit_ops', verbose_name="操作人",
    )
    reverses_transaction = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.PROTECT,
        related_name='refund_transactions', verbose_name="原消费流水",
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
        'core.Task', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='token_logs', verbose_name="任务",
    )
    project = models.ForeignKey(
        'core.Project', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='token_logs', verbose_name="项目",
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
    usage_breakdown = models.JSONField(default=dict, blank=True, verbose_name="分模型用量")
    pricing_version = models.CharField(max_length=50, blank=True, default='', verbose_name="影子计费版本")
    shadow_credits = models.IntegerField(null=True, blank=True, verbose_name="影子积分")
    estimated_cost_cny = models.DecimalField(
        max_digits=12, decimal_places=6, null=True, blank=True, verbose_name="估算成本（元）",
    )
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
# 信号：User 创建时只兜底建立零余额 CreditAccount
# ============================================================================

@receiver(post_save, sender=User)
def ensure_credit_account(sender, instance, created, **kwargs):
    """
    User 创建时兜底建立零余额 CreditAccount。

    任何有经济价值的赠送必须由显式业务 Service 完成，不能放在信号里。
    """
    if not created:
        return

    CreditAccount.objects.get_or_create(
        user=instance,
        defaults={
            'balance': 0,
            'total_granted': 0,
        },
    )


# ============================================================================
# 兑换码（阶段六）
# ============================================================================

class RechargeCode(models.Model):
    """
    积分或套餐兑换码（由管理员在 Django Admin 后台创建）。

    兑换流程：
      用户提交码 → 校验有效性（存在、未使用、未过期）
                → 原子发放积分批次或开通套餐权益
                → 写入交易、权益及审计记录
                → 标记 is_used=True
    """
    code       = models.CharField(max_length=32, unique=True, verbose_name="兑换码")
    credits    = models.IntegerField(verbose_name="面值(credits)")
    code_type  = models.CharField(
        max_length=16,
        choices=[('CREDIT', '积分码'), ('PLAN', '套餐码')],
        default='CREDIT',
        verbose_name="兑换码类型",
    )
    plan_price_version = models.ForeignKey(
        'PlanPriceVersion', null=True, blank=True,
        on_delete=models.PROTECT,
        related_name='recharge_codes', verbose_name="套餐价格版本",
    )
    valid_months = models.PositiveSmallIntegerField(default=1, verbose_name="套餐有效月数")
    batch_no = models.CharField(max_length=64, blank=True, default='', verbose_name="发行批次")
    is_used    = models.BooleanField(default=False, verbose_name="是否已使用")
    used_by    = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='recharge_codes_used', verbose_name="使用者",
    )
    used_at    = models.DateTimeField(null=True, blank=True, verbose_name="使用时间")
    created_by = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='recharge_codes_created', verbose_name="创建者",
    )
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name="过期时间（null=永不过期）")
    note       = models.CharField(max_length=255, blank=True, default='', verbose_name="备注")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        db_table        = 'plat_rechargecode'
        verbose_name    = "兑换码"
        verbose_name_plural = "兑换码"
        ordering        = ['-created_at']

    def __str__(self):
        if not self.is_used:
            status_str = "未使用"
        elif self.used_by_id and self.used_by:
            status_str = f"已被 {self.used_by.username} 使用"
        else:
            status_str = "已使用（原用户已删除）"
        if self.code_type == 'PLAN' and self.plan_price_version_id:
            value = f"{self.plan_price_version.plan.name} × {self.valid_months}个月"
        else:
            value = f"{self.credits} credits"
        return f"{self.code} | {value} | {status_str}"

    def is_valid(self) -> bool:
        """快速检查码是否可用（未使用且未过期）。"""
        from django.utils import timezone
        if self.is_used:
            return False
        if self.expires_at and self.expires_at < timezone.now():
            return False
        return True

    def clean(self):
        from django.core.exceptions import ValidationError

        errors = {}
        if self.code_type == 'CREDIT':
            if self.credits <= 0:
                errors['credits'] = '积分码面值必须大于 0。'
            if self.plan_price_version_id:
                errors['plan_price_version'] = '积分码不能关联套餐版本。'
        elif self.code_type == 'PLAN':
            if not self.plan_price_version_id:
                errors['plan_price_version'] = '套餐码必须选择套餐价格版本。'
            elif self.plan_price_version.status != 'published':
                errors['plan_price_version'] = '套餐码只能关联已发布的套餐版本。'
            if self.valid_months <= 0:
                errors['valid_months'] = '套餐有效月数必须大于 0。'
        if errors:
            raise ValidationError(errors)


# ============================================================================
# 套餐、积分批次与版本化模型计费（阶段 1～3：只建模和影子计算）
# ============================================================================

class PlanCatalog(models.Model):
    """稳定套餐标识；价格和权益由不可变的价格版本承载。"""

    code = models.CharField(max_length=32, unique=True, verbose_name="套餐代码")
    name = models.CharField(max_length=64, verbose_name="套餐名称")
    description = models.CharField(max_length=255, blank=True, default='', verbose_name="说明")
    is_active = models.BooleanField(default=True, verbose_name="是否可用")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = 'plat_plan_catalog'
        verbose_name = "套餐目录"
        verbose_name_plural = "套餐目录"
        ordering = ['code']

    def __str__(self):
        return f'{self.name} ({self.code})'


class PlanPriceVersion(models.Model):
    """套餐价格与权益快照；发布后不得原地覆盖历史版本。"""

    STATUS_CHOICES = [('draft', '草稿'), ('published', '已发布'), ('retired', '已停用')]

    plan = models.ForeignKey(
        PlanCatalog, on_delete=models.PROTECT,
        related_name='price_versions', verbose_name="套餐",
    )
    version = models.CharField(max_length=48, verbose_name="版本")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='draft', db_index=True)
    monthly_price_cny = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="月价（元）")
    valid_months = models.PositiveSmallIntegerField(default=1, verbose_name="有效月数")
    included_credits = models.PositiveIntegerField(verbose_name="每周期积分")
    ai_call_slots = models.PositiveSmallIntegerField(verbose_name="用户聚合 AI 调用槽位")
    project_limit = models.PositiveIntegerField(verbose_name="项目上限")
    effective_from = models.DateTimeField(null=True, blank=True, verbose_name="生效时间")
    effective_until = models.DateTimeField(null=True, blank=True, verbose_name="失效时间")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        db_table = 'plat_plan_price_version'
        verbose_name = "套餐价格版本"
        verbose_name_plural = "套餐价格版本"
        constraints = [
            models.UniqueConstraint(fields=['plan', 'version'], name='uniq_plan_price_version'),
        ]

    def __str__(self):
        return f'{self.plan.code}/{self.version}'


class UserPlanEntitlement(models.Model):
    """用户套餐权益周期；阶段 1 仅审计，不参与当前权限判断。"""

    STATUS_CHOICES = [
        ('scheduled', '待生效'), ('active', '生效中'),
        ('expired', '已到期'), ('cancelled', '已取消'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='plan_entitlements')
    price_version = models.ForeignKey(
        PlanPriceVersion, on_delete=models.PROTECT, related_name='entitlements',
    )
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='scheduled', db_index=True)
    starts_at = models.DateTimeField(verbose_name="开始时间")
    expires_at = models.DateTimeField(verbose_name="到期时间")
    source_recharge_code = models.ForeignKey(
        RechargeCode, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='plan_entitlements', verbose_name="来源兑换码",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'plat_user_plan_entitlement'
        verbose_name = "用户套餐权益"
        verbose_name_plural = "用户套餐权益"
        indexes = [models.Index(fields=['user', 'status', 'expires_at'], name='idx_ent_user_status_exp')]


class PlanBillingPeriod(models.Model):
    """套餐的单个月度周期，作为积分发放的幂等边界。"""

    entitlement = models.ForeignKey(
        UserPlanEntitlement, on_delete=models.CASCADE, related_name='billing_periods',
    )
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    grant_status = models.CharField(
        max_length=16,
        choices=[('pending', '待发放'), ('granted', '已发放'), ('expired', '已到期')],
        default='pending', db_index=True,
    )
    grant_batch = models.OneToOneField(
        'CreditGrantBatch', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='billing_period',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'plat_plan_billing_period'
        verbose_name = "套餐账期"
        verbose_name_plural = "套餐账期"
        constraints = [
            models.UniqueConstraint(
                fields=['entitlement', 'period_start'], name='uniq_entitlement_period_start',
            ),
        ]


class CreditGrantBatch(models.Model):
    """带来源与有效期的积分批次；阶段 4 才接管实际余额。"""

    TYPE_CHOICES = [
        ('WELCOME', '注册赠送'), ('PLAN', '套餐积分'),
        ('PURCHASED', '购买积分'), ('PROMOTION', '活动赠送'),
        ('COMPENSATION', '补偿积分'), ('LEGACY', '存量迁移'),
    ]

    account = models.ForeignKey(CreditAccount, on_delete=models.CASCADE, related_name='grant_batches')
    batch_type = models.CharField(max_length=20, choices=TYPE_CHOICES, db_index=True)
    batch_key = models.CharField(max_length=160, unique=True, verbose_name="批次幂等键")
    granted_amount = models.PositiveIntegerField(verbose_name="发放积分")
    remaining_amount = models.PositiveIntegerField(verbose_name="剩余积分")
    reserved_amount = models.PositiveIntegerField(default=0, verbose_name="预占积分")
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    entitlement = models.ForeignKey(
        UserPlanEntitlement, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='credit_batches',
    )
    grant_transaction = models.OneToOneField(
        CreditTransaction, null=True, blank=True, on_delete=models.PROTECT,
        related_name='grant_batch', verbose_name="发放流水",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'plat_credit_grant_batch'
        verbose_name = "积分批次"
        verbose_name_plural = "积分批次"
        indexes = [models.Index(fields=['account', 'expires_at'], name='idx_batch_account_exp')]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(remaining_amount__lte=models.F('granted_amount')),
                name='credit_batch_remaining_lte_granted',
            ),
        ]


class CreditAllocation(models.Model):
    """一笔总账流水在积分批次上的分摊。"""

    transaction = models.ForeignKey(
        CreditTransaction, on_delete=models.CASCADE, related_name='allocations',
    )
    batch = models.ForeignKey(CreditGrantBatch, on_delete=models.PROTECT, related_name='allocations')
    allocation_type = models.CharField(
        max_length=16,
        choices=[('consume', '消费'), ('refund', '退回'), ('expire', '过期'), ('reserve', '预占')],
    )
    amount = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'plat_credit_allocation'
        verbose_name = "积分分摊"
        verbose_name_plural = "积分分摊"
        constraints = [
            models.UniqueConstraint(
                fields=['transaction', 'batch', 'allocation_type'],
                name='uniq_txn_batch_allocation_type',
            ),
        ]


class ModelBillingRate(models.Model):
    """追加式模型费率；所有金额均为每百万 Token 单价。"""

    STATUS_CHOICES = [('draft', '草稿'), ('published', '已发布'), ('retired', '已停用')]

    rate_key = models.CharField(max_length=160, unique=True, verbose_name="费率唯一键")
    version = models.CharField(max_length=48, db_index=True, verbose_name="费率版本")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='draft', db_index=True)
    provider = models.CharField(max_length=32)
    region = models.CharField(max_length=48, blank=True, default='')
    service_tier = models.CharField(max_length=48, blank=True, default='standard')
    model_id = models.CharField(max_length=100, db_index=True, verbose_name="平台规范模型 ID")
    provider_model = models.CharField(max_length=128, verbose_name="供应商模型 ID")
    context_min_tokens = models.PositiveIntegerField(default=0)
    context_max_tokens = models.PositiveIntegerField(
        default=0, help_text='0 表示不设上限',
    )
    currency = models.CharField(max_length=3, default='CNY')
    fx_cny_per_unit = models.DecimalField(max_digits=12, decimal_places=6, default=1)
    input_cny_per_million = models.DecimalField(max_digits=14, decimal_places=6)
    output_cny_per_million = models.DecimalField(max_digits=14, decimal_places=6)
    cache_read_cny_per_million = models.DecimalField(max_digits=14, decimal_places=6)
    cache_write_cny_per_million = models.DecimalField(max_digits=14, decimal_places=6)
    effective_from = models.DateTimeField(null=True, blank=True)
    effective_until = models.DateTimeField(null=True, blank=True)
    source_url = models.URLField(max_length=500, blank=True, default='')
    notes = models.CharField(max_length=500, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'plat_model_billing_rate'
        verbose_name = "模型计费费率"
        verbose_name_plural = "模型计费费率"
        indexes = [
            models.Index(
                fields=['version', 'model_id', 'status'], name='idx_rate_ver_model_status',
            ),
        ]


class ModelUsageDetail(models.Model):
    """规范化的逐次 Provider 调用用量；任务汇总必须由本表可复算。"""

    usage_log = models.ForeignKey(
        TokenUsageLog, on_delete=models.CASCADE, related_name='call_details',
    )
    task = models.ForeignKey(
        'core.Task', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='model_usage_details',
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='model_usage_details')
    call_index = models.PositiveIntegerField()
    provider = models.CharField(max_length=32)
    region = models.CharField(max_length=48, blank=True, default='')
    service_tier = models.CharField(max_length=48, blank=True, default='standard')
    model_id = models.CharField(max_length=100, db_index=True)
    provider_model = models.CharField(max_length=128, blank=True, default='')
    provider_request_id = models.CharField(max_length=160, blank=True, default='', db_index=True)
    context_tokens = models.PositiveIntegerField(default=0)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cache_read_tokens = models.PositiveIntegerField(default=0)
    cache_write_tokens = models.PositiveIntegerField(default=0)
    attempt_number = models.PositiveSmallIntegerField(default=1)
    attempt_reason = models.CharField(max_length=40, default='initial')
    charge_bearer = models.CharField(
        max_length=16, choices=[('user', '用户'), ('platform', '平台')], default='user',
    )
    rate = models.ForeignKey(
        ModelBillingRate, null=True, blank=True, on_delete=models.PROTECT,
        related_name='usage_details',
    )
    estimated_cost_cny = models.DecimalField(max_digits=14, decimal_places=8, null=True, blank=True)
    raw_credits = models.DecimalField(max_digits=16, decimal_places=6, null=True, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'plat_model_usage_detail'
        verbose_name = "模型调用用量明细"
        verbose_name_plural = "模型调用用量明细"
        constraints = [
            models.UniqueConstraint(fields=['usage_log', 'call_index'], name='uniq_usage_log_call_index'),
        ]


class CreditReservation(models.Model):
    """任务积分预占状态；阶段 5 才参与实际扣费。"""

    STATUS_CHOICES = [
        ('pending', '待确认'), ('reserved', '已预占'), ('settled', '已结算'),
        ('released', '已释放'), ('expired', '已过期'), ('cancelled', '已取消'),
    ]

    account = models.ForeignKey(CreditAccount, on_delete=models.CASCADE, related_name='reservations')
    task = models.ForeignKey(
        'core.Task', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='credit_reservations',
    )
    idempotency_key = models.CharField(max_length=160, unique=True)
    pricing_version = models.CharField(max_length=48)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='pending', db_index=True)
    estimated_credits = models.PositiveIntegerField(default=0)
    reserved_credits = models.PositiveIntegerField(default=0)
    settled_credits = models.PositiveIntegerField(default=0)
    actual_credits = models.PositiveIntegerField(default=0)
    platform_covered_credits = models.PositiveIntegerField(default=0)
    settlement_transaction = models.OneToOneField(
        CreditTransaction, null=True, blank=True, on_delete=models.PROTECT,
        related_name='settled_reservation',
    )
    failure_reason = models.CharField(max_length=255, blank=True, default='')
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'plat_credit_reservation'
        verbose_name = "积分预占"
        verbose_name_plural = "积分预占"
        indexes = [models.Index(fields=['account', 'status'], name='idx_res_account_status')]


class CreditReservationAllocation(models.Model):
    """预占在积分批次上的锁定、消费和释放明细。"""

    reservation = models.ForeignKey(
        CreditReservation, on_delete=models.CASCADE, related_name='batch_allocations',
    )
    batch = models.ForeignKey(
        CreditGrantBatch, on_delete=models.PROTECT, related_name='reservation_allocations',
    )
    reserved_amount = models.PositiveIntegerField(default=0)
    consumed_amount = models.PositiveIntegerField(default=0)
    additional_consumed_amount = models.PositiveIntegerField(default=0)
    released_amount = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'plat_credit_reservation_allocation'
        verbose_name = "积分预占分摊"
        verbose_name_plural = "积分预占分摊"
        constraints = [
            models.UniqueConstraint(
                fields=['reservation', 'batch'], name='uniq_reservation_batch',
            ),
        ]
