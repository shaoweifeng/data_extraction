"""Persistent per-user storage accounting and quota enforcement tests."""

import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings

from core.artifacts.services import persist_generated_artifact
from core.models import DataFile, Project
from core.services.storage_quota_service import (
    MEBIBYTE,
    StorageQuotaExceeded,
    enforce_user_storage_quota,
    storage_quota_snapshot,
)


User = get_user_model()


class UserStorageQuotaTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.override = override_settings(
            MEDIA_ROOT=Path(self.temp_dir.name) / 'media',
            USER_STORAGE_QUOTA_ENABLED=True,
        )
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.user = User.objects.create_user('storage-owner')
        self.project = Project.objects.create(name='Storage project', owner=self.user)

    def test_counts_persisted_project_files_and_enforces_limit(self):
        artifact = DataFile(
            project=self.project,
            filename='existing.bin',
            data_category='output',
            source='tool_generated',
            created_by=self.user,
        )
        artifact.file.save('existing.bin', ContentFile(b'x' * 128), save=True)

        snapshot = storage_quota_snapshot(self.user)
        self.assertEqual(snapshot.used_bytes, 128)

        self.user.profile.quota_storage_mb_override = 0
        self.user.profile.save(update_fields=['quota_storage_mb_override'])
        with self.assertRaises(StorageQuotaExceeded):
            enforce_user_storage_quota(self.user, 1)

    def test_unlimited_sentinel_allows_upload(self):
        self.user.profile.quota_storage_mb_override = -1
        self.user.profile.save(update_fields=['quota_storage_mb_override'])

        snapshot = enforce_user_storage_quota(self.user, 100 * MEBIBYTE)

        self.assertIsNone(snapshot.limit_bytes)

    def test_generated_artifact_is_guarded(self):
        self.user.profile.quota_storage_mb_override = 0
        self.user.profile.save(update_fields=['quota_storage_mb_override'])
        source = Path(self.temp_dir.name) / 'generated.txt'
        source.write_text('generated output', encoding='utf-8')

        with self.assertRaises(StorageQuotaExceeded):
            persist_generated_artifact(
                project=self.project,
                stage=None,
                step=None,
                creator=self.user,
                file_path=source,
                filename='generated.txt',
                description='test',
            )
        self.assertFalse(DataFile.objects.filter(project=self.project).exists())
