from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings

from core.ai import AIUsageContext, AIUsageSettlementService, TokenUsageAccumulator
from core.ai.billing_calculator import RateSnapshot, calculate_task_pricing
from core.ai.pricing import calculate_shadow_pricing
from core.ai.usage_schema import normalize_provider_usage, summarize_complete_call_details
from core.models import Project, Task
from core.models_billing import (
    CreditAccount, ModelBillingRate, ModelUsageDetail, PlanCatalog,
    PlanPriceVersion, TokenUsageLog,
)
from core.quality.services.evidence_rollout import evidence_retrieval_enabled_for


User = get_user_model()


@override_settings(
    MODEL_WEIGHTED_BILLING_ENABLED=False,
    BILLING_RESERVATION_ENABLED=False,
    CREDIT_BATCH_LEDGER_ENABLED=False,
)
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


class VersionedBillingFoundationTests(TestCase):
    version = 'test-v2'

    def rate(self, **overrides):
        values = {
            'rate_key': 'qwen-short',
            'version': self.version,
            'provider': 'qwen',
            'region': 'cn-beijing',
            'service_tier': 'standard',
            'model_id': 'qwen3-7-flash',
            'provider_model': 'qwen3.7-flash',
            'context_min_tokens': 0,
            'context_max_tokens': 32768,
            'input_cny_per_million': Decimal('0.20'),
            'output_cny_per_million': Decimal('0.80'),
            'cache_read_cny_per_million': Decimal('0.04'),
            'cache_write_cny_per_million': Decimal('0.20'),
        }
        values.update(overrides)
        return RateSnapshot(**values)

    def call(self, **overrides):
        values = {
            'provider': 'qwen',
            'region': 'cn-beijing',
            'service_tier': 'standard',
            'model_id': 'qwen3-7-flash',
            'provider_model': 'qwen3.7-flash',
            'context_tokens': 1000,
            'input_tokens': 1000,
            'output_tokens': 100,
            'cache_read_tokens': 200,
            'cache_write_tokens': 0,
            'attempt_number': 1,
            'attempt_reason': 'initial',
            'charge_bearer': 'user',
        }
        values.update(overrides)
        return values

    def test_task_prices_cache_and_rounds_only_once(self):
        result = calculate_task_pricing(
            [self.call(), self.call()], [self.rate()], pricing_version=self.version,
        )

        self.assertEqual(result['estimated_cost_cny'], Decimal('0.000496'))
        self.assertEqual(result['task_credits'], 1)
        self.assertEqual(result['priced_calls'][0]['ordinary_input_tokens'], 800)

    def test_context_tier_and_platform_borne_retry(self):
        long_rate = self.rate(
            rate_key='qwen-long', context_min_tokens=32769,
            context_max_tokens=262144,
            input_cny_per_million=Decimal('0.60'),
            output_cny_per_million=Decimal('2.40'),
            cache_read_cny_per_million=Decimal('0.12'),
            cache_write_cny_per_million=Decimal('0.60'),
        )
        result = calculate_task_pricing(
            [self.call(
                context_tokens=40000, input_tokens=40000, cache_read_tokens=0,
                output_tokens=1000, attempt_reason='provider_transient_retry',
                charge_bearer='platform',
            )],
            [self.rate(), long_rate],
            pricing_version=self.version,
        )

        self.assertEqual(result['priced_calls'][0]['rate_key'], 'qwen-long')
        self.assertEqual(result['estimated_cost_cny'], Decimal('0.026400'))
        self.assertEqual(result['task_credits'], 0)

    def test_unknown_or_ambiguous_rate_blocks_credit_result(self):
        result = calculate_task_pricing(
            [self.call(model_id='unknown')], [self.rate()], pricing_version=self.version,
        )
        self.assertIsNone(result['task_credits'])
        self.assertEqual(len(result['unknown_calls']), 1)

    def test_historical_qwen_provider_model_id_is_canonicalized(self):
        result = calculate_task_pricing(
            [self.call(model_id='qwen3.7-flash')],
            [self.rate()],
            pricing_version=self.version,
        )

        self.assertEqual(result['task_credits'], 1)
        self.assertEqual(len(result['priced_calls']), 1)
        self.assertEqual(result['unknown_calls'], [])

    def test_provider_default_service_tier_matches_standard_rate(self):
        result = calculate_task_pricing(
            [self.call(service_tier='default')],
            [self.rate()],
            pricing_version=self.version,
        )

        self.assertEqual(result['task_credits'], 1)
        self.assertEqual(result['priced_calls'][0]['service_tier'], 'standard')
        self.assertEqual(result['unknown_calls'], [])

    def test_observed_deepseek_provider_model_matches_rate(self):
        detail = self.call(
            provider='deepseek', region='', model_id='deepseek-v4-flash',
            provider_model='deepseek-flash',
        )
        rate = self.rate(
            rate_key='deepseek-flash', provider='deepseek', region='global',
            model_id='deepseek-v4-flash', provider_model='deepseek-flash',
            context_max_tokens=0,
        )

        result = calculate_task_pricing([detail], [rate], pricing_version=self.version)

        self.assertEqual(result['task_credits'], 1)
        self.assertEqual(len(result['priced_calls']), 1)
        self.assertEqual(result['unknown_calls'], [])

    def test_configured_deepseek_provider_alias_matches_observed_rate(self):
        detail = self.call(
            provider='deepseek', region='', model_id='deepseek-v4-flash',
            provider_model='deepseek-v4-flash',
        )
        rate = self.rate(
            rate_key='deepseek-flash', provider='deepseek', region='global',
            model_id='deepseek-v4-flash', provider_model='deepseek-flash',
            context_max_tokens=0,
        )

        result = calculate_task_pricing([detail], [rate], pricing_version=self.version)

        self.assertEqual(result['task_credits'], 1)
        self.assertEqual(result['unknown_calls'], [])

    def test_replay_matches_historical_provider_identifiers(self):
        user = User.objects.create_user('replay-user', password='pw')
        usage_log = TokenUsageLog.objects.create(
            user=user,
            model='qwen3.7-flash,deepseek-v4-flash',
            credits_consumed=8,
            usage_breakdown={
                'qwen3.7-flash': {
                    'call_details': [self.call(model_id='qwen3.7-flash')],
                },
                'deepseek-v4-flash': {
                    'call_details': [self.call(
                        provider='deepseek', region='',
                        model_id='deepseek-v4-flash', provider_model='deepseek-flash',
                    )],
                },
            },
        )
        output = StringIO()

        call_command(
            'replay_weighted_billing',
            usage_log_id=[usage_log.pk],
            pricing_version='credit-v2-draft-2026-10-13',
            allow_draft=True,
            stdout=output,
        )

        rendered = output.getvalue()
        self.assertIn('calls=2 unknown=0', rendered)
        self.assertNotIn('未匹配费率', rendered)

    def test_replay_summary_keeps_unresolved_total_as_none(self):
        user = User.objects.create_user('unresolved-replay-user', password='pw')
        usage_log = TokenUsageLog.objects.create(
            user=user,
            model='unknown',
            credits_consumed=8,
            usage_breakdown={
                'unknown': {
                    'call_details': [self.call(
                        provider='unknown', region='', model_id='unknown',
                        provider_model='unknown',
                    )],
                },
            },
        )
        output = StringIO()

        call_command(
            'replay_weighted_billing',
            usage_log_id=[usage_log.pk],
            pricing_version='credit-v2-draft-2026-10-13',
            allow_draft=True,
            stdout=output,
        )

        summary = output.getvalue().splitlines()[-1]
        self.assertIn('new=None', summary)
        self.assertIn('calls=0 unknown=1', summary)

    @override_settings(
        MODEL_WEIGHTED_BILLING_ENABLED=True,
        MODEL_WEIGHTED_BILLING_ALLOW_DRAFT=True,
        MODEL_WEIGHTED_BILLING_PRICING_VERSION='credit-v2-draft-2026-10-13',
        BILLING_RESERVATION_ENABLED=False,
        CREDIT_BATCH_LEDGER_ENABLED=False,
    )
    def test_provider_usage_is_normalized_and_persisted_per_call(self):
        user = User.objects.create_user('usage-v2-user', password='pw')
        project = Project.objects.create(name='Usage V2', owner=user)
        task = Task.objects.create(project=project, task_type='ai_screen', created_by=user)
        account = CreditAccount.objects.get(user=user)
        account.balance = 20
        account.save(update_fields=['balance'])
        normalized = normalize_provider_usage(
            {
                'prompt_tokens': 1500,
                'completion_tokens': 500,
                'total_tokens': 2000,
                'prompt_tokens_details': {'cached_tokens': 300},
            },
            provider='deepseek', model_id='deepseek-v4-flash',
            provider_model='deepseek-v4-flash', region='global',
            provider_request_id='req-test-1',
        )
        usage = TokenUsageAccumulator()
        usage.add(normalized, model_id='deepseek-v4-flash')

        AIUsageSettlementService.settle(AIUsageContext(
            feature='AI初筛', user=user, project=project, task=task,
            model_ids=['deepseek-v4-flash'], idempotency_key='usage-v2-test',
        ), usage)

        detail = ModelUsageDetail.objects.get(task=task)
        self.assertEqual(detail.provider_request_id, 'req-test-1')
        self.assertEqual(detail.input_tokens, 1500)
        self.assertEqual(detail.output_tokens, 500)
        self.assertEqual(detail.cache_read_tokens, 300)
        self.assertEqual(detail.attempt_reason, 'initial')

    def test_complete_call_details_are_the_authoritative_summary(self):
        first = normalize_provider_usage(
            {'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 999},
            provider='qwen', model_id='qwen3-7-flash', provider_model='qwen3.7-flash',
        )
        summary = summarize_complete_call_details({
            'qwen3-7-flash': {
                'calls': 1,
                'call_details': first['call_details'],
            },
        })
        self.assertEqual(summary['prompt_tokens'], 100)
        self.assertEqual(summary['completion_tokens'], 20)
        self.assertEqual(summary['total_tokens'], 120)

    def test_plan_catalog_and_draft_and_published_rates_are_seeded(self):
        self.assertEqual(
            list(PlanCatalog.objects.order_by('code').values_list('code', flat=True)),
            ['LITE', 'PLUS', 'PRO'],
        )
        self.assertEqual(
            PlanPriceVersion.objects.filter(version='personal-v1-draft', status='draft').count(),
            3,
        )
        self.assertEqual(
            ModelBillingRate.objects.filter(
                version='credit-v2-draft-2026-10-13', status='draft',
            ).count(),
            8,
        )
        self.assertEqual(
            ModelBillingRate.objects.get(
                rate_key='credit-v2-draft:deepseek-v4-flash:all',
            ).provider_model,
            'deepseek-flash',
        )
        self.assertEqual(
            ModelBillingRate.objects.filter(
                version='credit-v2-2026-10-14', status='published',
            ).count(),
            8,
        )
        self.assertEqual(
            ModelBillingRate.objects.get(
                rate_key='credit-v2-2026-10-14:deepseek-v4-flash:all',
            ).provider_model,
            'deepseek-flash',
        )
        self.assertEqual(
            ModelBillingRate.objects.filter(
                version='credit-v2-2026-10-14-r2', status='published',
            ).count(),
            9,
        )
        deepseek_flash = ModelBillingRate.objects.get(
            rate_key='credit-v2-2026-10-14-r2:deepseek-v4-flash:all',
        )
        self.assertEqual(deepseek_flash.provider_model, 'deepseek-flash')
        self.assertEqual(deepseek_flash.input_cny_per_million, Decimal('2'))
        self.assertEqual(deepseek_flash.output_cny_per_million, Decimal('8'))
        self.assertEqual(deepseek_flash.cache_read_cny_per_million, Decimal('0.04'))
        qwen_plus_rates = ModelBillingRate.objects.filter(
            version='credit-v2-2026-10-14-r2', model_id='qwen3-7-plus',
        ).order_by('context_min_tokens')
        self.assertEqual(qwen_plus_rates.count(), 2)
        self.assertEqual(
            qwen_plus_rates.first().cache_read_cny_per_million,
            Decimal('0.4'),
        )


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
