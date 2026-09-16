from django.conf import settings
from django.db import models


class VerificationPurpose(models.TextChoices):
    EMAIL_ACTIVATION = 'email_activation', '邮箱激活'
    PASSWORD_RESET = 'password_reset', '密码重置'


class AccountVerificationToken(models.Model):
    """Single-use account token. Only a digest of the secret is persisted."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='account_verification_tokens',
        verbose_name='用户',
    )
    account_email = models.ForeignKey(
        'account.AccountEmail',
        on_delete=models.CASCADE,
        related_name='verification_tokens',
        verbose_name='邮箱身份',
    )
    purpose = models.CharField(
        max_length=32,
        choices=VerificationPurpose.choices,
        default=VerificationPurpose.EMAIL_ACTIVATION,
        verbose_name='用途',
    )
    token_digest = models.CharField(max_length=64, unique=True, verbose_name='Token 摘要')
    expires_at = models.DateTimeField(verbose_name='过期时间')
    used_at = models.DateTimeField(null=True, blank=True, verbose_name='使用时间')
    revoked_at = models.DateTimeField(null=True, blank=True, verbose_name='作废时间')
    sent_at = models.DateTimeField(null=True, blank=True, verbose_name='最近发送时间')
    send_attempts = models.PositiveSmallIntegerField(default=0, verbose_name='发送尝试次数')
    last_error = models.CharField(max_length=255, blank=True, default='', verbose_name='最近发送错误')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        db_table = 'plat_accountverificationtoken'
        verbose_name = '账户验证 Token'
        verbose_name_plural = '账户验证 Token'
        indexes = [
            models.Index(fields=['user', 'purpose', '-created_at'], name='acct_token_user_idx'),
            models.Index(fields=['expires_at'], name='acct_token_expiry_idx'),
        ]

    def __str__(self):
        return f'{self.user_id}:{self.purpose}:{self.created_at:%Y-%m-%d %H:%M}'
