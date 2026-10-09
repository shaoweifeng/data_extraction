"""Private storage helpers for quality-evaluation full text assets."""

import os
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

from django.conf import settings
from django.core.files.storage import FileSystemStorage, storages
from django.utils.deconstruct import deconstructible


def qa_fulltext_upload_path(instance, filename):
    """Keep untrusted filenames out of storage paths."""
    suffix = Path(filename).suffix.lower() or '.pdf'
    return f'project_{instance.qa_reference.project_id}/pdf/{uuid4().hex}{suffix}'


def qa_extracted_text_upload_path(instance, filename):
    return f'project_{instance.qa_reference.project_id}/text/{uuid4().hex}.txt'


def qa_chunk_index_upload_path(instance, filename):
    """Store derived chunk indexes beside private extracted text."""
    return f'project_{instance.qa_reference.project_id}/chunks/{uuid4().hex}.jsonl'


@deconstructible
class PrivateQAStorage(FileSystemStorage):
    """Private local default that can be replaced by an object-storage backend."""

    def __init__(self):
        super().__init__(location=None, base_url=None)

    @property
    def base_location(self):
        return settings.QA_FULLTEXT_UPLOAD_ROOT

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    @property
    def base_url(self):
        return None

    def url(self, name):
        raise ValueError('质量评价全文是私有文件，请使用鉴权下载接口。')


def qa_fulltext_storage():
    """Resolve the configured backend lazily so migrations remain portable."""
    return storages['qa_fulltext']


@contextmanager
def materialized_storage_path(field_file, *, suffix=''):
    """Yield a parser-compatible path for local or remote Django storage.

    Object storage normally has no ``path()``. In that case the object is copied
    into a bounded-lifetime temporary file and removed immediately afterwards.
    """
    try:
        path = field_file.path
    except (AttributeError, NotImplementedError):
        path = None
    if path and os.path.exists(path):
        yield path
        return

    temp = NamedTemporaryFile(prefix='qa-fulltext-', suffix=suffix, delete=False)
    temp_path = temp.name
    try:
        field_file.open('rb')
        with temp:
            while True:
                chunk = field_file.read(1024 * 1024)
                if not chunk:
                    break
                temp.write(chunk)
        yield temp_path
    finally:
        try:
            field_file.close()
        except Exception:
            pass
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass
