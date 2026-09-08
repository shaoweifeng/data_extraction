"""任务启动、停止和恢复生命周期的集成测试。"""

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from core.executors.executor import StepExecutor
from core.models import ActivityLog, Project, Task
from core.scheduler import TaskScheduler
from core.services.project_service import initialize_project
from core.workflow.domain.statuses import StageStepStatus, TaskStatus


User = get_user_model()


class TaskLifecycleIntegrationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('task-user', password='pw')
        self.project = Project.objects.create(name='任务项目', owner=self.user)
        initialize_project(self.project, self.user)
        self.client = Client()
        self.client.force_login(self.user)

    def test_manual_task_start_stop_resume_lifecycle(self):
        with tempfile.TemporaryDirectory() as temp_dir, override_settings(BASE_DIR=Path(temp_dir)):
            start = self.client.post(
                '/api/tasks/',
                {'project': self.project.id, 'task_type': 'criteria', 'config': {'draft': True}},
                content_type='application/json',
            )
            self.assertEqual(start.status_code, 201)
            task = Task.objects.get(pk=start.json()['id'])
            self.assertEqual(task.status, 'pending')
            self.assertEqual(task.created_by, self.user)

            stop = self.client.post(f'/api/tasks/{task.id}/stop/')
            self.assertEqual(stop.status_code, 200)
            task.refresh_from_db()
            self.assertEqual(task.status, 'stopped')
            self.assertIsNotNone(task.completed_at)
            self.assertTrue((Path(temp_dir) / 'workspaces' / f'project_{self.project.id}' / 'criteria.STOP').exists())

            resume = self.client.post(f'/api/tasks/{task.id}/resume/')
            self.assertEqual(resume.status_code, 200)
            task.refresh_from_db()
            self.assertEqual(task.status, 'superseded')
            new_task = Task.objects.get(pk=resume.json()['task']['id'])
            self.assertEqual(new_task.status, 'pending')
            self.assertEqual(new_task.config['resume_progress'], 0.0)

        operation_types = list(
            ActivityLog.objects.filter(project=self.project)
            .order_by('created_at')
            .values_list('operation_type', flat=True)
        )
        self.assertEqual(operation_types, ['task_start_criteria', 'task_stop', 'task_resume'])

    def test_completed_task_cannot_be_stopped_or_resumed(self):
        task = Task.objects.create(
            project=self.project,
            task_type='criteria',
            status='completed',
            created_by=self.user,
        )
        self.assertEqual(self.client.post(f'/api/tasks/{task.id}/stop/').status_code, 400)
        self.assertEqual(self.client.post(f'/api/tasks/{task.id}/resume/').status_code, 400)

    def test_terminal_tasks_reject_stop_and_resume(self):
        """终态任务不能重新进入停止或恢复流程。"""
        for task_status in ('completed', 'failed', 'superseded'):
            with self.subTest(task_status=task_status):
                task = Task.objects.create(
                    project=self.project,
                    task_type='criteria',
                    status=task_status,
                    created_by=self.user,
                )
                self.assertEqual(self.client.post(f'/api/tasks/{task.id}/stop/').status_code, 400)
                self.assertEqual(self.client.post(f'/api/tasks/{task.id}/resume/').status_code, 400)

        self.assertFalse(ActivityLog.objects.filter(project=self.project).exists())

    def test_repeated_stop_is_idempotent_at_api_boundary(self):
        """重复停止不会重复写状态或操作日志。"""
        task = Task.objects.create(
            project=self.project,
            task_type='criteria',
            status='running',
            created_by=self.user,
        )

        with tempfile.TemporaryDirectory() as temp_dir, override_settings(BASE_DIR=Path(temp_dir)):
            first = self.client.post(f'/api/tasks/{task.id}/stop/')
            second = self.client.post(f'/api/tasks/{task.id}/stop/')

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 400)
        task.refresh_from_db()
        self.assertEqual(task.status, 'stopped')
        self.assertEqual(
            ActivityLog.objects.filter(project=self.project, operation_type='task_stop').count(),
            1,
        )

    def test_repeated_resume_creates_only_one_successor(self):
        """同一停止任务只能恢复一次，旧任务随后成为 superseded。"""
        task = Task.objects.create(
            project=self.project,
            task_type='criteria',
            status='stopped',
            progress=0.35,
            config={'criteria': ['PICO']},
            created_by=self.user,
        )

        first = self.client.post(f'/api/tasks/{task.id}/resume/')
        second = self.client.post(f'/api/tasks/{task.id}/resume/')

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 400)
        task.refresh_from_db()
        self.assertEqual(task.status, 'superseded')
        self.assertEqual(Task.objects.filter(project=self.project, task_type='criteria').count(), 2)
        self.assertEqual(
            ActivityLog.objects.filter(project=self.project, operation_type='task_resume').count(),
            1,
        )

    def test_resume_transfers_checkpoint_progress_and_business_config(self):
        """恢复任务保留业务配置，并把旧 checkpoint 转换成显式续传配置。"""
        task = Task.objects.create(
            project=self.project,
            task_type='criteria',
            status='stopped',
            progress=0.625,
            config={
                'criteria': ['纳入随机对照试验'],
                'checkpoint_path': '/tmp/old-task/checkpoint.json',
            },
            created_by=self.user,
        )

        response = self.client.post(f'/api/tasks/{task.id}/resume/')

        self.assertEqual(response.status_code, 200)
        successor = Task.objects.get(pk=response.json()['task']['id'])
        self.assertEqual(successor.config['criteria'], ['纳入随机对照试验'])
        self.assertEqual(successor.config['resume_progress'], 0.625)
        self.assertEqual(
            successor.config['resume_checkpoint_path'],
            '/tmp/old-task/checkpoint.json',
        )
        self.assertNotIn('checkpoint_path', successor.config)

    def test_async_resume_dispatches_one_celery_job(self):
        """异步任务重复恢复时只允许派发一个后继 Celery job。"""
        task = Task.objects.create(
            project=self.project,
            task_type='qa_chart',
            status='stopped',
            config={'checkpoint_path': '/tmp/qa-chart/checkpoint.json'},
            created_by=self.user,
        )

        with patch(
            'core.executors.celery_tasks.execute_async_step.delay',
            return_value=SimpleNamespace(id='celery-resume-1'),
        ) as delay:
            first = self.client.post(f'/api/tasks/{task.id}/resume/')
            second = self.client.post(f'/api/tasks/{task.id}/resume/')

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 400)
        delay.assert_called_once()
        successor = Task.objects.get(pk=first.json()['task']['id'])
        self.assertEqual(delay.call_args.args, (successor.id, 'qa_chart', self.project.id))
        self.assertEqual(successor.celery_task_id, 'celery-resume-1')

    def test_completed_step_can_be_executed_again(self):
        """已完成的去重步骤重新执行时先重置，再进入执行中。"""
        step = self.project.stages.get(stage_key='SCREEN_1').steps.get(step_key='dedup')
        step.status = StageStepStatus.COMPLETED
        step.started_at = timezone.now()
        step.completed_at = timezone.now()
        step.save(update_fields=['status', 'started_at', 'completed_at', 'updated_at'])
        task = Task.objects.create(
            project=self.project,
            task_type='dedup',
            status=TaskStatus.RUNNING,
            created_by=self.user,
        )

        with tempfile.TemporaryDirectory() as temp_dir, override_settings(BASE_DIR=Path(temp_dir)):
            executor = StepExecutor(task.id, 'dedup', self.project.id)
            executor.initialize()
            step.refresh_from_db()
            self.assertEqual(step.status, StageStepStatus.IN_PROGRESS)
            self.assertIsNotNone(step.started_at)
            self.assertIsNone(step.completed_at)
            executor.finalize(True)

        task.refresh_from_db()
        step.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertEqual(step.status, StageStepStatus.COMPLETED)

    def test_finalize_failure_does_not_leave_task_running_when_step_is_terminal(self):
        """初始化期间失败时，步骤状态冲突不得阻止 Task 落到 failed。"""
        stage = self.project.stages.get(stage_key='SCREEN_1')
        step = stage.steps.get(step_key='dedup')
        step.status = StageStepStatus.COMPLETED
        step.save(update_fields=['status', 'updated_at'])
        task = Task.objects.create(
            project=self.project,
            task_type='dedup',
            status=TaskStatus.RUNNING,
            created_by=self.user,
        )

        with tempfile.TemporaryDirectory() as temp_dir, override_settings(BASE_DIR=Path(temp_dir)):
            executor = StepExecutor(task.id, 'dedup', self.project.id)
            executor.task_obj = task
            executor.project_obj = self.project
            executor.stage_obj = stage
            executor.step_obj = step
            executor.finalize(False, '初始化失败')

        task.refresh_from_db()
        step.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertEqual(step.status, StageStepStatus.COMPLETED)
        self.assertEqual(task.error_message, '初始化失败')


