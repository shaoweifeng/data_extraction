"""Per-user persistent storage accounting and quota enforcement."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Sum


MEBIBYTE = 1024 * 1024


class StorageQuotaExceeded(ValueError):
    code = 'storage_quota_exceeded'

    def __init__(self, snapshot: 'StorageQuotaSnapshot', incoming_bytes: int):
        self.snapshot = snapshot
        self.incoming_bytes = max(0, int(incoming_bytes or 0))
        super().__init__(
            f'存储空间不足：已使用 {snapshot.used_mb:.1f} MB，'
            f'本次需要 {self.incoming_bytes / MEBIBYTE:.1f} MB，'
            f'当前上限 {snapshot.limit_mb} MB。请删除无用文件或联系管理员。'
        )


@dataclass(frozen=True)
class StorageQuotaSnapshot:
    used_bytes: int
    limit_bytes: int | None

    @property
    def used_mb(self) -> float:
        return self.used_bytes / MEBIBYTE

    @property
    def limit_mb(self) -> int | None:
        return None if self.limit_bytes is None else self.limit_bytes // MEBIBYTE

    @property
    def remaining_bytes(self) -> int | None:
        if self.limit_bytes is None:
            return None
        return max(0, self.limit_bytes - self.used_bytes)


def _sum(queryset, field: str) -> int:
    return int(queryset.aggregate(total=Sum(field))['total'] or 0)


def _stored_size(field_file) -> int:
    if not field_file or not getattr(field_file, 'name', ''):
        return 0
    try:
        return int(field_file.storage.size(field_file.name))
    except (OSError, ValueError, NotImplementedError):
        return 0


def user_storage_usage_bytes(user) -> int:
    """Return persisted bytes owned by one account without double-counting imports."""
    if not user or not getattr(user, 'pk', None):
        return 0

    from core.feedback.models import FeedbackAttachment
    from core.models import DataFile, QAFulltextAsset
    from core.screening.models import ReferenceImportFile

    # DataFile rows for screening source imports deliberately have an empty
    # ``file`` value; their private raw file is counted by ReferenceImportFile.
    data_files = _sum(
        DataFile.objects.filter(project__owner=user).exclude(file=''),
        'file_size',
    )
    screening_imports = _sum(
        ReferenceImportFile.objects.filter(import_batch__project__owner=user),
        'source_file__file_size',
    )
    qa_assets = QAFulltextAsset.objects.filter(project__owner=user)
    qa_raw = _sum(qa_assets, 'size_bytes')
    qa_derived = sum(
        _stored_size(field_file)
        for asset in qa_assets.only('extracted_text_file', 'chunk_index_file').iterator()
        for field_file in (asset.extracted_text_file, asset.chunk_index_file)
    )
    feedback = _sum(
        FeedbackAttachment.objects.filter(feedback__reporter_user_id=user.pk),
        'file_size',
    )
    return data_files + screening_imports + qa_raw + qa_derived + feedback


def storage_quota_snapshot(user) -> StorageQuotaSnapshot:
    from core.services.entitlement_service import resolve_user_entitlements

    quota_mb = int(resolve_user_entitlements(user, sync=False).storage_limit_mb)
    limit_bytes = None if quota_mb < 0 else quota_mb * MEBIBYTE
    return StorageQuotaSnapshot(
        used_bytes=user_storage_usage_bytes(user),
        limit_bytes=limit_bytes,
    )


def enforce_user_storage_quota(user, incoming_bytes: int) -> StorageQuotaSnapshot:
    """Validate quota; caller must hold the user row lock until files are saved."""
    snapshot = storage_quota_snapshot(user)
    incoming = max(0, int(incoming_bytes or 0))
    if (
        getattr(settings, 'USER_STORAGE_QUOTA_ENABLED', True)
        and snapshot.limit_bytes is not None
        and snapshot.used_bytes + incoming > snapshot.limit_bytes
    ):
        raise StorageQuotaExceeded(snapshot, incoming)
    return snapshot


@contextmanager
def user_storage_quota_guard(user, incoming_bytes: int):
    """Serialize quota check and persistence for concurrent upload requests."""
    with transaction.atomic():
        locked_user = (
            get_user_model().objects.select_for_update().select_related('profile').get(pk=user.pk)
        )
        snapshot = enforce_user_storage_quota(locked_user, incoming_bytes)
        yield snapshot

