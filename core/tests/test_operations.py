from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.models import Project, QAReference, SystemOperationState, Task
from core.operations.services import (
    get_operations_snapshot,
    pause_long_running_tasks,
    reconcile_interrupted_tasks,
    resume_maintenance_tasks,
    set_system_state,
)
from core.quality.executors.qa_eval import QAEvalStepHandler
from core.workflow.services.task_launcher import create_step_task


User = get_user_model()


class OperationsApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('operator-user', password='pw')
        self.admin = User.objects.create_user('operator-admin', password='pw')
        self.admin.profile.role = 'admin'
        self.admin.profile.save(update_fields=['role'])

    def tearDown(self):
        set_system_state('normal')

    def test_public_system_status_and_authenticated_heartbeat(self):
        response = self.client.get('/api/system/status/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['mode'], 'normal')

        self.client.force_login(self.user)
        with patch('core.operations.api_views.record_presence') as record:
            response = self.client.post(
                '/api/presence/heartbeat/',
                {'tab_id': 'tab-1', 'page': '/workspace/7', 'project_id': 7},
                content_type='application/json',
            )
        self.assertEqual(response.status_code, 200)
        record.assert_called_once()

    def test_only_admin_can_read_and_change_operations_state(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get('/api/operations/status/').status_code, 403)
        self.assertEqual(
            self.client.post('/api/operations/state/', {'mode': 'draining'}).status_code,
            403,
        )

        self.client.force_login(self.admin)
        response = self.client.post(
            '/api/operations/state/',
            {'mode': 'draining', 'message': '20:30 开始维护'},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['mode'], 'draining')

    def test_draining_blocks_new_work_but_allows_reads(self):
        set_system_state('draining', message='即将维护', user=self.admin)
        self.client.force_login(self.user)

        blocked = self.client.post(
            '/api/projects/', {'name': 'blocked'}, content_type='application/json'
        )
        self.assertEqual(blocked.status_code, 503)
        self.assertEqual(blocked.json()['code'], 'SYSTEM_DRAINING')
        self.assertEqual(self.client.get('/api/projects/').status_code, 200)

    def test_maintenance_blocks_regular_api_but_not_admin(self):
        set_system_state('maintenance', message='升级中', user=self.admin)
        self.client.force_login(self.user)
        response = self.client.get('/api/projects/')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['code'], 'SYSTEM_MAINTENANCE')

        self.client.force_login(self.admin)
        self.assertEqual(self.client.get('/api/projects/').status_code, 200)

    def test_internal_task_creation_is_blocked_while_draining(self):
        project = Project.objects.create(name='运维测试', owner=self.user)
        set_system_state('draining', user=self.admin)
        with self.assertRaisesMessage(RuntimeError, '暂时不能启动新任务'):
            create_step_task(project.id, 'ai_screen', self.user.id, {})

    def test_readiness_requires_dependencies_and_respects_maintenance(self):
        with patch('core.operations.services._get_redis') as redis_client:
            redis_client.return_value.ping.return_value = True
            self.assertEqual(self.client.get('/api/health/ready/').status_code, 200)
            set_system_state('maintenance', user=self.admin)
            self.assertEqual(self.client.get('/api/health/ready/').status_code, 503)
            self.assertEqual(
                self.client.get('/api/health/ready/?allow_maintenance=1').status_code,
                200,
            )


