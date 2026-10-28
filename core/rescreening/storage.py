import os
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


@deconstructible
class PrivateRescreenStorage(FileSystemStorage):
    def __init__(self):
        super().__init__(location=None, base_url=None)

    @property
    def base_location(self):
        return getattr(settings, 'RESCREEN_IMPORT_UPLOAD_ROOT', '') or os.path.join(settings.BASE_DIR, 'private_media', 'rescreening', 'imports')

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    @property
    def base_url(self):
        return None

    def url(self, name):
        raise ValueError('复筛原始题录为私有文件，请使用鉴权下载接口。')


def rescreen_upload_path(instance, filename):
    return f'project_{instance.batch.project_id}/batch_{instance.batch_id}/{uuid4().hex}{Path(filename).suffix.lower()}'


@deconstructible
class PrivateRescreenExportStorage(PrivateRescreenStorage):
    @property
    def base_location(self):
        return getattr(settings, 'RESCREEN_EXPORT_UPLOAD_ROOT', '') or os.path.join(settings.BASE_DIR, 'private_media', 'rescreening', 'exports')


def rescreen_export_path(instance, filename):
    return f'project_{instance.project_id}/{uuid4().hex}{Path(filename).suffix.lower()}'
