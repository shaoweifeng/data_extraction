from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from dateutil.relativedelta import relativedelta

from core.models import Project
from core.models_billing import (
    CreditGrantBatch, PlanBillingPeriod, PlanCatalog, PlanPriceVersion,
    RechargeCode, UserPlanEntitlement,
)
from core.services.billing_estimate_service import estimate_model_credits
from core.services.concurrency_service import get_user_concurrency, slots_for_task
from core.services.entitlement_service import (
    EntitlementError, redeem_plan_code, resolve_user_entitlements, sync_user_plan,
)
from core.services.project_service import check_create_permission


User = get_user_model()


@override_settings(
    MODEL_WEIGHTED_BILLING_ENABLED=True,
    MODEL_WEIGHTED_BILLING_ALLOW_DRAFT=True,
    MODEL_WEIGHTED_BILLING_PRICING_VERSION='credit-v2-2026-10-14-r2',
)
class ModelAwareEstimateTests(TestCase):
    expected_multipliers = {
        'qwen3-7-flash': '0.25',
        'deepseek-v4-flash': '1.0',
        'qwen3-7-plus': '1.0',
        'doubao-seed-2-1-turbo': '1.5',
        'deepseek-v4-pro': '4.5',
        'qwen3-7-max': '6.0',
    }

    def test_selected_models_use_rate_based_multipliers_and_reserve_range(self):
        model_ids = list(self.expected_multipliers)
        result = estimate_model_credits(
            100,
            model_ids,
            feature='ai_screen',
        )
        rows = {row['model_id']: row for row in result['models']}
        self.assertEqual(
            {model_id: rows[model_id]['multiplier'] for model_id in model_ids},
            self.expected_multipliers,
        )
        for row in rows.values():
            self.assertEqual((Decimal(row['multiplier']) * 4) % 1, 0)
        self.assertGreater(result['reserve_credits'], result['base_credits'])
        self.assertNotEqual(result['reserve_credits'], 100 * len(model_ids) * 2)

    def test_quality_evaluation_uses_the_same_public_multiplier_scale(self):
        result = estimate_model_credits(
            1,
            list(self.expected_multipliers),
            feature='qa_eval',
        )

        self.assertEqual(
            {row['model_id']: row['multiplier'] for row in result['models']},
            self.expected_multipliers,
        )


