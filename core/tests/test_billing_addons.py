from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from core.models_billing import (
    AddonProductVersion, CreditGrantBatch, RechargeCode, UserConcurrencyGrant,
    PlanPriceVersion, UserPlanEntitlement,
)
from core.services.billing_addon_service import AddonError, catalog, redeem_addon_code
from core.services.entitlement_service import resolve_user_entitlements
from core.services.credit_ledger_service import redeem_credit_code


@override_settings(PLAN_BILLING_ENABLED=True, CREDIT_BATCH_LEDGER_ENABLED=True,
                   PLAN_FREE_AI_CALL_SLOTS=2, ACCOUNT_RATE_LIMIT_ENABLED=False)
class BillingAddonTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('addon-user', password='test')
        self.now = timezone.now()
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def version(self, code):
        return AddonProductVersion.objects.get(product__code=code)

    def code(self, product, name='ADDON-TEST'):
        return RechargeCode.objects.create(code=name, code_type='ADDON', credits=0,
                                           addon_version=self.version(product))

    def subscribe(self, plan='LITE', start=None, end=None):
        version = PlanPriceVersion.objects.filter(plan__code=plan, status='published').first()
        return UserPlanEntitlement.objects.create(
            user=self.user, price_version=version, status='active',
            starts_at=start or self.now - timedelta(days=1),
            expires_at=end or self.now + timedelta(days=20),
        )

    def test_seed_prices_costs_and_listing(self):
        expected = {'CREDIT_10K': (99, 10000), 'CREDIT_50K': (399, 50000),
                    'CREDIT_100K': (699, 100000), 'TRIAL_5K': (99, 5000)}
        for code, (price, credits) in expected.items():
            item = self.version(code)
            item.full_clean()
            self.assertEqual((item.reference_price_cny, item.credits), (price, credits))
        self.assertEqual(self.version('TRIAL_5K').credits * Decimal('0.00216'), Decimal('10.80'))
        self.assertNotIn('SLOTS_4', [row['code'] for row in catalog(self.user)])

    def test_free_user_can_redeem_trial_once_with_independent_expiry(self):
        code = self.code('TRIAL_5K')
        before = self.user.credit_account.balance
        result = redeem_addon_code(self.user, code.code)
        batch = CreditGrantBatch.objects.get(addon_version=code.addon_version)
        self.assertEqual(result['credits_added'], 5000)
        self.assertEqual(batch.granted_amount, 5000)
        self.assertEqual(batch.expires_at.year, self.now.year + 1)
        self.user.credit_account.refresh_from_db()
        self.assertEqual(self.user.credit_account.balance, before + 5000)
        with self.assertRaises(AddonError):
            redeem_addon_code(self.user, code.code)
        self.assertEqual(resolve_user_entitlements(self.user).ai_call_slots, 2)

    def test_subscription_rejection_rolls_back(self):
        for product in ('CREDIT_50K', 'SLOTS_8'):
            code = self.code(product, product)
            with self.assertRaisesRegex(AddonError, '套餐'):
                redeem_addon_code(self.user, code.code)
            code.refresh_from_db()
            self.assertFalse(code.is_used)
        self.assertFalse(CreditGrantBatch.objects.filter(addon_version__isnull=False).exists())

    def test_expired_and_future_plans_are_not_subscriptions(self):
        for start, end in ((-10, -1), (1, 20)):
            self.subscribe(start=self.now + timedelta(days=start), end=self.now + timedelta(days=end))
        with self.assertRaisesRegex(AddonError, '套餐'):
            redeem_addon_code(self.user, self.code('CREDIT_10K').code)

    def test_subscriber_credit_bundle_and_plan_expiry(self):
        self.subscribe()
        redeem_addon_code(self.user, self.code('CREDIT_50K').code)
        batch = CreditGrantBatch.objects.get(addon_version__isnull=False)
        self.assertEqual(batch.granted_amount, 50000)
        with patch('django.utils.timezone.now', return_value=self.now + timedelta(days=30)):
            self.assertEqual(resolve_user_entitlements(self.user).plan_code, 'FREE')
            self.assertGreater(batch.expires_at, timezone.now())

    def test_legacy_credit_code_retains_existing_behavior(self):
        code = RechargeCode.objects.create(code='LEGACY', credits=777)
        txn = redeem_credit_code(self.user, code.code)
        self.assertEqual(txn.grant_batch.granted_amount, 777)
        self.assertIsNone(txn.grant_batch.expires_at)

    def test_unlisting_keeps_issued_code_valid_revocation_does_not(self):
        version = self.version('TRIAL_5K')
        code = self.code('TRIAL_5K')
        version.product.is_active = False
        version.product.save()
        redeem_addon_code(self.user, code.code)
        other = self.code('TRIAL_5K', 'REVOKED')
        version.status = 'revoked'
        version.save(update_fields=['status'])
        with self.assertRaisesRegex(AddonError, '撤销'):
            redeem_addon_code(self.user, other.code)

    def test_published_snapshot_immutable_and_bad_code_validation(self):
        version = self.version('TRIAL_5K')
        version.credits = 99999
        with self.assertRaises(ValidationError):
            version.save()
        code = self.code('TRIAL_5K')
        code.full_clean()
        code.credits = 100
        with self.assertRaises(ValidationError):
            code.full_clean()

    def test_concurrency_renewal_cross_tier_and_expiry(self):
        self.subscribe()
        first = self.code('SLOTS_8')
        redeem_addon_code(self.user, first.code)
        current = resolve_user_entitlements(self.user)
        self.assertEqual((current.base_ai_call_slots, current.ai_call_slots), (4, 8))
        redeem_addon_code(self.user, self.code('SLOTS_8', 'RENEW').code)
        rows = list(UserConcurrencyGrant.objects.order_by('starts_at'))
        self.assertEqual(rows[0].expires_at, rows[1].starts_at)
        with self.assertRaisesRegex(AddonError, '其他档位'):
            redeem_addon_code(self.user, self.code('SLOTS_16', 'CROSS').code)
        with patch('django.utils.timezone.now', return_value=rows[0].expires_at):
            self.assertEqual(resolve_user_entitlements(self.user).ai_call_slots, 8)
        with patch('django.utils.timezone.now', return_value=rows[1].expires_at):
            self.assertEqual(resolve_user_entitlements(self.user).ai_call_slots, 2)

    def test_plan_expiry_does_not_cancel_grant_but_blocks_renewal(self):
        self.subscribe(end=self.now + timedelta(days=1))
        redeem_addon_code(self.user, self.code('SLOTS_16').code)
        with patch('django.utils.timezone.now', return_value=self.now + timedelta(days=2)):
            self.assertEqual(resolve_user_entitlements(self.user).ai_call_slots, 16)
            with self.assertRaisesRegex(AddonError, '套餐'):
                redeem_addon_code(self.user, self.code('SLOTS_16', 'LATE').code)

    def test_no_gain_admin_override_and_researcher(self):
        self.subscribe('PLUS')
        with self.assertRaisesRegex(AddonError, '基础并发'):
            redeem_addon_code(self.user, self.code('SLOTS_8').code)
        self.user.profile.role = 'researcher'
        self.user.profile.save()
        redeem_addon_code(self.user, self.code('SLOTS_16', 'RESEARCH').code)
        self.assertEqual(resolve_user_entitlements(self.user).ai_call_slots, 16)
        self.user.profile.ai_call_slots_override = 3
        self.user.profile.save()
        self.assertEqual(resolve_user_entitlements(self.user).ai_call_slots, 3)

    def test_month_end_renewal_retains_anchor(self):
        jan31 = timezone.make_aware(datetime(2027, 1, 31, 12))
        self.subscribe(start=jan31 - timedelta(days=1), end=jan31 + timedelta(days=100))
        with patch('django.utils.timezone.now', return_value=jan31):
            redeem_addon_code(self.user, self.code('SLOTS_8').code)
            redeem_addon_code(self.user, self.code('SLOTS_8', 'MONTH2').code)
        rows = list(UserConcurrencyGrant.objects.order_by('starts_at'))
        self.assertEqual((rows[0].expires_at.day, rows[1].expires_at.day), (28, 31))

    def test_api_catalog_redemption_and_untrusted_fields(self):
        code = self.code('TRIAL_5K')
        response = self.client.post('/api/billing/redeem/', {'code': code.code, 'credits': 99999})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['credits_added'], 5000)
        response = self.client.get('/api/billing/plans/')
        self.assertEqual(response.status_code, 200)
        addons = {row['code']: row for row in response.data['addons']}
        self.assertFalse(addons['CREDIT_50K']['eligible'])
        self.assertTrue(addons['TRIAL_5K']['eligible'])
        self.assertNotIn('reference_cost', addons['TRIAL_5K'])

    def test_rejected_api_code_stays_unused(self):
        code = self.code('CREDIT_100K')
        response = self.client.post('/api/billing/redeem/', {'code': code.code})
        self.assertEqual(response.status_code, 400)
        code.refresh_from_db()
        self.assertFalse(code.is_used)

    def test_two_users_cannot_redeem_same_code_and_failure_is_atomic(self):
        code = self.code('TRIAL_5K')
        with patch('core.services.credit_ledger_service.grant_batch_credits', side_effect=RuntimeError('ledger unavailable')):
            with self.assertRaises(RuntimeError):
                redeem_addon_code(self.user, code.code)
        code.refresh_from_db()
        self.assertFalse(code.is_used)
        redeem_addon_code(self.user, code.code)
        other = get_user_model().objects.create_user('other-addon')
        with self.assertRaises(AddonError):
            redeem_addon_code(other, code.code)
        self.assertEqual(CreditGrantBatch.objects.filter(addon_version=code.addon_version).count(), 1)

    def test_admin_batch_generation_and_immutable_version_admin(self):
        from django.contrib.admin.models import LogEntry
        from django.test import Client
        admin = get_user_model().objects.create_superuser('addon-admin', password='test')
        client = Client()
        client.force_login(admin)
        response = client.post('/admin/core/rechargecode/batch-generate/', {
            'count': 2, 'code_type': 'ADDON', 'addon_version': self.version('TRIAL_5K').pk,
        })
        self.assertEqual(response.status_code, 200)
        codes = RechargeCode.objects.filter(code_type='ADDON')
        self.assertEqual(codes.count(), 2)
        self.assertTrue(all(item.credits == 0 and item.created_by_id == admin.pk for item in codes))
        self.assertEqual(LogEntry.objects.filter(user=admin).count(), 2)
        for url in ('/admin/core/addonproduct/', '/admin/core/addonproductversion/', '/admin/core/userconcurrencygrant/'):
            self.assertEqual(client.get(url).status_code, 200)
        response = client.get(f'/admin/core/addonproductversion/{self.version("TRIAL_5K").pk}/change/')
        self.assertEqual(response.status_code, 200)

    def test_expired_code_exact_boundary(self):
        code = self.code('TRIAL_5K')
        code.expires_at = self.now
        code.save()
        with patch('django.utils.timezone.now', return_value=self.now):
            with self.assertRaises(AddonError):
                redeem_addon_code(self.user, code.code)

    def test_renewal_after_first_period_uses_original_month_end(self):
        jan31 = timezone.make_aware(datetime(2027, 1, 31, 12))
        self.subscribe(start=jan31 - timedelta(days=1), end=jan31 + timedelta(days=200))
        with patch('django.utils.timezone.now', return_value=jan31):
            redeem_addon_code(self.user, self.code('SLOTS_8').code)
            redeem_addon_code(self.user, self.code('SLOTS_8', 'SECOND').code)
        with patch('django.utils.timezone.now', return_value=jan31 + timedelta(days=35)):
            redeem_addon_code(self.user, self.code('SLOTS_8', 'THIRD').code)
        tail = UserConcurrencyGrant.objects.order_by('-expires_at').first()
        self.assertEqual((tail.expires_at.month, tail.expires_at.day, tail.anchor_day), (4, 30, 31))


