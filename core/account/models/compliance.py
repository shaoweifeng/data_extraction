from django.conf import settings
from django.db import models


class LegalDocumentType(models.TextChoices):
    TERMS = 'terms', '服务协议'
    PRIVACY = 'privacy', '隐私政策'


class AgreementAcceptance(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='agreement_acceptances',
        verbose_name='用户',
    )
    document_type = models.CharField(max_length=16, choices=LegalDocumentType.choices)
    version = models.CharField(max_length=32, verbose_name='版本')
    content_sha256 = models.CharField(max_length=64, verbose_name='内容摘要')
    ip_hash = models.CharField(max_length=64, blank=True, verbose_name='IP 摘要')
    user_agent_hash = models.CharField(max_length=64, blank=True, verbose_name='User-Agent 摘要')
    accepted_at = models.DateTimeField(auto_now_add=True, verbose_name='接受时间')

    class Meta:
        db_table = 'plat_agreement_acceptance'
        verbose_name = '协议接受记录'
        verbose_name_plural = '协议接受记录'
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'document_type', 'version'],
                name='account_agreement_acceptance_uniq',
            ),
        ]
        indexes = [models.Index(
            fields=['document_type', 'version', '-accepted_at'],
            name='account_ag_documen_1e2dbf_idx',
        )]


class AccountSecurityEvent(models.Model):
    event_type = models.CharField(max_length=48, db_index=True, verbose_name='事件类型')
    outcome = models.CharField(max_length=16, db_index=True, verbose_name='结果')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='account_security_events',
        verbose_name='用户',
    )
    user_id_snapshot = models.PositiveBigIntegerField(null=True, blank=True)
    identifier_hash = models.CharField(max_length=64, blank=True, db_index=True)
    ip_masked = models.CharField(max_length=64, blank=True, verbose_name='脱敏 IP')
    ip_hash = models.CharField(max_length=64, blank=True, db_index=True)
    user_agent_hash = models.CharField(max_length=64, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'plat_account_security_event'
        verbose_name = '账户安全事件'
        verbose_name_plural = '账户安全事件'
        indexes = [models.Index(
            fields=['event_type', 'outcome', '-created_at'],
            name='account_acc_event_t_8fe639_idx',
        )]


class AccountAdminAuditEvent(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='account_admin_actions',
        verbose_name='管理员',
    )
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='account_admin_audit_events',
        verbose_name='目标用户',
    )
    target_user_id_snapshot = models.PositiveBigIntegerField(null=True, blank=True)
    target_username_snapshot = models.CharField(max_length=150, blank=True)
    action = models.CharField(max_length=48, db_index=True, verbose_name='操作')
    reason = models.CharField(max_length=500, blank=True, verbose_name='原因')
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    ip_hash = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'plat_account_admin_audit_event'
        verbose_name = '账户管理审计'
        verbose_name_plural = '账户管理审计'
        indexes = [models.Index(
            fields=['action', '-created_at'], name='account_acc_action_577ece_idx',
        )]
