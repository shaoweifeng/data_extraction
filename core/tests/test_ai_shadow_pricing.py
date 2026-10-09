from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings

from core.ai import AIUsageContext, AIUsageSettlementService, TokenUsageAccumulator
from core.ai.pricing import calculate_shadow_pricing
from core.models import Project, Task
from core.models_billing import CreditAccount, TokenUsageLog
from core.quality.services.evidence_rollout import evidence_retrieval_enabled_for


User = get_user_model()


class ShadowPricingTests(TestCase):
    def test_model_aware_rates_are_calculated_per_input_and_output(self):
        result = calculate_shadow_pricing({
            'deepseek-v4-flash': {
                'prompt_tokens': 1000, 'completion_tokens': 1000, 'calls': 1,
            },
            'qwen3-7-flash': {
                'prompt_tokens': 1000, 'completion_tokens': 1000, 'calls': 1,
            },
        })
        self.assertEqual(result['pricing_version'], 'ai-credit-v1')
        self.assertEqual(result['estimated_cost_cny'], Decimal('0.011800'))
        self.assertEqual(result['shadow_credits'], 6)

    def test_shadow_pricing_is_persisted_without_changing_actual_charge(self):
        user = User.objects.create_user('shadow-user', password='pw')
        project = Project.objects.create(name='Shadow', owner=user)
        task = Task.objects.create(project=project, task_type='qa_eval', created_by=user)
        account = CreditAccount.objects.get(user=user)
        account.balance = 20
        account.save(update_fields=['balance'])
        usage = TokenUsageAccumulator()
        usage.add(
            {'prompt': 1500, 'completion': 500, 'total': 2000},
            model_id='deepseek-v4-flash',
        )
        stats = AIUsageSettlementService.settle(AIUsageContext(
            feature='AI质量评价', user=user, project=project, task=task,
            model_ids=['deepseek-v4-flash'],
        ), usage)
        account.refresh_from_db()
        log = TokenUsageLog.objects.get(task=task)
        self.assertEqual(account.balance, 18)
        self.assertEqual(log.credits_consumed, 2)
        self.assertEqual(log.shadow_credits, 4)
        self.assertEqual(log.pricing_version, 'ai-credit-v1')
        self.assertIn('deepseek-v4-flash', log.usage_breakdown)
        self.assertEqual(stats['credits_consumed'], 2)


class EvidenceRolloutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('rollout-user', email='rollout@example.test')
        self.admin = User.objects.create_superuser('rollout-admin', 'admin@example.test', 'pw')

    @override_settings(
        QA_EVIDENCE_RETRIEVAL_ENABLED=True,
        QA_EVIDENCE_ROLLOUT_MODE='admin',
        QA_EVIDENCE_ROLLOUT_ALLOWLIST=set(),
    )
    def test_admin_mode_is_restricted(self):
        self.assertFalse(evidence_retrieval_enabled_for(self.user))
        self.assertTrue(evidence_retrieval_enabled_for(self.admin))

    @override_settings(
        QA_EVIDENCE_RETRIEVAL_ENABLED=True,
        QA_EVIDENCE_ROLLOUT_MODE='allowlist',
        QA_EVIDENCE_ROLLOUT_ALLOWLIST={'rollout-user'},
    )
    def test_allowlist_accepts_username(self):
        self.assertTrue(evidence_retrieval_enabled_for(self.user))

    @override_settings(
        QA_EVIDENCE_RETRIEVAL_ENABLED=False,
        QA_EVIDENCE_ROLLOUT_MODE='all',
        QA_EVIDENCE_ROLLOUT_ALLOWLIST=set(),
    )
    def test_master_switch_wins(self):
        self.assertFalse(evidence_retrieval_enabled_for(self.admin))

    def test_rollout_report_runs_with_empty_window(self):
        output = StringIO()
        call_command('report_qa_evidence_rollout', days=7, stdout=output)
        self.assertIn('QA任务:', output.getvalue())
