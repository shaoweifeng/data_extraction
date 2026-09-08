"""QA 信号问题、偏倚风险和适用性结果的聚合规则。"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.models import Project, QADomainResult, QAReference, QASignalItem


User = get_user_model()


class QaDomainAggregationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('qa-domain-user')
        self.project = Project.objects.create(name='QA domain', owner=self.user)

    def add_signal(self, ref, key, result_type, judgment, confirmed=True, domain='patient_selection'):
        return QASignalItem.objects.create(
            qa_ref=ref,
            quality_method=ref.quality_method,
            domain=domain,
            result_type=result_type,
            signal_key=key,
            signal_question=key,
            options=['是', '否', '不清楚', '低', '高'],
            human_judgment=judgment,
            is_confirmed=confirmed,
        )

    def test_quadas2_aggregation_handles_bias_applicability_and_pending(self):
        from core.quality.services.domain_results import recalculate_domain_results

        ref = QAReference.objects.create(
            project=self.project,
            title='Mixed result',
            quality_method='QUADAS2',
        )
        self.add_signal(ref, 'PS1', 'bias_risk', '是')
        self.add_signal(ref, 'PS2', 'bias_risk', '不清楚')
        self.add_signal(ref, 'PSA', 'applicability', '高')
        self.add_signal(ref, 'IT1', 'bias_risk', '是', domain='index_test')
        self.add_signal(ref, 'IT2', 'bias_risk', '', confirmed=False, domain='index_test')

        recalculate_domain_results(ref)

        patient = QADomainResult.objects.get(qa_ref=ref, domain='patient_selection')
        self.assertEqual(patient.bias_risk_result, 'unclear')
        self.assertEqual(patient.applicability_result, 'high')
        self.assertTrue(patient.bias_all_confirmed)
        self.assertTrue(patient.applicability_all_confirmed)
        index_test = QADomainResult.objects.get(qa_ref=ref, domain='index_test')
        self.assertEqual(index_test.bias_risk_result, 'pending')
        self.assertFalse(index_test.bias_all_confirmed)
        ref.refresh_from_db()
        self.assertEqual(ref.review_status, 'partial')

    def test_nos_cross_mark_is_high_risk(self):
        from core.quality.services.domain_results import recalculate_domain_results

        ref = QAReference.objects.create(
            project=self.project,
            title='NOS result',
            quality_method='NOS',
        )
        self.add_signal(ref, 'S1', 'bias_risk', '✗ 不满足标准', domain='selection')
        recalculate_domain_results(ref)
        result = QADomainResult.objects.get(qa_ref=ref, domain='selection')
        self.assertEqual(result.bias_risk_result, 'high')
