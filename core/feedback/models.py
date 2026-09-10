import os
import uuid

from django.conf import settings
from django.db import models

from .storage import feedback_storage


def feedback_attachment_path(instance, filename):
    extension = os.path.splitext(filename)[1].lower()
    return f'{instance.feedback.reporter_user_id}/{instance.feedback_id}/{instance.id}{extension}'


class UserFeedback(models.Model):
    CATEGORY_CHOICES = [
        ('problem', '遇到问题'),
        ('suggestion', '改进建议'),
    ]
    STATUS_CHOICES = [
        ('new', '待处理'),
        ('reviewing', '处理中'),
        ('resolved', '已解决'),
        ('rejected', '无效'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    display_code = models.CharField(max_length=40, unique=True, editable=False, verbose_name='反馈编号')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='feedback_items',
        verbose_name='提交用户',
    )
    reporter_user_id = models.PositiveBigIntegerField(verbose_name='提交用户ID快照')
    reporter_username = models.CharField(max_length=150, verbose_name='提交用户名快照')
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, verbose_name='反馈类型')
    content = models.TextField(verbose_name='反馈内容')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new', verbose_name='状态')
    project = models.ForeignKey(
        'core.Project',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='feedback_items',
        verbose_name='关联项目',
    )
    page_path = models.CharField(max_length=500, blank=True, verbose_name='页面路径')
    route_name = models.CharField(max_length=100, blank=True, verbose_name='路由名称')
    client_request_id = models.UUIDField(verbose_name='客户端幂等ID')
    context = models.JSONField(default=dict, blank=True, verbose_name='技术上下文')
    admin_note = models.TextField(blank=True, verbose_name='管理员备注')
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='resolved_feedback_items',
        verbose_name='处理人',
    )
    resolved_at = models.DateTimeField(null=True, blank=True, verbose_name='处理时间')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='提交时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'plat_user_feedback'
        verbose_name = '用户反馈'
        verbose_name_plural = '用户反馈'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['reporter_user_id', 'client_request_id'],
                name='feedback_user_request_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['user', 'created_at'], name='feedback_user_created_idx'),
            models.Index(fields=['status', 'created_at'], name='feedback_status_created_idx'),
        ]

    def save(self, *args, **kwargs):
        if not self.display_code:
            self.display_code = f'FB-{self.id.hex.upper()}'
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.display_code} - {self.get_category_display()}'


class FeedbackAttachment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    feedback = models.ForeignKey(
        UserFeedback,
        on_delete=models.CASCADE,
        related_name='attachments',
        verbose_name='反馈',
    )
    file = models.FileField(storage=feedback_storage, upload_to=feedback_attachment_path, verbose_name='图片')
    original_name = models.CharField(max_length=255, verbose_name='原始文件名')
    mime_type = models.CharField(max_length=50, verbose_name='MIME类型')
    file_size = models.PositiveBigIntegerField(verbose_name='文件大小')
    sha256 = models.CharField(max_length=64, verbose_name='SHA-256')
    width = models.PositiveIntegerField(verbose_name='宽度')
    height = models.PositiveIntegerField(verbose_name='高度')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='上传时间')

    class Meta:
        db_table = 'plat_feedback_attachment'
        verbose_name = '反馈图片'
        verbose_name_plural = '反馈图片'
        ordering = ['created_at']

    def __str__(self):
        return self.original_name


class FeedbackDailyQuota(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='feedback_daily_quotas',
        verbose_name='用户',
    )
    quota_date = models.DateField(verbose_name='配额日期')
    used_count = models.PositiveIntegerField(default=0, verbose_name='已使用次数')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'plat_feedback_daily_quota'
        verbose_name = '反馈每日配额'
        verbose_name_plural = '反馈每日配额'
        constraints = [
            models.UniqueConstraint(fields=['user', 'quota_date'], name='feedback_daily_quota_uniq'),
        ]

    def __str__(self):
        return f'{self.user_id} / {self.quota_date}: {self.used_count}'
