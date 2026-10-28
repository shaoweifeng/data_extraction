import os
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


@deconstructible
class PrivateFulltextStorage(FileSystemStorage):
    def __init__(self):
        super().__init__(location=None, base_url=None)

    @property
    def base_location(self):
        return getattr(settings, 'FULLTEXT_UPLOAD_ROOT', '') or os.path.join(settings.BASE_DIR, 'private_media', 'fulltext')

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    @property
    def base_url(self):
        return None

    def url(self, name):
        raise ValueError('全文资产为私有文件，请使用鉴权下载接口。')


def fulltext_upload_path(instance, filename):
    return f'projects/{instance.project_id}/{instance.asset_key}/{uuid4().hex}{Path(filename).suffix.lower()}'


@contextmanager
def materialized_storage_path(field_file, *, suffix='', max_bytes=None):
    """Local or remote Storage, with bounded temporary bodies and unconditional cleanup."""
    from core.fulltext.errors import FulltextError
    try:
        path = field_file.path
    except (AttributeError, NotImplementedError):
        path = None
    if path and os.path.exists(path):
        if max_bytes is not None and os.path.getsize(path) > max_bytes:
            raise FulltextError('file_too_large', '私有 PDF 超过允许大小。')
        yield path
        return
    temporary = NamedTemporaryFile(prefix='metaflow-fulltext-', suffix=suffix, delete=False)
    try:
        field_file.open('rb')
        size = 0
        with temporary:
            while body := field_file.read(1024*1024):
                size += len(body)
                if max_bytes is not None and size > max_bytes:
                    raise FulltextError('file_too_large', '私有 PDF 超过允许大小。')
                temporary.write(body)
        yield temporary.name
    finally:
        temporary.close()
        try:
            field_file.close()
        except Exception:
            pass
        try:
            os.unlink(temporary.name)
        except FileNotFoundError:
            pass
