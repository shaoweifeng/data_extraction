from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from core.models_billing import (
    CreditAccount,
    ModelBillingRate,
    ModelUsageDetail,
    PlanPriceVersion,
    TokenUsageLog,
    UserPlanEntitlement,
)
from core.services.credit_ledger_service import consume_batch_credits, grant_batch_credits


User = get_user_model()


class BillingPortalApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('portal-user', password='pw')
        self.other = User.objects.create_user('other-user', password='pw')
        self.client = Client()
        self.client.force_login(self.user)
        grant_batch_credits(
            self.user,
            100,
            batch_type='WELCOME',
            batch_key='portal:welcome',
            expires_at=timezone.now() + timedelta(days=30),
        )
        grant_batch_credits(
            self.other,
            999,
            batch_type='WELCOME',
            batch_key='other:welcome',
        )

    def test_batches_are_paginated_and_isolated_by_user(self):
        response = self.client.get('/api/billing/batches/', {'page': 1, 'page_size': 10})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['results'][0]['granted_amount'], 100)
        self.assertNotIn('other:welcome', str(data))

    def test_plans_include_current_and_scheduled_entitlement(self):
        version = PlanPriceVersion.objects.get(
            plan__code='PLUS', version='personal-v1-2026-10-13', status='published',
        )
        starts = timezone.now() + timedelta(days=5)
        UserPlanEntitlement.objects.create(
            user=self.user,
            price_version=version,
            status='scheduled',
            starts_at=starts,
            expires_at=starts + timedelta(days=30),
        )

        response = self.client.get('/api/billing/plans/')

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['current']['plan_code'], 'FREE')
        self.assertEqual(data['scheduled'][0]['plan_code'], 'PLUS')
        self.assertEqual({row['plan_code'] for row in data['plans']}, {'LITE', 'PLUS', 'PRO'})
        storage = {row['plan_code']: row['storage_limit_mb'] for row in data['plans']}
        self.assertEqual(storage, {'LITE': 20480, 'PLUS': 51200, 'PRO': 102400})

    def test_transaction_usage_exposes_model_tokens_but_not_internal_cost(self):
        transaction = consume_batch_credits(
            self.user,
            4,
            idempotency_key='portal:consume',
            note='AI 初筛',
        )
        log = TokenUsageLog.objects.create(
            user=self.user,
            model='qwen3-7-plus',
            prompt_tokens=2000,
            completion_tokens=200,
            total_tokens=2200,
            credits_consumed=4,
            pricing_version='credit-v2-2026-10-14',
            transaction=transaction,
        )
        rate = ModelBillingRate.objects.get(
            version='credit-v2-2026-10-14',
            model_id='qwen3-7-plus',
        )
        ModelUsageDetail.objects.create(
            usage_log=log,
            user=self.user,
            call_index=1,
            provider='qwen',
            region='cn-beijing',
            service_tier='standard',
            model_id='qwen3-7-plus',
            provider_model='qwen3.7-plus',
            context_tokens=2000,
            input_tokens=2000,
            output_tokens=200,
            rate=rate,
            estimated_cost_cny=Decimal('0.00560000'),
            raw_credits=Decimal('3.500000'),
        )

        response = self.client.get('/api/billing/transactions/')

        self.assertEqual(response.status_code, 200)
        item = next(row for row in response.json()['results'] if row['id'] == transaction.pk)
        model = item['usage'][0]['models'][0]
        self.assertEqual(model['model_id'], 'qwen3-7-plus')
        self.assertEqual(model['raw_credits'], '3.500000')
        self.assertNotIn('estimated_cost_cny', str(item))
        self.assertNotIn('input_tokens', str(item))
        self.assertNotIn('output_tokens', str(item))
        self.assertNotIn('total_tokens', str(item))

    def test_billing_endpoints_require_authentication(self):
        anonymous = Client()
        for path in (
            '/api/billing/balance/', '/api/billing/plans/',
            '/api/billing/batches/', '/api/billing/transactions/',
        ):
            self.assertIn(anonymous.get(path).status_code, {302, 403})
