"""Private storage for externally uploaded images."""

import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


@deconstructible
class ExternalImageStorage(FileSystemStorage):
    def __init__(self):
        super().__init__(
            location=None,
            base_url=None,
            file_permissions_mode=0o600,
            directory_permissions_mode=0o700,
        )

    @property
    def base_location(self):
        return settings.EXTERNAL_IMAGE_UPLOAD_ROOT

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    @property
    def base_url(self):
        return None

    def url(self, name):
        raise ValueError('外部上传图片是私有文件，不提供公开 URL。')


external_image_storage = ExternalImageStorage()
