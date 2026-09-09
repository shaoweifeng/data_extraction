"""初筛最终决策、人工复核统计和 QA 导入规则。"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from core.artifacts.types import ArtifactType
from core.artifacts.services import get_ai_screen_stats
from core.models import DataFile, ManualReview, Project, QAReference
from core.services.project_service import initialize_project
from core.workflow.domain.statuses import StageStepStatus


User = get_user_model()


class ScreeningDecisionContractTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('decision-user', password='pw')
        self.project = Project.objects.create(name='决策契约项目', owner=self.user)
        initialize_project(self.project, self.user)
        self.review_step = self.project.stages.get(stage_key='SCREEN_1').steps.get(step_key='review')
        self.client = Client()
        self.client.force_login(self.user)

    def add_review(self, source_xml, decision, ai_decision, is_override):
        return ManualReview.objects.create(
            project=self.project,
            step=self.review_step,
            source_xml=source_xml,
            decision=decision,
            ai_decision=ai_decision,
            is_override=is_override,
            reviewer=self.user,
        )

    def add_result(self, source_xml, decision='', consensus=None, title=''):
        ai_step = self.project.stages.get(stage_key='SCREEN_1').steps.get(step_key='ai_screen')
        metadata = {
            'artifact_type': ArtifactType.SCREENING_RESULT_JSON,
            'source_xml': source_xml,
            'decision': decision,
            'consensus': consensus or decision or 'pending',
            'title': title or source_xml,
        }
        return DataFile.objects.create(
            project=self.project,
            stage=ai_step.stage,
            step=ai_step,
            filename=f'screening_result_{source_xml}.json',
            file='',
            data_category='output',
            source='tool_generated',
            description='AI筛选结果',
            metadata=metadata,
            created_by=self.user,
        )

    def test_qa_import_uses_human_decision_before_ai(self):
        excluded_by_human = self.add_review('a.xml', 'excluded', 'included', True)
        included_by_human = self.add_review('b.xml', 'included', 'excluded', True)
        self.assertIsNotNone(excluded_by_human.pk)
        ai_results = [
            {'source_xml': 'a.xml', 'title': 'AI include, human exclude', 'decision': 'included'},
            {'source_xml': 'b.xml', 'title': 'AI exclude, human include', 'decision': 'excluded'},
            {'source_xml': 'c.xml', 'title': 'Conflict', 'consensus': 'conflict'},
            {'source_xml': 'd.xml', 'title': 'Legacy include', 'include_or_not': 'yes'},
        ]

        with patch('core.quality.services.reference_service.load_ai_results', return_value=ai_results):
            response = self.client.post(
                '/api/qa/refs/import/',
                {'project_id': self.project.id, 'source_stage': 'SCREEN_1'},
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        refs = list(QAReference.objects.filter(project=self.project).order_by('title'))
        self.assertEqual([ref.title for ref in refs], ['AI exclude, human include', 'Legacy include'])
        human_ref = next(ref for ref in refs if ref.title == 'AI exclude, human include')
        self.assertEqual(human_ref.source_ref_id, included_by_human.id)

    def test_review_stats_freezes_final_decision_and_accuracy_rules(self):
        self.add_review('a.xml', 'excluded', 'included', True)
        self.add_review('b.xml', 'included', 'excluded', True)
        self.add_review('e.xml', 'pending', '', False)
        # 历史记录不属于当前 AI 结果，不应污染统计。
        self.add_review('stale.xml', 'excluded', 'included', True)
        ai_results = [
            {'source_xml': 'a.xml', 'decision': 'included'},
            {'source_xml': 'b.xml', 'decision': 'excluded'},
            {'source_xml': 'c.xml', 'decision': 'excluded', 'consensus': 'conflict'},
            {'source_xml': 'd.xml', 'decision': 'included'},
            {'source_xml': 'e.xml'},
        ]

        with patch('core.screening.api.review_views.load_ai_results', return_value=ai_results):
            response = self.client.get('/api/review/stats/', {'project': self.project.id})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        expected = {
            'total': 5,
            'reviewed': 3,
            'unreviewed': 2,
            'included': 1,
            'excluded': 1,
            'pending': 1,
            'conflict': 1,
            'overridden': 2,
            'ai_included': 2,
            'ai_excluded': 1,
            'ai_conflict': 1,
            'tab_included': 2,
            'tab_excluded': 1,
            'tab_pending': 1,
            'tab_conflict': 1,
            'final_included': 2,
            'final_excluded': 1,
            'final_conflict_pending': 2,
            'ai_accuracy': 50.0,
            'ai_correct_in_reviewed': 0,
            'ai_wrong_in_reviewed': 2,
            'decisive_reviewed': 2,
        }
        self.assertEqual(data, expected)

    def test_indexed_review_list_filters_conflicts_before_reading_page_files(self):
        self.add_result('included.xml', 'included', title='Included')
        conflict = self.add_result('conflict.xml', 'excluded', 'conflict', 'Conflict')
        self.add_result('excluded.xml', 'excluded', title='Excluded')

        with patch(
            'core.screening.api.review_views.load_ai_results',
            side_effect=AssertionError('indexed review must not scan every result file'),
        ):
            with patch(
                'core.screening.api.review_views.load_ai_result_file',
                side_effect=lambda data_file: dict(data_file.metadata),
            ) as load_file:
                with patch(
                    'core.screening.api.review_views.load_xml_fields_bulk', return_value={},
                ):
                    response = self.client.get('/api/review/list/', {
                        'project': self.project.id,
                        'step': self.review_step.id,
                        'decision': 'conflict',
                        'page': 1,
                        'page_size': 30,
                    })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['total'], 1)
        self.assertEqual(response.json()['results'][0]['source_xml'], 'conflict.xml')
        self.assertEqual(load_file.call_count, 1)
        self.assertEqual(load_file.call_args.args[0].pk, conflict.pk)

    def test_indexed_review_stats_aggregate_in_database(self):
        self.add_result('a.xml', 'included')
        self.add_result('b.xml', 'excluded')
        self.add_result('c.xml', 'excluded', 'conflict')
        self.add_result('d.xml', '')
        self.add_review('a.xml', 'excluded', 'included', True)

        with patch(
            'core.screening.api.review_views.load_ai_results',
            side_effect=AssertionError('indexed stats must not load result files'),
        ):
            response = self.client.get('/api/review/stats/', {'project': self.project.id})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['total'], 4)
        self.assertEqual(data['reviewed'], 1)
        self.assertEqual(data['tab_included'], 0)
        self.assertEqual(data['tab_excluded'], 2)
        self.assertEqual(data['tab_conflict'], 1)
        self.assertEqual(data['tab_pending'], 1)

    def test_ai_screen_stats_use_one_result_aggregation_query(self):
        self.add_result('a.xml', 'included')
        self.add_result('b.xml', 'excluded')
        self.add_result('c.xml', 'excluded', 'conflict')
        self.add_result('d.xml', '')

        # 一次定位 ai_screen 步骤、一次条件聚合；不能按分类重复扫描结果表。
        with self.assertNumQueries(2):
            stats = get_ai_screen_stats(self.project)

        self.assertEqual(stats['total'], 4)
        self.assertEqual(stats['included_count'], 1)
        self.assertEqual(stats['excluded_count'], 1)
        self.assertEqual(stats['conflict_count'], 1)
        self.assertEqual(stats['pending_count'], 1)

    def test_completed_ai_screen_stats_use_step_metadata_cache(self):
        ai_step = self.project.stages.get(stage_key='SCREEN_1').steps.get(step_key='ai_screen')
        ai_step.status = StageStepStatus.COMPLETED
        ai_step.metadata = {
            'stats_version': 2,
            'included_refs': 10,
            'excluded_refs': 20,
            'conflict_refs': 3,
            'pending_refs': 2,
        }
        ai_step.save(update_fields=['status', 'metadata'])

        # 只查询步骤自身，不访问 DataFile 结果表。
        with self.assertNumQueries(1):
            stats = get_ai_screen_stats(self.project)

        self.assertEqual(stats['total'], 35)
        self.assertEqual(stats['included_count'], 10)
        self.assertEqual(stats['excluded_count'], 20)
        self.assertEqual(stats['conflict_count'], 3)
        self.assertEqual(stats['pending_count'], 2)

    def test_single_review_update_reads_only_the_selected_result(self):
        self.add_result('selected.xml', 'included')
        self.add_result('other.xml', 'excluded')

        with patch(
            'core.screening.selectors.load_ai_results',
            side_effect=AssertionError('single review update must not scan every result file'),
        ):
            response = self.client.patch(
                '/api/review/item/selected.xml/',
                data={
                    'project': self.project.id,
                    'step': self.review_step.id,
                    'decision': 'excluded',
                    'reason': '人工排除',
                },
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        review = ManualReview.objects.get(project=self.project, source_xml='selected.xml')
        self.assertEqual(review.ai_decision, 'included')
        self.assertEqual(review.decision, 'excluded')
        self.assertTrue(review.is_override)


class ScreeningDecisionServiceTests(TestCase):
    def test_manual_decision_wins_and_legacy_ai_value_is_supported(self):
        from types import SimpleNamespace

        from core.screening.services.decision_service import ScreeningDecisionService

        result = {'include_or_not': 'yes'}
        self.assertTrue(ScreeningDecisionService.is_included(result))
        self.assertEqual(
            ScreeningDecisionService.resolve(
                result, SimpleNamespace(decision='excluded')
            ),
            'excluded',
        )
