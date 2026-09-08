"""Shared AI quota, provider and usage-settlement contracts."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.ai import (
    AIQuotaService,
    AIUsageContext,
    AIUsageSettlementService,
    TokenUsageAccumulator,
    is_unlimited_ai_user,
)
from core.executors.ai_providers import OpenAICompatibleProvider
from core.models import Project, Task
from core.models_billing import CreditAccount, CreditTransaction, TokenUsageLog


User = get_user_model()


class SharedAIInfrastructureTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ai-user', password='pw')
        self.project = Project.objects.create(name='AI Project', owner=self.user)
        self.task = Task.objects.create(
            project=self.project,
            task_type='ai_screen',
            created_by=self.user,
        )
        self.account = CreditAccount.objects.get(user=self.user)
        self.account.balance = 10
        self.account.total_consumed = 0
        self.account.save(update_fields=['balance', 'total_consumed'])

    def usage(self):
        usage = TokenUsageAccumulator()
        usage.add({'prompt': 1500, 'completion': 1000, 'total': 2500})
        return usage

    def test_accumulator_normalizes_provider_usage(self):
        usage = self.usage()
        usage.add(None)
        self.assertEqual(
            usage.as_dict(),
            {
                'prompt_tokens': 1500,
                'completion_tokens': 1000,
                'total_tokens': 2500,
                'ref_count': 1,
            },
        )

    def test_regular_user_preflight_and_settlement_share_one_policy(self):
        self.assertEqual(AIQuotaService.preflight(self.user, 2, ['model-a']), 4)
        stats = AIUsageSettlementService.settle(
            AIUsageContext(
                feature='AI筛选', user=self.user, project=self.project,
                task=self.task, model_ids=['model-a'],
            ),
            self.usage(),
        )

        self.account.refresh_from_db()
        self.task.refresh_from_db()
        transaction = CreditTransaction.objects.get(txn_type='consume')
        usage_log = TokenUsageLog.objects.get(task=self.task)
        self.assertEqual(self.account.balance, 8)
        self.assertEqual(stats['credits_consumed'], 2)
        self.assertEqual(usage_log.transaction, transaction)
        self.assertEqual(usage_log.project, self.project)
        self.assertEqual(self.task.result['token_stats']['credits_estimate'], 2)

    def test_application_admin_bypasses_preflight_and_is_audited_without_charge(self):
        self.user.profile.role = 'admin'
        self.user.profile.save(update_fields=['role'])
        self.account.balance = 0
        self.account.save(update_fields=['balance'])

        self.assertTrue(is_unlimited_ai_user(self.user))
        self.assertEqual(AIQuotaService.preflight(self.user, 100, ['a', 'b']), 400)
        AIUsageSettlementService.settle(
            AIUsageContext(
                feature='AI质量评价', user=self.user, project=self.project,
                task=self.task, model_ids=['a', 'b'],
            ),
            self.usage(),
        )

        self.account.refresh_from_db()
        transaction = CreditTransaction.objects.get(txn_type='admin_usage')
        usage_log = TokenUsageLog.objects.get(task=self.task)
        self.assertEqual(self.account.balance, 0)
        self.assertEqual(transaction.amount, 0)
        self.assertEqual(usage_log.transaction, transaction)
        self.assertTrue(self.task.token_logs.exists())

    def test_regular_user_with_insufficient_balance_is_rejected(self):
        self.account.balance = 1
        self.account.save(update_fields=['balance'])
        with self.assertRaisesMessage(ValueError, '余额不足'):
            AIQuotaService.preflight(self.user, 2, ['model-a'])

    def test_provider_exposes_public_text_generation(self):
        provider = OpenAICompatibleProvider({
            'api_key': 'test', 'api_url': 'https://example.invalid/v1',
            'model': 'example', 'timeout': 1,
        })
        with patch.object(provider, '_call_api', return_value=('answer', {'total': 3})) as call:
            result = provider.generate_text('prompt')
        self.assertEqual(result, ('answer', {'total': 3}))
        call.assert_called_once_with('prompt')
