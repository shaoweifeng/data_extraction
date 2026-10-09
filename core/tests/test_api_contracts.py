"""OpenAPI 可用性和前端依赖的响应形状契约。"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from core.models import Project, QAReference, QASignalItem
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
        '/screening-imports/',
        '/screening-imports/{id}/',
        '/screening-imports/{id}/cancel/',
        '/screening-imports/{id}/retry/',
        '/projects/{project_id}/dedup-runs/{run_id}/groups/',
        '/projects/{project_id}/dedup-runs/{run_id}/groups/{group_id}/members/',
        '/review/list/',
        '/review/runs/{run_id}/references/{reference_id}/',
        '/review/runs/{run_id}/references/{reference_id}/notes/',
        '/review/stats/',
        '/review/complete/',
        '/qa/methods/',
        '/qa/refs/',
        '/qa/refs/import/',
        '/qa/refs/upload/',
        '/qa/fulltext-assets/{id}/download/',
        '/qa/fulltext-assets/{id}/retry/',
        '/qa/eval/start/',
        '/qa/eval/progress/',
        '/qa/eval/audit/',
        '/qa/signal-items/',
        '/qa/signal-items/{id}/evidence-context/',
        '/qa/review/batch-confirm/',
        '/qa/domain-results/',
        '/qa/chart/preview/',
        '/qa/chart/generate/',
        '/qa/export/excel/',
        '/billing/balance/',
        '/health/live/',
        '/health/ready/',
        '/system/status/',
        '/presence/heartbeat/',
        '/operations/status/',
        '/operations/state/',
        '/operations/announcement/',
        '/operations/tasks/pause/',
        '/operations/tasks/resume/',
        '/feedback/',
        '/feedback/attachments/{attachment_id}/',
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

    def test_qa_reference_list_supports_server_pagination_and_reviewable_filter(self):
        pending = QAReference.objects.create(project=self.project, title='未评价')
        reviewed = QAReference.objects.create(
            project=self.project,
            title='已评价',
            quality_method='QUADAS2',
            ai_eval_status='completed',
        )
        QASignalItem.objects.create(
            qa_ref=reviewed,
            quality_method='QUADAS2',
            domain='patient_selection',
            result_type='bias_risk',
            signal_key='PS1',
            signal_question='是否连续纳入？',
            options=['是', '否'],
            pre_selected='是',
        )

        response = self.client.get('/api/qa/refs/', {
            'project_id': self.project.id,
            'page': 1,
            'page_size': 10,
            'view': 'reviewable',
        })

        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertEqual(data['count'], 1)
        self.assertEqual([item['id'] for item in data['results']], [reviewed.id])
        self.assertEqual(data['summary']['total'], 2)
        self.assertEqual(data['summary']['reviewable'], 1)
        self.assertNotEqual(pending.id, reviewed.id)

    def test_eval_progress_omits_plain_pending_rows_and_reports_each_status(self):
        QAReference.objects.create(project=self.project, title='未进入任务')
        QAReference.objects.create(
            project=self.project, title='摘要完成', ai_eval_status='abstract_only'
        )
        QAReference.objects.create(
            project=self.project, title='缺少方法', ai_eval_status='skipped_no_method'
        )

        response = self.client.get('/api/qa/eval/progress/', {'project_id': self.project.id})

        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertEqual(data['summary']['pending'], 1)
        self.assertEqual(data['summary']['abstract_only'], 1)
        self.assertEqual(data['summary']['skipped_no_method'], 1)
        self.assertEqual(len(data['refs']), 2)
        self.assertNotIn('未进入任务', [item['title'] for item in data['refs']])

    def test_project_batch_confirm_only_processes_evaluated_references(self):
        evaluated = QAReference.objects.create(
            project=self.project,
            title='已有结果',
            quality_method='QUADAS2',
            ai_eval_status='completed',
        )
        unevaluated = QAReference.objects.create(
            project=self.project,
            title='未评价',
            quality_method='QUADAS2',
            ai_eval_status='pending',
        )
        evaluated_item = QASignalItem.objects.create(
            qa_ref=evaluated,
            quality_method='QUADAS2',
            domain='patient_selection',
            result_type='bias_risk',
            signal_key='PS1',
            signal_question='问题',
            options=['是', '否'],
            pre_selected='是',
        )
        existing_human_item = QASignalItem.objects.create(
            qa_ref=evaluated,
            quality_method='QUADAS2',
            domain='patient_selection',
            result_type='bias_risk',
            signal_key='PS2',
            signal_question='已人工修改的问题',
            options=['是', '否'],
            pre_selected='是',
            human_judgment='否',
            is_confirmed=True,
        )
        pending_item = QASignalItem.objects.create(
            qa_ref=unevaluated,
            quality_method='QUADAS2',
            domain='patient_selection',
            result_type='bias_risk',
            signal_key='PS1',
            signal_question='问题',
            options=['是', '否'],
            pre_selected='是',
        )

        response = self.client.post(
            '/api/qa/review/batch-confirm/',
            {'project_id': self.project.id, 'confirm_mode': 'adopt_preselected'},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data'], {'references': 1, 'signals': 1})
        evaluated_item.refresh_from_db()
        existing_human_item.refresh_from_db()
        pending_item.refresh_from_db()
        self.assertTrue(evaluated_item.is_confirmed)
        self.assertEqual(existing_human_item.human_judgment, '否')
        self.assertFalse(pending_item.is_confirmed)

    def test_review_list_shape_matches_frontend_store(self):
        response = self.client.get(
            '/api/review/list/',
            {'project': self.project.id, 'step': self.review_step.id},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                'total': 0,
                'page': 1,
                'page_size': 50,
                'results': [],
                'storage_mode': 'database',
                'screening_run_id': None,
                'corpus_revision': None,
                'is_current': True,
            },
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
