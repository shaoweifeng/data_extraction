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

    def test_proportion_renderer_keeps_bias_and_applicability_separate(self):
        import matplotlib.pyplot as plt

        from core.quality.renderers.matplotlib_charts import render_proportion

        domain = {'key': 'patient_selection', 'name': '患者选择'}
        proportion = {
            'patient_selection': {
                'result_type': 'bias_risk',
                'counts': {'high': 0, 'unclear': 0, 'low': 2, 'pending': 0},
            },
            'app_patient_selection': {
                'result_type': 'applicability',
                'counts': {'high': 2, 'unclear': 0, 'low': 0, 'pending': 0},
            },
        }

        try:
            with (
                patch('core.quality.renderers.matplotlib_charts._init_cjk_font'),
                patch('core.quality.renderers.matplotlib_charts._draw_summary_bar') as draw_bar,
                patch('core.quality.renderers.matplotlib_charts._draw_legend'),
                patch('core.quality.renderers.matplotlib_charts._fig_to_b64', return_value='image'),
            ):
                result = render_proportion(
                    proportion,
                    'QUADAS-2',
                    bias_domains=[domain],
                    applic_domains=[domain],
                )
        finally:
            plt.close('all')

        self.assertEqual(result, 'image')
        self.assertEqual(draw_bar.call_count, 2)
        bias_summary = draw_bar.call_args_list[0].args[1].iloc[0]
        applic_summary = draw_bar.call_args_list[1].args[1].iloc[0]
        self.assertEqual((bias_summary['Low'], bias_summary['High']), (1, 0))
        self.assertEqual((applic_summary['Low'], applic_summary['High']), (0, 1))

    def test_pending_and_not_applicable_remain_distinct(self):
        from core.quality.services.chart_data import build_chart_data

        ref = QAReference.objects.create(
            project=self.project,
            title='Explicit states',
            quality_method='QUADAS2',
            review_status='confirmed',
        )
        self.add_domain(ref, 'patient_selection', 'pending', 'na')

        traffic, proportion, _, _, _ = build_chart_data(self.project, 'QUADAS2')

        self.assertEqual(traffic[0]['bias_risk']['patient_selection'], 'pending')
        self.assertEqual(traffic[0]['applicability']['patient_selection'], 'na')
        self.assertEqual(proportion['patient_selection']['counts']['pending'], 1)
        self.assertEqual(proportion['app_patient_selection']['counts']['na'], 1)

    def test_traffic_light_omits_applicability_group_when_method_has_none(self):
        from core.quality.renderers.matplotlib_charts import _draw_traffic_light_matrix

        for orientation in ('horizontal', 'vertical'):
            with self.subTest(orientation=orientation):
                axis = MagicMock()
                _draw_traffic_light_matrix(
                    axis,
                    studies=['Study'],
                    rows=[{'label': 'Selection', 'values': ['Low']}],
                    n_bias=1,
                    orientation=orientation,
                )
                labels = [
                    call.args[2] for call in axis.text.call_args_list
                    if len(call.args) >= 3
                ]
                self.assertNotIn('适用性问题', labels)
                axis.plot.assert_not_called()

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

    def test_traffic_light_truncates_long_custom_labels_by_display_width(self):
        import unicodedata

        from core.quality.renderers.matplotlib_charts import (
            _MAX_STUDY_LABEL_WIDTH,
            _get_study_label,
        )

        label = _get_study_label(
            {'ref_id': 7, 'title': 'Fallback'},
            {'7': '这是一个特别长的中文文献标题 mixed with a very long English title'},
        )

        display_width = sum(
            2 if unicodedata.east_asian_width(char) in {'W', 'F'} else 1
            for char in label
        )
        self.assertLessEqual(display_width, _MAX_STUDY_LABEL_WIDTH)
        self.assertTrue(label.endswith('…'))

    def test_traffic_light_prefers_title_over_unreliable_author_metadata(self):
        from core.quality.renderers.matplotlib_charts import _get_study_label

        row = {
            'ref_id': 7,
            'title': '正常的文献标题',
            'first_author': 'CNKI',
            'year': None,
        }

        self.assertEqual(
            _get_study_label(row, {'7': row['title']}),
            '正常的文献标题',
        )

    def test_rendered_traffic_light_keeps_marker_rows_apart_with_long_labels(self):
        import matplotlib.pyplot as plt

        from core.quality.renderers.matplotlib_charts import (
            _CIRCLE_MARKER_SIZE,
            render_traffic_light,
        )

        traffic = [{
            'ref_id': 1,
            'title': 'A study title',
            'bias_risk': {'d1': 'high', 'd2': 'low', 'd3': 'unclear'},
            'applicability': {},
        }]
        domains = [
            {'key': 'd1', 'name': '领域一'},
            {'key': 'd2', 'name': '领域二'},
            {'key': 'd3', 'name': '领域三'},
        ]
        captured = {}

        def inspect_figure(fig):
            fig.canvas.draw()
            axis = fig.axes[0]
            first = axis.transData.transform((0, 0))[1]
            second = axis.transData.transform((0, 1))[1]
            captured['row_spacing_px'] = abs(second - first)
            captured['marker_diameter_px'] = (
                _CIRCLE_MARKER_SIZE ** 0.5 * fig.dpi / 72
            )
            plt.close(fig)
            return 'image'

        with (
            patch('core.quality.renderers.matplotlib_charts._init_cjk_font'),
            patch('core.quality.renderers.matplotlib_charts._fig_to_b64', side_effect=inspect_figure),
        ):
            result = render_traffic_light(
                traffic,
                domains,
                [],
                'Method',
                study_labels={'1': '非常长的文献名称' * 20},
                orientation='horizontal',
            )

        self.assertEqual(result, 'image')
        self.assertGreater(captured['row_spacing_px'], captured['marker_diameter_px'] * 1.15)
