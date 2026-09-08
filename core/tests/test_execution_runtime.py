"""工作流文件运行时组件测试。"""

import json
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from core.models import Project, Task
from core.workflow.runtime import CheckpointStore, TaskReporter, WorkspaceManager


User = get_user_model()


class CheckpointStoreTests(TestCase):
    def test_checkpoint_round_trip_and_clear(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CheckpointStore(Path(temp_dir) / 'nested' / 'checkpoint.json')
            payload = {'processed_sources': ['a.xml'], 'progress': 0.5}

            store.save(payload)
            self.assertEqual(store.load(), payload)
            store.clear()
            self.assertIsNone(store.load())


class WorkspaceManagerTests(TestCase):
    def test_workspace_is_isolated_by_task_id(self):
        with tempfile.TemporaryDirectory() as temp_dir, override_settings(BASE_DIR=Path(temp_dir)):
            first = WorkspaceManager(7, 'qa_chart', 101).prepare()
            second = WorkspaceManager(7, 'qa_chart', 102).prepare()

        self.assertNotEqual(first, second)
        self.assertIn('task_101', first.name)
        self.assertIn('task_102', second.name)

    def test_stop_signal_lifecycle(self):
        with tempfile.TemporaryDirectory() as temp_dir, override_settings(BASE_DIR=Path(temp_dir)):
            manager = WorkspaceManager(7, 'ai_screen', 101)
            signal_path = manager.create_stop_signal('test stop')

            self.assertTrue(manager.has_stop_signal())
            payload = json.loads(signal_path.read_text(encoding='utf-8'))
            self.assertEqual(payload['task_id'], 101)
            self.assertEqual(payload['reason'], 'test stop')
            manager.clear_stop_signal()
            self.assertFalse(manager.has_stop_signal())


class TaskReporterTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('reporter-user', password='pw')
        self.project = Project.objects.create(name='Reporter 项目', owner=self.user)
        self.task = Task.objects.create(
            project=self.project,
            task_type='qa_chart',
            created_by=self.user,
        )

    def test_reporter_writes_progress_checkpoint_and_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reporter = TaskReporter(self.task.id, temp_dir)
            reporter._progress_sync_interval = 1
            reporter.update_progress(1, 2, 'refs')
            reporter._save_checkpoint({'processed': [1]})

            self.task.refresh_from_db()
            self.assertEqual(self.task.progress, 0.5)
            self.assertEqual(reporter.load_checkpoint(), {'processed': [1]})
            metadata = reporter.get_metadata()
            self.assertGreaterEqual(metadata['line_count'], 2)
            self.assertEqual(metadata['progress_file'], str(reporter.progress_file))
            reporter.close()
