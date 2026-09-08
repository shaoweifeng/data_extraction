"""初筛最终决策、人工复核统计和 QA 导入规则。"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from core.models import ManualReview, Project, QAReference
from core.services.project_service import initialize_project


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
