from django.conf import settings
from django.db import models

from ..email import normalize_email_address


class AccountEmail(models.Model):
    """A user's canonical email identity; verification is added in phase 2."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='account_email',
        verbose_name='用户',
    )
    email = models.EmailField(max_length=254, verbose_name='邮箱')
    normalized_email = models.CharField(
        max_length=254,
        unique=True,
        verbose_name='规范化邮箱',
    )
    verified_at = models.DateTimeField(null=True, blank=True, verbose_name='验证时间')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'plat_accountemail'
        verbose_name = '可信邮箱'
        verbose_name_plural = '可信邮箱'

    def __str__(self):
        status = '已验证' if self.verified_at else '未验证'
        return f'{self.email}（{status}）'

    def save(self, *args, **kwargs):
        normalized = normalize_email_address(self.email)
        self.email = normalized
        self.normalized_email = normalized
        update_fields = kwargs.get('update_fields')
        if update_fields is not None and 'email' in update_fields:
            kwargs['update_fields'] = set(update_fields) | {'normalized_email'}
        return super().save(*args, **kwargs)
