"""OpenAPI 可用性和前端依赖的响应形状契约。"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from core.models import Project, QAReference
from core.services.project_service import initialize_project


User = get_user_model()


class OpenApiContractTests(TestCase):
    FRONTEND_CRITICAL_PATHS = {
        '/projects/',
        '/projects/{id}/stages/',
        '/tasks/',
        '/tasks/{id}/stop/',
        '/tasks/{id}/resume/',
        '/files/',
        '/review/list/',
        '/review/stats/',
        '/review/complete/',
        '/qa/methods/',
        '/qa/refs/',
        '/qa/refs/import/',
        '/qa/eval/start/',
        '/qa/eval/progress/',
        '/qa/signal-items/',
        '/qa/domain-results/',
        '/qa/chart/preview/',
        '/qa/chart/generate/',
        '/qa/export/excel/',
        '/billing/balance/',
    }

    def test_schema_is_public_valid_json_and_covers_frontend_paths(self):
        response = Client().get('/api/schema/')
        self.assertEqual(response.status_code, 200)
        schema = response.json()
        self.assertEqual(schema['openapi'], '3.0.3')
        self.assertIn('schemas', schema['components'])
        self.assertTrue(self.FRONTEND_CRITICAL_PATHS.issubset(schema['paths']))
        for path, path_item in schema['paths'].items():
            methods = {'get', 'post', 'put', 'patch', 'delete'} & set(path_item)
            self.assertTrue(methods, f'{path} 缺少 HTTP operation')
            for method in methods:
                self.assertIn('responses', path_item[method], f'{method.upper()} {path} 缺少 responses')


class FrontendResponseShapeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('contract-user', password='pw')
        self.project = Project.objects.create(name='Contract project', owner=self.user)
        initialize_project(self.project, self.user)
        self.review_step = self.project.stages.get(stage_key='SCREEN_1').steps.get(step_key='review')
        self.client = Client()
        self.client.force_login(self.user)

    def test_project_list_keeps_drf_pagination_shape(self):
        data = self.client.get('/api/projects/').json()
        self.assertEqual(set(data), {'count', 'next', 'previous', 'results'})
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['results'][0]['id'], self.project.id)

    def test_empty_qa_collection_remains_an_array(self):
        response = self.client.get('/api/qa/refs/', {'project_id': self.project.id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'ok': True, 'data': []})

    def test_review_list_shape_matches_frontend_store(self):
        with patch('core.screening.api.review_views.load_ai_results', return_value=[]):
            response = self.client.get(
                '/api/review/list/',
                {'project': self.project.id, 'step': self.review_step.id},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {'total': 0, 'page': 1, 'page_size': 50, 'results': []},
        )

    def test_qa_method_envelope_contains_array(self):
        data = self.client.get('/api/qa/methods/').json()
        self.assertTrue(data['ok'])
        self.assertIsInstance(data['data'], list)
        self.assertEqual(len(data['data']), 5)

    def test_qa_eval_start_accepts_legacy_null_eval_mode(self):
        """兼容旧前端提交的 eval_mode=null，不应在参数校验阶段失败。"""
        qa_ref = QAReference.objects.create(
            project=self.project,
            title='待评价文献',
            quality_method='QUADAS2',
        )
        result = {'task_id': 101, 'evaluable_count': 1, 'ref_ids': [qa_ref.id]}

        with patch(
            'core.quality.services.evaluation_service.start_evaluation',
            return_value=result,
        ) as start_evaluation:
            response = self.client.post(
                '/api/qa/eval/start/',
                data={
                    'project_id': self.project.id,
                    'ref_ids': [qa_ref.id],
                    'model_ids': ['deepseek-v4-pro'],
                    'eval_mode': None,
                },
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data'], result)
        start_evaluation.assert_called_once()

    def test_qa_validation_errors_are_strings(self):
        response = self.client.post(
            '/api/qa/eval/start/',
            data={
                'project_id': self.project.id,
                'ref_ids': [],
                'model_ids': [],
            },
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIsInstance(response.json()['error'], str)
        self.assertIn('model_ids', response.json()['error'])
