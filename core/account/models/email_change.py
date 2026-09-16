from django.conf import settings
from django.db import models


class AccountEmailChangeRequest(models.Model):
    """Pending verified-email replacement; the current trusted email stays active."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='account_email_change_requests',
        verbose_name='用户',
    )
    new_email = models.EmailField(max_length=254, verbose_name='新邮箱')
    normalized_new_email = models.CharField(
        max_length=254,
        db_index=True,
        verbose_name='规范化新邮箱',
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
        db_table = 'plat_accountemailchangerequest'
        verbose_name = '邮箱变更请求'
        verbose_name_plural = '邮箱变更请求'
        indexes = [
            models.Index(fields=['user', '-created_at'], name='acct_emailchg_user_idx'),
            models.Index(fields=['expires_at'], name='acct_emailchg_expiry_idx'),
        ]

    def __str__(self):
        return f'{self.user_id}:{self.new_email}:{self.created_at:%Y-%m-%d %H:%M}'