class TaskDispatchContractTests(TestCase):
    """固定调度入口的派发次数和步骤级重复启动边界。"""

    def setUp(self):
        self.user = User.objects.create_user('dispatch-user', password='pw')
        self.project = Project.objects.create(name='派发项目', owner=self.user)
        initialize_project(self.project, self.user)
        self.client = Client()
        self.client.force_login(self.user)

    def test_async_start_dispatches_exactly_one_celery_job(self):
        with patch(
            'core.executors.celery_tasks.execute_async_step.delay',
            return_value=SimpleNamespace(id='celery-start-1'),
        ) as delay:
            task = TaskScheduler(self.project.id).start_step('qa_chart', self.user.id)

        delay.assert_called_once_with(task.id, 'qa_chart', self.project.id)
        task.refresh_from_db()
        self.assertEqual(task.celery_task_id, 'celery-start-1')

    def test_step_api_rejects_sequential_duplicate_start(self):
        """步骤进入 in_progress 后，同一 API 入口不能再次启动它。"""
        step = self.project.stages.get(stage_key='SCREEN_1').steps.get(step_key='criteria')
        task = Task.objects.create(
            project=self.project,
            task_type='criteria',
            status='pending',
            created_by=self.user,
        )

        with patch('core.scheduler.TaskScheduler.start_step', return_value=task) as start_step:
            first = self.client.post(f'/api/steps/{step.id}/start/', {'config': {}}, content_type='application/json')
            second = self.client.post(f'/api/steps/{step.id}/start/', {'config': {}}, content_type='application/json')

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 400)
        start_step.assert_called_once_with('criteria', self.user.id)
        step.refresh_from_db()
        self.assertEqual(step.status, 'in_progress')

    def test_completed_step_rejects_restart_without_dispatch(self):
        step = self.project.stages.get(stage_key='SCREEN_1').steps.get(step_key='criteria')
        step.status = 'completed'
        step.save(update_fields=['status'])

        with patch('core.scheduler.TaskScheduler.start_step') as start_step:
            response = self.client.post(
                f'/api/steps/{step.id}/start/',
                {'config': {}},
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 400)
        start_step.assert_not_called()


