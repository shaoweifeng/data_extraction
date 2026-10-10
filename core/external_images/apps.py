from django.apps import AppConfig
from django.core.exceptions import ImproperlyConfigured


class ExternalImagesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core.external_images'
    label = 'external_images'
    verbose_name = '外部图片接收'

    def ready(self):
        from django.conf import settings

        if settings.EXTERNAL_IMAGE_UPLOAD_ENABLED and len(settings.EXTERNAL_IMAGE_UPLOAD_API_KEY) < 32:
            raise ImproperlyConfigured(
                '启用外部图片上传时，EXTERNAL_IMAGE_UPLOAD_API_KEY 至少需要 32 个字符。'
            )
        import core.external_images.signals  # noqa: F401
