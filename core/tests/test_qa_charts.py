"""QA 图表数据的语义 golden tests。"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

from core.models import DataFile, Project, QADomainResult, QAReference, Task
from core.services.project_service import initialize_project


User = get_user_model()
FIXTURES = Path(__file__).parent / 'fixtures'


class QaChartDataGoldenTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('chart-user')
        self.project = Project.objects.create(name='Chart project', owner=self.user)

    def add_domain(self, ref, domain, bias, applicability='na'):
        QADomainResult.objects.create(
            qa_ref=ref,
            domain=domain,
            domain_name=domain,
            bias_risk_result=bias,
            applicability_result=applicability,
            bias_all_confirmed=bias != 'pending',
            applicability_all_confirmed=applicability != 'pending',
        )

    def test_quadas2_chart_data_matches_golden(self):
        from core.quality.services.chart_data import build_chart_data

        confirmed = QAReference.objects.create(
            project=self.project,
            title='Confirmed Study',
            quality_method='QUADAS2',
            review_status='confirmed',
        )
        QAReference.objects.create(
            project=self.project,
            title='Pending Study',
            quality_method='QUADAS2',
            review_status='partial',
        )
        self.add_domain(confirmed, 'patient_selection', 'low', 'low')
        self.add_domain(confirmed, 'index_test', 'high', 'high')
        self.add_domain(confirmed, 'reference_standard', 'unclear', 'unclear')
        self.add_domain(confirmed, 'flow_timing', 'low')

        traffic, proportion, _, _, _ = build_chart_data(self.project, 'QUADAS2')
        normalized_traffic = [
            {
                'title': row['title'],
                'review_status': row['review_status'],
                'bias_risk': row['bias_risk'],
                'applicability': row['applicability'],
            }
            for row in traffic
        ]
        normalized_proportion = {
            key: value['counts'] for key, value in proportion.items()
        }
        actual = {
            'traffic_light': normalized_traffic,
            'proportion': normalized_proportion,
        }
        expected = json.loads((FIXTURES / 'golden' / 'chart_data.json').read_text(encoding='utf-8'))
        self.assertEqual(actual, expected)
        self.assertEqual(proportion['patient_selection']['result_type'], 'bias_risk')
        self.assertEqual(proportion['app_patient_selection']['result_type'], 'applicability')

    def test_chart_generate_endpoint_enqueues_unified_task(self):
        initialize_project(self.project, self.user)
        ref = QAReference.objects.create(
            project=self.project,
            title='Queued chart study',
            quality_method='QUADAS2',
            review_status='confirmed',
        )
        client = Client()
        client.force_login(self.user)
        queued_task = Task.objects.create(
            project=self.project,
            task_type='qa_chart',
            status='running',
            created_by=self.user,
        )

        with patch('core.scheduler.TaskScheduler.start_step', return_value=queued_task) as start:
            response = client.post(
                '/api/qa/chart/generate/',
                {
                    'project_id': self.project.id,
                    'quality_method': 'QUADAS2',
                    'ref_ids': [ref.id],
                    'study_labels': {},
                    'orientation': 'horizontal',
                    'lang': 'zh',
                },
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()['data'], {'task_id': queued_task.id, 'status': 'running'})
        self.assertEqual(start.call_args.args[:2], ('qa_chart', self.user.id))

    def test_chart_handler_persists_png_artifacts_and_task_result(self):
        initialize_project(self.project, self.user)
        ref = QAReference.objects.create(
            project=self.project,
            title='Rendered chart study',
            quality_method='QUADAS2',
            review_status='confirmed',
        )
        self.add_domain(ref, 'patient_selection', 'low', 'low')
        task = Task.objects.create(
            project=self.project,
            task_type='qa_chart',
            status='pending',
            created_by=self.user,
            config={
                'quality_method': 'QUADAS2',
                'ref_ids': [ref.id],
                'study_labels': {str(ref.id): 'Rendered Study'},
                'orientation': 'horizontal',
                'lang': 'en',
            },
        )

        with tempfile.TemporaryDirectory() as temp_dir, override_settings(
            BASE_DIR=Path(temp_dir), MEDIA_ROOT=Path(temp_dir) / 'media'
        ):
            from core.executors.executor import StepExecutor

            executor = StepExecutor(task.id, 'qa_chart', self.project.id)
            executor.config.update(task.config)
            executor.initialize()
            success = executor.execute()
            executor.finalize(success)

        self.assertTrue(success)
        task.refresh_from_db()
        self.assertEqual(task.status, 'completed')
        self.assertTrue(task.result['traffic_light_image'])
        self.assertTrue(task.result['proportion_image'])
        artifacts = DataFile.objects.filter(project=self.project, step__step_key='qa_chart')
        self.assertEqual(artifacts.count(), 2)
        self.assertEqual(
            set(artifacts.values_list('metadata__artifact_type', flat=True)),
            {'qa_traffic_light_png', 'qa_proportion_png'},
        )

    def test_traffic_light_symbols_use_enlarged_font(self):
        from core.quality.renderers.matplotlib_charts import (
            _SYMBOL_FONT_SIZE,
            _draw_traffic_light_matrix,
        )

        axis = MagicMock()
        _draw_traffic_light_matrix(
            axis,
            studies=['High', 'Unclear', 'Low'],
            rows=[{'label': 'Domain', 'values': ['High', 'Unclear', 'Low']}],
            n_bias=1,
        )

        symbol_calls = [
            call for call in axis.text.call_args_list
            if len(call.args) >= 3 and call.args[2] in {'×', '?', '+'}
        ]
        self.assertEqual(len(symbol_calls), 3)
        self.assertTrue(all(call.kwargs['fontsize'] == _SYMBOL_FONT_SIZE for call in symbol_calls))
        self.assertGreaterEqual(_SYMBOL_FONT_SIZE, 12)

    def test_traffic_light_markers_stay_circular_for_all_layouts_and_label_lengths(self):
        import matplotlib.pyplot as plt

        from core.quality.renderers.matplotlib_charts import (
            _CIRCLE_MARKER_SIZE,
            _draw_traffic_light_matrix,
        )

        label_sets = [
            ['A', 'B'],
            ['A very long custom study name that changes the axes layout', 'Short'],
        ]
        rows = [
            {'label': 'Domain 1', 'values': ['High', 'Low']},
            {'label': 'Domain 2', 'values': ['Unclear', 'High']},
        ]

        for orientation in ('horizontal', 'vertical'):
            for studies in label_sets:
                with self.subTest(orientation=orientation, studies=studies):
                    fig, axis = plt.subplots(figsize=(11, 4))
                    _draw_traffic_light_matrix(
                        axis,
                        studies=studies,
                        rows=rows,
                        n_bias=1,
                        orientation=orientation,
                    )
                    fig.tight_layout()
                    fig.canvas.draw()

                    self.assertEqual(len(axis.collections), 4)
                    for marker in axis.collections:
                        self.assertEqual(marker.get_sizes().tolist(), [_CIRCLE_MARKER_SIZE])
                        marker_transform = marker.get_transforms()[0]
                        self.assertAlmostEqual(
                            abs(marker_transform[0, 0]),
                            abs(marker_transform[1, 1]),
                        )
                    plt.close(fig)