class OperationsStatusTests(TestCase):
    def test_admin_status_contains_presence_tasks_sessions_and_safety(self):
        admin = User.objects.create_superuser('root-operator', password='pw')
        self.client.force_login(admin)
        with patch(
            'core.operations.services.get_presence_snapshot',
            return_value={
                'redis_available': True,
                'online_users': 0,
                'active_tabs': 0,
                'recent_users': 0,
                'users': [],
            },
        ), patch(
            'core.operations.services._celery_snapshot',
            return_value={'available': True, 'workers': 1, 'active': 0, 'reserved': 0, 'scheduled': 0},
        ):
            response = self.client.get('/api/operations/status/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['safe_to_stop'])
        self.assertIn('presence', payload)
        self.assertIn('task_counts', payload)
        self.assertIn('sessions', payload)

    def test_idle_platform_is_safe_before_service_processes_are_stopped(self):
        with patch(
            'core.operations.services.get_presence_snapshot',
            return_value={
                'redis_available': True,
                'online_users': 0,
                'active_tabs': 0,
                'recent_users': 0,
                'users': [],
            },
        ), patch(
            'core.operations.services.get_system_state',
            return_value={'mode': 'draining', 'message': '', 'scheduled_at': None},
        ):
            snapshot = get_operations_snapshot(inspect_celery=False)

        self.assertTrue(snapshot['safe_to_stop'])
        self.assertIsNone(snapshot['celery']['available'])

    def test_snapshot_uses_bounded_metadata_queries_without_large_task_fields(self):
        user = User.objects.create_user('snapshot-user', password='pw')
        project = Project.objects.create(name='Snapshot project', owner=user)
        Task.objects.create(
            project=project,
            task_type='ai_screen',
            status='running',
            created_by=user,
            config={'large': 'x' * 10000},
            logs='x' * 10000,
        )
        Task.objects.bulk_create([
            Task(
                project=project,
                task_type='ai_screen',
                status='queuing',
                created_by=user,
            )
            for _ in range(100)
        ])
        with patch(
            'core.operations.services.get_presence_snapshot',
            return_value={
                'redis_available': True,
                'online_users': 0,
                'active_tabs': 0,
                'recent_users': 0,
                'users': [],
            },
        ), patch(
            'core.operations.services.get_system_state',
            return_value={'mode': 'normal', 'message': '', 'scheduled_at': None},
        ), self.assertNumQueries(3):
            snapshot = get_operations_snapshot(inspect_celery=False)

        self.assertEqual(snapshot['active_task_count'], 101)
        self.assertEqual(snapshot['task_counts'], {'queuing': 100, 'running': 1})
        self.assertEqual(len(snapshot['tasks']), 100)
        self.assertTrue(snapshot['tasks_truncated'])
        self.assertFalse(snapshot['safe_to_stop'])
        self.assertNotIn('config', snapshot['tasks'][0])


class MaintenanceTaskTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('maintenance-user', password='pw')
        self.project = Project.objects.create(name='维护任务项目', owner=self.user)

    def test_pause_marks_only_resumable_long_tasks(self):
        ai_task = Task.objects.create(
            project=self.project, task_type='ai_screen', status='running', created_by=self.user,
        )
        Task.objects.create(
            project=self.project, task_type='dedup', status='running', created_by=self.user,
        )
        with patch('core.scheduler.TaskScheduler.stop_task', return_value=True) as stop:
            result = pause_long_running_tasks()

        self.assertEqual(result['paused'], [ai_task.id])
        stop.assert_called_once_with(ai_task.id)
        ai_task.refresh_from_db()
        self.assertTrue(ai_task.config['paused_by_maintenance'])

    def test_resume_dispatches_maintenance_task_with_privileged_bypass(self):
        old_task = Task.objects.create(
            project=self.project,
            task_type='qa_eval',
            status='stopped',
            created_by=self.user,
            config={'paused_by_maintenance': True},
        )
        with patch(
            'core.scheduler.TaskScheduler.resume_task',
            return_value=SimpleNamespace(id=99),
        ) as resume:
            result = resume_maintenance_tasks()

        self.assertEqual(result['resumed'], [{'old_task_id': old_task.id, 'new_task_id': 99}])
        resume.assert_called_once_with(old_task.id, maintenance_resume=True)

    def test_qa_maintenance_resume_skips_completed_and_resets_unprocessed(self):
        completed = QAReference.objects.create(
            project=self.project,
            title='已完成',
            quality_method='QUADAS2',
            ai_eval_status='completed',
        )
        pending = QAReference.objects.create(
            project=self.project,
            title='待恢复',
            quality_method='QUADAS2',
            ai_eval_status='pending',
        )
        executor = SimpleNamespace(
            config={
                'ref_ids': [completed.id, pending.id],
                'model_ids': ['model-1'],
                'resume_incomplete_only': True,
            },
            logger=MagicMock(),
            workspace=None,
            project_obj=self.project,
            task_obj=None,
            step_obj=None,
            stage_obj=None,
            project_id=self.project.id,
            check_stop_signal=MagicMock(return_value=True),
        )
        with patch('core.quality.executors.qa_eval.QAEvalHandler'):
            result = QAEvalStepHandler(executor).execute()

        self.assertTrue(result)
        completed.refresh_from_db()
        pending.refresh_from_db()
        self.assertEqual(completed.ai_eval_status, 'completed')
        self.assertEqual(pending.ai_eval_status, 'pending')

    def test_startup_reconciliation_preserves_resumable_work(self):
        ai_task = Task.objects.create(
            project=self.project,
            task_type='ai_screen',
            status='running',
            created_by=self.user,
        )
        parse_task = Task.objects.create(
            project=self.project,
            task_type='parse',
            status='running',
            created_by=self.user,
        )
        qa_task = Task.objects.create(
            project=self.project,
            task_type='qa_eval',
            status='running',
            created_by=self.user,
            config={'ref_ids': []},
        )
        qa_ref = QAReference.objects.create(
            project=self.project,
            title='中断评价',
            quality_method='QUADAS2',
            ai_eval_status='running',
        )

        preview = reconcile_interrupted_tasks(apply=False)
        self.assertEqual(len(preview['found']), 3)
        ai_task.refresh_from_db()
        self.assertEqual(ai_task.status, 'running')

        with patch('core.services.concurrency_service.reset_slots') as reset_slots:
            applied = reconcile_interrupted_tasks(apply=True)

        self.assertEqual(len(applied['repaired']), 3)
        reset_slots.assert_called_once_with(force=False)
        ai_task.refresh_from_db()
        parse_task.refresh_from_db()
        qa_task.refresh_from_db()
        qa_ref.refresh_from_db()
        self.assertEqual(ai_task.status, 'stopped')
        self.assertTrue(ai_task.config['paused_by_maintenance'])
        self.assertEqual(qa_task.status, 'stopped')
        self.assertEqual(qa_ref.ai_eval_status, 'pending')
        self.assertEqual(parse_task.status, 'failed')
