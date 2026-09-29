"""Private filesystem storage for raw screening reference imports."""

import os
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


def screening_import_upload_path(instance, filename):
    """Use server-generated names and keep user filenames out of storage paths."""
    extension = Path(filename).suffix.lower()
    project_id = instance.import_batch.project_id
    return f'project_{project_id}/batch_{instance.import_batch_id}/{uuid4().hex}{extension}'


@deconstructible
class PrivateScreeningStorage(FileSystemStorage):
    """Storage without a public URL; location follows override_settings in tests."""

    def __init__(self):
        super().__init__(location=None, base_url=None)

    @property
    def base_location(self):
        return settings.SCREENING_IMPORT_UPLOAD_ROOT

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    @property
    def base_url(self):
        return None

    def url(self, name):
        raise ValueError('私有索引文件没有公开 URL，请使用鉴权下载接口。')
