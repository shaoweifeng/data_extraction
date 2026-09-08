"""阶段 Pipeline 和模块任务归属测试。"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from core.models import Project, Task
from core.quality.tasks import parse_qa_pdf_meta
from core.services.project_service import initialize_project
from core.workflow.domain.statuses import ProjectStageStatus


User = get_user_model()


class PipelineBoundaryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('pipeline-user', password='pw')
        self.project = Project.objects.create(name='Pipeline 项目', owner=self.user)
        initialize_project(self.project, self.user)
        self.client = Client()
        self.client.force_login(self.user)

    def test_unimplemented_pipeline_stage_returns_400_without_creating_task(self):
        stage = self.project.stages.get(stage_key='SCREEN_1')

        response = self.client.post(
            f'/api/stages/{stage.id}/start/',
            {'config': {}},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('Pipeline 尚未实现', response.json()['error'])
        self.assertFalse(Task.objects.filter(project=self.project, task_type='SCREEN_1').exists())
        stage.refresh_from_db()
        self.assertEqual(stage.status, ProjectStageStatus.PENDING)


class QualityTaskOwnershipTests(TestCase):
    def test_pdf_metadata_task_is_owned_by_quality_module(self):
        with patch('core.quality.executors.qa_eval.extract_pdf_meta') as extract:
            parse_qa_pdf_meta.run(42)

        extract.assert_called_once_with(42)
        self.assertEqual(parse_qa_pdf_meta.name, 'core.quality.tasks.parse_qa_pdf_meta')