@override_settings(
    PLAN_BILLING_ENABLED=True,
    CREDIT_BATCH_LEDGER_ENABLED=True,
    PLAN_FREE_PROJECT_LIMIT=1,
    PLAN_FREE_AI_CALL_SLOTS=2,
    PLAN_FREE_STORAGE_MB=5120,
    AI_SCREEN_MAX_GLOBAL_THREADS=64,
)
class PlanBillingServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('plan-user', password='secret')
        self.now = timezone.make_aware(datetime(2026, 10, 15, 12, 0, 0))
        self.lite = self._version('LITE', 'Lite', 399, 20000, 4, 5)
        self.plus = self._version('PLUS', 'Plus', 599, 50000, 8, 10)
        self.pro = self._version('PRO', 'Pro', 899, 120000, 16, 20)

    def _version(self, code, name, price, credits, slots, projects):
        storage_by_plan = {'LITE': 20480, 'PLUS': 51200, 'PRO': 102400}
        plan, _ = PlanCatalog.objects.update_or_create(
            code=code, defaults={'name': name, 'is_active': True},
        )
        version, _ = PlanPriceVersion.objects.update_or_create(
            plan=plan,
            version=f'{code.lower()}-test-published',
            defaults={
                'status': 'published', 'monthly_price_cny': price,
                'valid_months': 1, 'included_credits': credits,
                'ai_call_slots': slots, 'project_limit': projects,
                'storage_limit_mb': storage_by_plan[code],
            },
        )
        return version

    def _code(self, code, version, months=1):
        return RechargeCode.objects.create(
            code=code, code_type='PLAN', credits=0,
            plan_price_version=version, valid_months=months,
        )

    def test_free_then_active_plan_and_admin_override_precedence(self):
        free = resolve_user_entitlements(self.user)
        self.assertEqual(
            (free.plan_code, free.project_limit, free.ai_call_slots, free.storage_limit_mb),
            ('FREE', 1, 2, 5120),
        )

        self._code('LITE-ONE', self.lite)
        entitlement = redeem_plan_code(self.user, 'LITE-ONE', now=self.now)
        self.assertEqual(entitlement.status, 'active')
        self.assertEqual(PlanBillingPeriod.objects.filter(entitlement=entitlement).count(), 1)
        batch = CreditGrantBatch.objects.get(entitlement=entitlement)
        self.assertEqual((batch.granted_amount, batch.remaining_amount), (20000, 20000))

        active = resolve_user_entitlements(self.user, sync=False)
        # resolve uses wall-clock time; verify the resolver's priority with a
        # period anchored around the actual test time as well.
        entitlement.starts_at = timezone.now() - timedelta(days=1)
        entitlement.expires_at = timezone.now() + timedelta(days=20)
        entitlement.save(update_fields=['starts_at', 'expires_at'])
        active = resolve_user_entitlements(self.user, sync=False)
        self.assertEqual(
            (active.plan_code, active.project_limit, active.ai_call_slots, active.storage_limit_mb),
            ('LITE', 5, 4, 20480),
        )

        profile = self.user.profile
        profile.quota_projects_override = 7
        profile.ai_call_slots_override = 6
        profile.quota_storage_mb_override = 30720
        profile.save(update_fields=[
            'quota_projects_override', 'ai_call_slots_override', 'quota_storage_mb_override',
        ])
        overridden = resolve_user_entitlements(self.user, sync=False)
        self.assertEqual(
            (
                overridden.source, overridden.project_limit,
                overridden.ai_call_slots, overridden.storage_limit_mb,
            ),
            ('admin_override', 7, 6, 30720),
        )

    def test_same_plan_multi_month_renewal_is_idempotently_scheduled(self):
        self._code('LITE-FIRST', self.lite)
        first = redeem_plan_code(self.user, 'LITE-FIRST', now=self.now)
        original_end = first.expires_at
        self._code('LITE-RENEW', self.lite, months=2)
        renewed = redeem_plan_code(self.user, 'LITE-RENEW', now=self.now)
        self.assertEqual(first.pk, renewed.pk)
        self.assertEqual(renewed.expires_at, original_end + relativedelta(months=2))
        self.assertEqual(renewed.billing_periods.count(), 3)
        with self.assertRaises(EntitlementError):
            redeem_plan_code(self.user, 'LITE-RENEW', now=self.now)

    def test_month_end_anchor_survives_february_and_leap_year(self):
        jan_31 = timezone.make_aware(datetime(2027, 1, 31, 8, 0, 0))
        self._code('LITE-MONTH-END', self.lite, months=3)
        entitlement = redeem_plan_code(self.user, 'LITE-MONTH-END', now=jan_31)
        ends = list(entitlement.billing_periods.order_by('period_start').values_list(
            'period_end', flat=True,
        ))
        self.assertEqual([(item.month, item.day) for item in ends], [(2, 28), (3, 31), (4, 30)])

        leap_user = User.objects.create_user('leap-user', password='secret')
        leap_start = timezone.make_aware(datetime(2028, 1, 31, 8, 0, 0))
        RechargeCode.objects.create(
            code='LITE-LEAP', code_type='PLAN', credits=0,
            plan_price_version=self.lite, valid_months=2,
        )
        leap = redeem_plan_code(leap_user, 'LITE-LEAP', now=leap_start)
        leap_ends = list(leap.billing_periods.order_by('period_start').values_list(
            'period_end', flat=True,
        ))
        self.assertEqual([(item.month, item.day) for item in leap_ends], [(2, 29), (3, 31)])

    def test_only_one_different_future_plan_change_is_allowed(self):
        self._code('LITE-ACTIVE', self.lite)
        redeem_plan_code(self.user, 'LITE-ACTIVE', now=self.now)
        self._code('PLUS-FUTURE', self.plus)
        scheduled = redeem_plan_code(self.user, 'PLUS-FUTURE', now=self.now)
        self.assertEqual(scheduled.status, 'scheduled')
        self._code('PRO-REJECT', self.pro)
        with self.assertRaisesMessage(EntitlementError, 'future_plan_change_exists'):
            redeem_plan_code(self.user, 'PRO-REJECT', now=self.now)

    def test_due_period_grants_once_and_project_limit_uses_resolver(self):
        self._code('LITE-LIMIT', self.lite)
        entitlement = redeem_plan_code(self.user, 'LITE-LIMIT', now=self.now)
        for index in range(5):
            Project.objects.create(name=f'P{index}', owner=self.user)
        entitlement.starts_at = timezone.now() - timedelta(days=1)
        entitlement.expires_at = timezone.now() + timedelta(days=20)
        entitlement.save(update_fields=['starts_at', 'expires_at'])
        with self.assertRaisesMessage(PermissionError, '当前套餐项目上限'):
            check_create_permission(self.user)
        sync_user_plan(self.user, now=self.now)
        self.assertEqual(CreditGrantBatch.objects.filter(entitlement=entitlement).count(), 1)

    def test_concurrency_comes_from_plan_and_task_never_exceeds_it(self):
        self._code('PLUS-SLOTS', self.plus)
        entitlement = redeem_plan_code(self.user, 'PLUS-SLOTS', now=self.now)
        entitlement.starts_at = timezone.now() - timedelta(days=1)
        entitlement.expires_at = timezone.now() + timedelta(days=20)
        entitlement.save(update_fields=['starts_at', 'expires_at'])
        self.assertEqual(get_user_concurrency(self.user), 8)
        task = type('TaskStub', (), {
            'task_type': 'ai_screen', 'config': {'concurrency': 16},
        })()
        self.assertEqual(slots_for_task(task, 8), 8)

    def test_plan_redeem_and_catalog_api(self):
        self._code('LITE-API', self.lite)
        self.client.force_login(self.user)
        response = self.client.post(
            '/api/billing/redeem/',
            {'code': 'LITE-API'},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['plan']['plan_code'], 'LITE')
        self.assertEqual(response.json()['credits_added'], 20000)

        catalog = self.client.get('/api/billing/plans/')
        self.assertEqual(catalog.status_code, 200)
        self.assertIn('LITE', {row['plan_code'] for row in catalog.json()['plans']})
