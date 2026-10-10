from pathlib import Path
import uuid

from django.db import models

from .storage import external_image_storage


def external_image_upload_path(instance, filename):
    suffix = Path(filename).suffix.lower()
    day = instance.created_at.date()
    return f'{day:%Y/%m/%d}/{instance.id.hex}{suffix}'


class ExternalImageUpload(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client_request_id = models.UUIDField(unique=True, verbose_name='客户端幂等ID')
    source = models.CharField(max_length=100, blank=True, verbose_name='来源标识')
    file = models.FileField(
        storage=external_image_storage,
        upload_to=external_image_upload_path,
        max_length=500,
        blank=True,
        verbose_name='私有图片',
    )
    original_name = models.CharField(max_length=255, verbose_name='原始文件名')
    mime_type = models.CharField(max_length=50, verbose_name='MIME类型')
    file_size = models.PositiveBigIntegerField(verbose_name='文件大小')
    sha256 = models.CharField(max_length=64, db_index=True, verbose_name='SHA-256')
    width = models.PositiveIntegerField(verbose_name='宽度')
    height = models.PositiveIntegerField(verbose_name='高度')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='上传时间')

    class Meta:
        db_table = 'plat_external_image_upload'
        verbose_name = '外部上传图片'
        verbose_name_plural = '外部上传图片'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.id} / {self.original_name}'