class RuntimeAddonSlotTests(TestCase):
    def task(self):
        from unittest.mock import Mock
        return Mock(pk=73, task_type='ai_screen', created_by_id=18,
                    config={'ai_slot_lease': {'slots': 8}, 'progress': 10})

    def test_running_task_refresh_releases_before_wait_then_uses_new_limit(self):
        from core.services.concurrency_service import refresh_task_slots
        task = self.task()
        with patch('core.services.concurrency_service.get_user_concurrency', side_effect=[4, 8]), \
             patch('core.services.concurrency_service.release') as release, \
             patch('core.services.concurrency_service.try_acquire', side_effect=[False, True]) as acquire, \
             patch('core.services.concurrency_service.time.sleep'):
            self.assertEqual(refresh_task_slots(task), 8)
        release.assert_called_once_with(73)
        self.assertEqual(acquire.call_args_list[0].kwargs['user_limit'], 4)
        self.assertEqual(acquire.call_args_list[1].kwargs['user_limit'], 8)
        self.assertEqual(task.config['progress'], 10)

    def test_stopped_waiter_releases_lease_and_does_not_start_calls(self):
        from core.services.concurrency_service import refresh_task_slots
        with patch('core.services.concurrency_service.release') as release, \
             patch('core.services.concurrency_service.try_acquire') as acquire:
            self.assertEqual(refresh_task_slots(self.task(), stop_checker=lambda: True), 0)
            self.assertTrue(release.called)
            acquire.assert_not_called()

    def test_quality_model_workers_do_not_exceed_held_lease(self):
        from core.quality.executors.qa_eval import QAEvalHandler
        engine = object.__new__(QAEvalHandler)
        engine.model_ids = ['deepseek', 'qwen']
        engine.task_obj = SimpleNamespace(config={'ai_slot_lease': {'slots': 1}})
        self.assertEqual(engine._model_workers(), 1)
