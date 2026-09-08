"""项目隔离、管理员可见性与 CSRF 长期回归测试。"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from core.models import ManualReview, Project, QAChart, QAChartSettings, QAReference
from core.services.access_policy import ProjectAccessPolicy
from core.services.project_service import initialize_project


User = get_user_model()


class AccessFixture(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('owner', password='pw')
        self.other = User.objects.create_user('other', password='pw')
        self.admin = User.objects.create_user('admin', password='pw')
        self.admin.profile.role = 'admin'
        self.admin.profile.save(update_fields=['role'])

        self.project = Project.objects.create(name='所有者项目', owner=self.owner)
        self.other_project = Project.objects.create(name='其他项目', owner=self.other)
        initialize_project(self.project, self.owner)
        initialize_project(self.other_project, self.other)
        self.review_step = self.project.stages.get(stage_key='SCREEN_1').steps.get(step_key='review')

    def login(self, user, enforce_csrf=False):
        client = Client(enforce_csrf_checks=enforce_csrf)
        client.force_login(user)
        return client


class ProjectAccessPolicyTests(AccessFixture):
    def test_normal_user_sees_only_owned_projects(self):
        self.assertQuerySetEqual(
            ProjectAccessPolicy.visible_projects(self.owner).order_by('id'),
            [self.project],
        )

    def test_admin_sees_all_projects(self):
        self.assertEqual(ProjectAccessPolicy.visible_projects(self.admin).count(), 2)

    def test_nested_resources_are_not_visible_across_projects(self):
        client = self.login(self.owner)
        foreign_step = self.other_project.stages.get(stage_key='SCREEN_1').steps.get(step_key='review')
        self.assertEqual(client.get(f'/api/steps/{foreign_step.id}/').status_code, 404)
        self.assertEqual(
            client.get('/api/review/list/', {'project': self.other_project.id, 'step': foreign_step.id}).status_code,
            404,
        )

    def test_admin_can_access_another_users_qa(self):
        client = self.login(self.admin)
        response = client.get('/api/qa/refs/', {'project_id': self.project.id})
        self.assertEqual(response.status_code, 200)

    def test_qa_reference_cannot_be_updated_by_unrelated_user(self):
        ref = QAReference.objects.create(project=self.project, title='私有文献')
        client = self.login(self.other)
        response = client.patch(
            f'/api/qa/refs/{ref.id}/',
            data='{"title": "changed"}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 404)
        ref.refresh_from_db()
        self.assertEqual(ref.title, '私有文献')

    def test_user_detail_does_not_expose_other_users(self):
        client = self.login(self.owner)
        self.assertEqual(client.get(f'/api/users/{self.other.id}/').status_code, 404)
        self.assertEqual(self.login(self.admin).get(f'/api/users/{self.other.id}/').status_code, 200)


class QaAndCsrfContractTests(AccessFixture):
    def test_import_clears_all_current_qa_results(self):
        QAReference.objects.create(project=self.project, title='旧文献')
        QAChart.objects.create(project=self.project, quality_method='QUADAS2')
        QAChartSettings.objects.create(
            project=self.project,
            quality_method='QUADAS2',
            study_labels={'1': '旧名称'},
        )
        client = self.login(self.owner)
        with patch('core.quality.services.reference_service.load_ai_results', return_value=[]):
            response = client.post(
                '/api/qa/refs/import/',
                data={'project_id': self.project.id, 'source_stage': 'SCREEN_1'},
                content_type='application/json',
            )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(QAReference.objects.filter(project=self.project).exists())
        self.assertFalse(QAChart.objects.filter(project=self.project).exists())
        self.assertFalse(QAChartSettings.objects.filter(project=self.project).exists())

    def test_session_write_endpoint_requires_csrf_token(self):
        client = self.login(self.owner, enforce_csrf=True)
        response = client.post(
            '/api/review/complete/',
            data={'project': self.project.id, 'step': self.review_step.id},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 403)

    def test_unreviewed_items_count_as_ai_correct(self):
        ManualReview.objects.create(
            project=self.project,
            step=self.review_step,
            source_xml='reviewed.xml',
            ai_decision='included',
            decision='included',
            reviewer=self.owner,
        )
        ai_results = [
            {'source_xml': 'reviewed.xml', 'decision': 'included'},
            {'source_xml': 'unreviewed.xml', 'decision': 'excluded'},
        ]
        with patch('core.screening.api.review_views.load_ai_results', return_value=ai_results):
            response = self.login(self.owner).get('/api/review/stats/', {'project': self.project.id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['ai_accuracy'], 100.0)