class WorkerFinalizationContractTests(TestCase):
    """固定 worker 收尾与用户停止发生竞争时的当前正确行为。"""

    def setUp(self):
        self.user = User.objects.create_user('worker-user', password='pw')
        self.project = Project.objects.create(name='Worker 项目', owner=self.user)
        initialize_project(self.project, self.user)

    def test_worker_finalize_does_not_overwrite_stopped_task(self):
        task = Task.objects.create(
            project=self.project,
            task_type='qa_chart',
            status='pending',
            created_by=self.user,
        )

        with tempfile.TemporaryDirectory() as temp_dir, override_settings(BASE_DIR=Path(temp_dir)):
            executor = StepExecutor(task.id, 'qa_chart', self.project.id)
            executor.initialize()
            executor.save_checkpoint({'completed': ['traffic_light']})

            Task.objects.filter(pk=task.id).update(status='stopped')
            executor.finalize(False, 'worker observed stop')

            task.refresh_from_db()
            task.step.refresh_from_db()
            self.assertEqual(task.status, 'stopped')
            self.assertEqual(task.step.status, 'stopped')
            self.assertEqual(task.error_message, '')
            self.assertEqual(
                task.config['checkpoint_path'],
                str(executor.logger.checkpoint_file),
            )
            self.assertIsNotNone(task.completed_at)
