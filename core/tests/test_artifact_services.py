"""Generated-artifact workspace lifecycle tests."""

import os
import tempfile
import time
from pathlib import Path

from django.test import SimpleTestCase

from core.artifacts.services import cleanup_expired_workspaces


class WorkspaceCleanupTests(SimpleTestCase):
    def test_cleanup_removes_only_expired_managed_task_directories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / 'workspaces'
            project = root / 'project_7'
            expired = project / 'export_task_11_20260101_010101'
            current = project / 'export_task_12_20260928_010101'
            unmanaged = project / 'keep-me'
            for path in (expired, current, unmanaged):
                path.mkdir(parents=True)
            now = time.time()
            os.utime(expired, (now - 10_000, now - 10_000))
            os.utime(current, (now, now))
            os.utime(unmanaged, (now - 10_000, now - 10_000))

            cleaned = cleanup_expired_workspaces(root, now - 100)

            self.assertEqual(cleaned, 1)
            self.assertFalse(expired.exists())
            self.assertTrue(current.exists())
            self.assertTrue(unmanaged.exists())

    def test_cleanup_rejects_a_broad_or_unexpected_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, 'workspaces'):
                cleanup_expired_workspaces(Path(temp_dir), time.time())
