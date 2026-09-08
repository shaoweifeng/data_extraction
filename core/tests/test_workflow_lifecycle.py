"""集中工作流状态机的转换矩阵和持久化测试。"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from core.models import Project, Task
from core.services.project_service import initialize_project
from core.workflow.domain.statuses import ProjectStageStatus, StageStepStatus, TaskStatus
from core.workflow.services.lifecycle import (
    InvalidStateTransition,
    can_transition_stage,
    can_transition_step,
    can_transition_task,
    transition_stage,
    transition_step,
    transition_task,
)


User = get_user_model()


class TransitionMatrixTests(TestCase):
    def test_task_transition_matrix_rejects_terminal_reentry(self):
        for terminal in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SUPERSEDED):
            with self.subTest(terminal=terminal):
                self.assertFalse(can_transition_task(terminal, TaskStatus.RUNNING))
                self.assertFalse(can_transition_task(terminal, TaskStatus.PENDING))

    def test_task_stop_and_resume_path_is_explicit(self):
        self.assertTrue(can_transition_task(TaskStatus.RUNNING, TaskStatus.STOPPING))
        self.assertTrue(can_transition_task(TaskStatus.STOPPING, TaskStatus.STOPPED))
        self.assertTrue(can_transition_task(TaskStatus.STOPPED, TaskStatus.SUPERSEDED))
        self.assertFalse(can_transition_task(TaskStatus.STOPPED, TaskStatus.RUNNING))

    def test_step_and_stage_terminal_rules_are_explicit(self):
        self.assertFalse(can_transition_step(StageStepStatus.COMPLETED, StageStepStatus.IN_PROGRESS))
        self.assertFalse(can_transition_stage(ProjectStageStatus.COMPLETED, ProjectStageStatus.IN_PROGRESS))
        self.assertTrue(can_transition_step(StageStepStatus.COMPLETED, StageStepStatus.PENDING))
        self.assertTrue(can_transition_stage(ProjectStageStatus.COMPLETED, ProjectStageStatus.PENDING))

    def test_same_state_transition_is_idempotent(self):
        self.assertTrue(can_transition_task(TaskStatus.RUNNING, TaskStatus.RUNNING))
        self.assertTrue(can_transition_step(StageStepStatus.PENDING, StageStepStatus.PENDING))
        self.assertTrue(can_transition_stage(ProjectStageStatus.PENDING, ProjectStageStatus.PENDING))

    def test_unknown_state_is_never_accepted(self):
        self.assertFalse(can_transition_task('unknown', 'unknown'))
        self.assertFalse(can_transition_step(StageStepStatus.PENDING, 'unknown'))
        self.assertFalse(can_transition_stage('unknown', ProjectStageStatus.PENDING))


class LifecyclePersistenceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('lifecycle-user', password='pw')
        self.project = Project.objects.create(name='状态机项目', owner=self.user)
        initialize_project(self.project, self.user)

    def test_transition_reloads_locked_row_instead_of_trusting_stale_instance(self):
        task = Task.objects.create(
            project=self.project,
            task_type='criteria',
            status=TaskStatus.PENDING,
            created_by=self.user,
        )
        stale = Task.objects.get(pk=task.pk)
        Task.objects.filter(pk=task.pk).update(status=TaskStatus.COMPLETED)

        with self.assertRaises(InvalidStateTransition) as error:
            transition_task(stale, TaskStatus.RUNNING)

        self.assertEqual(error.exception.current, TaskStatus.COMPLETED)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.COMPLETED)

    def test_transition_updates_status_and_related_fields_together(self):
        task = Task.objects.create(
            project=self.project,
            task_type='criteria',
            status=TaskStatus.PENDING,
            created_by=self.user,
        )

        transition_task(
            task,
            TaskStatus.RUNNING,
            updates={'celery_task_id': 'job-42', 'progress': 0.25},
            expected_from={TaskStatus.PENDING},
        )

        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.RUNNING)
        self.assertEqual(task.celery_task_id, 'job-42')
        self.assertEqual(task.progress, 0.25)

    def test_expected_source_protects_compare_and_set_semantics(self):
        task = Task.objects.create(
            project=self.project,
            task_type='criteria',
            status=TaskStatus.RUNNING,
            created_by=self.user,
        )

        with self.assertRaises(InvalidStateTransition):
            transition_task(
                task,
                TaskStatus.STOPPING,
                expected_from={TaskStatus.PENDING},
            )

        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.RUNNING)

    def test_step_and_stage_use_the_same_persistence_boundary(self):
        stage = self.project.stages.get(stage_key='SCREEN_1')
        step = stage.steps.get(step_key='criteria')

        transition_stage(stage, ProjectStageStatus.IN_PROGRESS)
        transition_step(step, StageStepStatus.IN_PROGRESS)

        stage.refresh_from_db()
        step.refresh_from_db()
        self.assertEqual(stage.status, ProjectStageStatus.IN_PROGRESS)
        self.assertEqual(step.status, StageStepStatus.IN_PROGRESS)


class StatusSerializerBoundaryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('serializer-user', password='pw')
        self.project = Project.objects.create(name='Serializer 项目', owner=self.user)
        initialize_project(self.project, self.user)
        self.client = Client()
        self.client.force_login(self.user)

    def test_generic_task_patch_cannot_bypass_state_machine(self):
        task = Task.objects.create(
            project=self.project,
            task_type='criteria',
            status=TaskStatus.PENDING,
            created_by=self.user,
        )

        response = self.client.patch(
            f'/api/tasks/{task.id}/',
            {'status': TaskStatus.COMPLETED, 'config': {'kept': True}},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.PENDING)
        self.assertEqual(task.config, {'kept': True})

    def test_generic_step_and_stage_patch_cannot_change_status(self):
        stage = self.project.stages.get(stage_key='SCREEN_1')
        step = stage.steps.get(step_key='criteria')

        step_response = self.client.patch(
            f'/api/steps/{step.id}/',
            {'status': StageStepStatus.COMPLETED, 'metadata': {'kept': True}},
            content_type='application/json',
        )
        stage_response = self.client.patch(
            f'/api/stages/{stage.id}/',
            {'status': ProjectStageStatus.COMPLETED, 'metadata': {'kept': True}},
            content_type='application/json',
        )

        self.assertEqual(step_response.status_code, 200)
        self.assertEqual(stage_response.status_code, 200)
        step.refresh_from_db()
        stage.refresh_from_db()
        self.assertEqual(step.status, StageStepStatus.PENDING)
        self.assertEqual(stage.status, ProjectStageStatus.PENDING)
        self.assertEqual(step.metadata, {'kept': True})
        self.assertEqual(stage.metadata, {'kept': True})

    def test_stage_start_moves_stage_to_in_progress_through_action(self):
        stage = self.project.stages.get(stage_key='SEARCH')
        task = Task.objects.create(
            project=self.project,
            task_type='SEARCH',
            status=TaskStatus.PENDING,
            created_by=self.user,
        )

        with patch('core.scheduler.TaskScheduler.start_stage', return_value=task):
            response = self.client.post(
                f'/api/stages/{stage.id}/start/',
                {'config': {}},
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        stage.refresh_from_db()
        self.assertEqual(stage.status, ProjectStageStatus.IN_PROGRESS)
        self.assertIsNotNone(stage.started_at)
