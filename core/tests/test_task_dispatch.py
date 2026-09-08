"""任务创建、派发、worker 认领和排队取消测试。"""

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from celery.exceptions import Retry
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from core.executors.celery_tasks import execute_async_step
from core.models import Project, Task
from core.scheduler import TaskScheduler
from core.services.project_service import initialize_project
from core.workflow.domain.statuses import TaskStatus
from core.workflow.services.lifecycle import transition_task
from core.workflow.services.task_launcher import ActiveTaskExists, create_step_task


User = get_user_model()


class TaskCreationBoundaryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('launch-user', password='pw')
        self.project = Project.objects.create(name='启动互斥项目', owner=self.user)
        initialize_project(self.project, self.user)

    def test_same_project_and_executable_step_rejects_second_active_task(self):
        first = create_step_task(self.project.id, 'qa_chart', self.user.id, {})

        with self.assertRaises(ActiveTaskExists):
            create_step_task(self.project.id, 'qa_chart', self.user.id, {})

        self.assertEqual(first.status, TaskStatus.PENDING)
        self.assertEqual(Task.objects.filter(project=self.project, task_type='qa_chart').count(), 1)

    def test_completed_task_does_not_block_a_new_attempt(self):
        old = create_step_task(self.project.id, 'qa_chart', self.user.id, {})
        transition_task(old, TaskStatus.RUNNING)
        transition_task(old, TaskStatus.COMPLETED)

        new = create_step_task(self.project.id, 'qa_chart', self.user.id, {})

        self.assertNotEqual(old.id, new.id)
        self.assertEqual(new.status, TaskStatus.PENDING)

    def test_different_steps_and_projects_do_not_block_each_other(self):
        other_project = Project.objects.create(name='另一个项目', owner=self.user)
        initialize_project(other_project, self.user)

        qa_task = create_step_task(self.project.id, 'qa_chart', self.user.id, {})
        parse_task = create_step_task(self.project.id, 'parse', self.user.id, {})
        other_qa_task = create_step_task(other_project.id, 'qa_chart', self.user.id, {})

        self.assertEqual({qa_task.project_id, parse_task.project_id}, {self.project.id})
        self.assertEqual(other_qa_task.project_id, other_project.id)

    def test_manual_steps_keep_their_existing_nonexclusive_behavior(self):
        first = create_step_task(
            self.project.id, 'criteria', self.user.id, {}, exclusive=False,
        )
        second = create_step_task(
            self.project.id, 'criteria', self.user.id, {}, exclusive=False,
        )

        self.assertNotEqual(first.id, second.id)


class SchedulerDispatchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('scheduler-user', password='pw')
        self.project = Project.objects.create(name='调度项目', owner=self.user)
        initialize_project(self.project, self.user)

    def test_async_dispatch_keeps_task_pending_until_worker_claims_it(self):
        with patch(
            'core.executors.celery_tasks.execute_async_step.delay',
            return_value=SimpleNamespace(id='broker-job-1'),
        ):
            task = TaskScheduler(self.project.id).start_step('qa_chart', self.user.id)

        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.PENDING)
        self.assertIsNone(task.started_at)
        self.assertEqual(task.celery_task_id, 'broker-job-1')

    def test_broker_failure_marks_created_task_failed(self):
        with patch(
            'core.executors.celery_tasks.execute_async_step.delay',
            side_effect=RuntimeError('broker unavailable'),
        ):
            with self.assertRaises(RuntimeError):
                TaskScheduler(self.project.id).start_step('qa_chart', self.user.id)

        task = Task.objects.get(project=self.project, task_type='qa_chart')
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIn('broker unavailable', task.error_message)
        self.assertIsNotNone(task.completed_at)

    def test_queued_ai_task_can_be_stopped_and_removed_from_queue(self):
        task = Task.objects.create(
            project=self.project,
            task_type='ai_screen',
            status=TaskStatus.QUEUING,
            created_by=self.user,
        )

        with tempfile.TemporaryDirectory() as temp_dir, override_settings(BASE_DIR=Path(temp_dir)), \
                patch('core.services.concurrency_service.cancel_queue') as cancel_queue:
            stopped = TaskScheduler(self.project.id).stop_task(task.id)

        self.assertTrue(stopped)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.STOPPED)
        cancel_queue.assert_called_once_with(task.id, 2)


class WorkerClaimTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('worker-claim-user', password='pw')
        self.project = Project.objects.create(name='Worker 认领项目', owner=self.user)
        initialize_project(self.project, self.user)

    def test_duplicate_delivery_executes_handler_only_once(self):
        task = Task.objects.create(
            project=self.project,
            task_type='qa_chart',
            status=TaskStatus.PENDING,
            created_by=self.user,
        )
        executor = Mock()

        def assert_worker_claimed():
            task.refresh_from_db()
            self.assertEqual(task.status, TaskStatus.RUNNING)
            self.assertIsNotNone(task.started_at)

        def finish(success, error_msg=None):
            self.assertTrue(success)
            task.refresh_from_db()
            transition_task(task, TaskStatus.COMPLETED)

        executor.initialize.side_effect = assert_worker_claimed
        executor.execute.return_value = True
        executor.finalize.side_effect = finish

        with patch('core.executors.executor.StepExecutor', return_value=executor) as executor_class:
            first = execute_async_step.run(task.id, 'qa_chart', self.project.id)
            second = execute_async_step.run(task.id, 'qa_chart', self.project.id)

        self.assertTrue(first)
        self.assertFalse(second)
        executor_class.assert_called_once_with(task.id, 'qa_chart', self.project.id)
        executor.execute.assert_called_once_with()

    def test_stopped_pending_delivery_never_initializes_executor(self):
        task = Task.objects.create(
            project=self.project,
            task_type='qa_chart',
            status=TaskStatus.STOPPED,
            created_by=self.user,
        )

        with patch('core.executors.executor.StepExecutor') as executor_class:
            result = execute_async_step.run(task.id, 'qa_chart', self.project.id)

        self.assertFalse(result)
        executor_class.assert_not_called()

    def test_ai_task_without_slots_stays_queued_and_does_not_initialize(self):
        task = Task.objects.create(
            project=self.project,
            task_type='ai_screen',
            status=TaskStatus.PENDING,
            created_by=self.user,
        )
        queue_info = {
            'position': 2,
            'queue_length': 3,
            'slots_free': 0,
            'slots_total': 64,
        }

        with patch('core.services.concurrency_service.get_user_concurrency', return_value=2), \
                patch('core.services.concurrency_service.try_acquire', return_value=False), \
                patch('core.services.concurrency_service.get_queue_info', return_value=queue_info), \
                patch.object(execute_async_step, 'retry', side_effect=Retry()), \
                patch('core.executors.executor.StepExecutor') as executor_class:
            with self.assertRaises(Retry):
                execute_async_step.run(task.id, 'ai_screen', self.project.id)

        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.QUEUING)
        self.assertEqual(task.config['queue_info']['position'], 2)
        executor_class.assert_not_called()

    def test_retryable_failure_returns_same_task_to_pending(self):
        task = Task.objects.create(
            project=self.project,
            task_type='qa_chart',
            status=TaskStatus.PENDING,
            created_by=self.user,
        )
        executor = Mock()
        executor.execute.side_effect = RuntimeError('temporary renderer failure')

        with patch('core.executors.executor.StepExecutor', return_value=executor), \
                patch.object(execute_async_step, 'retry', side_effect=Retry()):
            with self.assertRaises(Retry):
                execute_async_step.run(task.id, 'qa_chart', self.project.id)

        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.PENDING)
        self.assertIn('temporary renderer failure', task.error_message)
        executor.finalize.assert_not_called()
        executor.logger.close.assert_called_once_with()
