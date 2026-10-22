from django.conf import settings
from django.test import SimpleTestCase


class ScheduledFileCleanupTests(SimpleTestCase):
    def test_daily_cleanup_tasks_are_registered_and_staggered(self):
        expected = {
            'cleanup-old-task-workspaces-daily': (
                'core.executors.celery_tasks.cleanup_old_workspaces', 0,
            ),
            'cleanup-abandoned-screening-imports-daily': (
                'core.executors.celery_tasks.cleanup_abandoned_screening_imports', 10,
            ),
            'cleanup-qa-fulltext-files-daily': (
                'core.quality.tasks.cleanup_qa_fulltext_files', 20,
            ),
        }

        self.assertTrue(settings.FILE_RETENTION_CLEANUP_ENABLED)
        for schedule_name, (task_name, minute) in expected.items():
            with self.subTest(schedule=schedule_name):
                entry = settings.CELERY_BEAT_SCHEDULE[schedule_name]
                self.assertEqual(entry['task'], task_name)
                self.assertEqual(entry['schedule'].hour, {settings.FILE_RETENTION_CLEANUP_HOUR})
                self.assertEqual(entry['schedule'].minute, {minute})
