"""Shared AI quota, provider and usage-settlement contracts."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

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
from core.screening.services.prompt_configuration import save_prompt
from core.screening.services.prompt_builder import ScreeningPromptBuilder


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

    def test_screening_provider_injects_one_structured_literature_record(self):
        provider = OpenAICompatibleProvider({
            'api_key': 'test', 'api_url': 'https://example.invalid/v1',
            'model': 'example', 'timeout': 1,
        })
        template = (
            '<criteria>{screening_criteria}</criteria>\n'
            '<record>{literature_record}</record>'
        )
        entry = {
            'reference_id': 42,
            'title': 'Example title',
            'abstract': 'Example abstract',
            'authors': ['Alice A', 'Bob B'],
            'journal': 'Example Journal',
            'publication_year': '2026',
            'publication_type': 'Journal Article',
            'language': 'eng',
            'keywords': ['screening', 'review'],
            'doi': '10.1000/example',
            'pmid': '123456',
            'url': 'https://example.test/article',
            'address': '',
        }
        response = '[{"exclusion_reason":"","number_exclusion_reason":"","include_or_not":"yes"}]'

        with patch.object(
            provider, 'generate_text', return_value=(response, {'total': 10}),
        ) as generate:
            result = provider.screen_single(entry, ['Exclude reviews'], template)

        rendered = generate.call_args.args[0]
        self.assertNotIn('{screening_criteria}', rendered)
        self.assertNotIn('{literature_record}', rendered)
        self.assertNotIn('[文献内容]', rendered)
        self.assertIn('1. Exclude reviews', rendered)
        self.assertIn('"reference_id": 42', rendered)
        self.assertIn('"authors": [', rendered)
        self.assertIn('"publication_type": "Journal Article"', rendered)
        self.assertIn('"language": "eng"', rendered)
        self.assertNotIn('"address"', rendered)
        self.assertEqual(result.decision, 'included')

    def test_prompt_render_does_not_expand_placeholders_inside_injected_data(self):
        rendered = OpenAICompatibleProvider._render_screening_prompt(
            '{screening_criteria}\n{literature_record}',
            screening_criteria='1. 标题含有 {literature_record}',
            literature_record='{"title":"{screening_criteria}"}',
        )

        self.assertEqual(
            rendered,
            '1. 标题含有 {literature_record}\n{"title":"{screening_criteria}"}',
        )

    def test_custom_screening_prompt_requires_both_placeholders(self):
        with self.assertRaisesMessage(ValueError, '{literature_record}'):
            save_prompt(
                self.project,
                'Only {screening_criteria}',
                True,
                self.user,
            )

        result = save_prompt(
            self.project,
            '{screening_criteria}\n{literature_record}',
            True,
            self.user,
        )

        self.project.refresh_from_db()
        self.assertTrue(result['use_custom_prompt'])
        self.assertTrue(self.project.metadata['use_custom_prompt'])

    def test_field_extraction_block_extends_the_base_output_contract(self):
        executor = Mock()
        executor.get_previous_step.return_value = SimpleNamespace(metadata={
            'fields': [
                {'name': '研究人群', 'definition': '提取研究对象的年龄与疾病'},
                {'name': '引号"字段', 'definition': '定义中包含"引号"'},
                {'name': '研究人群', 'definition': '重复字段应忽略'},
                'invalid-field',
            ],
        })
        handler = SimpleNamespace(executor=executor, logger=Mock())
        builder = ScreeningPromptBuilder(handler)

        prompt = builder._append_extraction_block('BASE_PROMPT')

        self.assertIn('<field_extraction_task>', prompt)
        self.assertIn('增加且仅增加一个 extracted_fields 字段', prompt)
        self.assertIn('文献被排除时，extracted_fields 输出空对象 {}', prompt)
        self.assertEqual(prompt.count('"name": "研究人群"'), 1)
        self.assertIn('"name": "引号\\"字段"', prompt)
        self.assertIn('"研究人群": "提取值或空字符串"', prompt)
        self.assertNotIn('invalid-field', prompt)

    def test_no_extraction_fields_keeps_base_prompt_unchanged(self):
        executor = Mock()
        executor.get_previous_step.return_value = SimpleNamespace(metadata={'fields': []})
        handler = SimpleNamespace(executor=executor, logger=Mock())

        prompt = ScreeningPromptBuilder(handler)._append_extraction_block('BASE_PROMPT')

        self.assertEqual(prompt, 'BASE_PROMPT')

    def test_reasoning_provider_disables_thinking_by_default(self):
        provider = OpenAICompatibleProvider({
            'api_key': 'test', 'api_url': 'https://example.invalid/v1',
            'model': 'example', 'provider': 'deepseek',
            'timeout': 1, 'is_reasoning': True,
        })
        response = Mock(status_code=200)
        response.json.return_value = {
            'choices': [{'message': {'content': 'answer'}}],
            'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2},
        }

        with patch(
            'core.executors.ai_providers.openai_compatible.requests.post',
            return_value=response,
        ) as post:
            provider.generate_text('prompt')

        self.assertEqual(post.call_args.kwargs['json']['thinking'], {'type': 'disabled'})

    def test_reasoning_provider_can_enable_thinking_explicitly(self):
        provider = OpenAICompatibleProvider({
            'api_key': 'test', 'api_url': 'https://example.invalid/v1',
            'model': 'example', 'provider': 'deepseek',
            'timeout': 1, 'is_reasoning': True,
            'thinking_enabled': True,
        })
        response = Mock(status_code=200)
        response.json.return_value = {'choices': [{'message': {'content': 'answer'}}]}

        with patch(
            'core.executors.ai_providers.openai_compatible.requests.post',
            return_value=response,
        ) as post:
            provider.generate_text('prompt')

        self.assertEqual(post.call_args.kwargs['json']['thinking'], {'type': 'enabled'})

    def test_qwen_uses_vendor_specific_thinking_parameter(self):
        provider = OpenAICompatibleProvider({
            'api_key': 'test', 'api_url': 'https://example.invalid/v1',
            'model': 'qwen-example', 'provider': 'qwen',
            'timeout': 1, 'is_reasoning': True,
        })
        response = Mock(status_code=200)
        response.json.return_value = {'choices': [{'message': {'content': 'answer'}}]}

        with patch(
            'core.executors.ai_providers.openai_compatible.requests.post',
            return_value=response,
        ) as post:
            provider.generate_text('prompt')

        payload = post.call_args.kwargs['json']
        self.assertIs(payload['enable_thinking'], False)
        self.assertNotIn('thinking', payload)
