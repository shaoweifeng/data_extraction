"""Real row-lock race checks, run only against a dedicated MySQL test database."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.test import TransactionTestCase, override_settings

from core.models_billing import AddonProduct, AddonProductVersion, CreditGrantBatch, RechargeCode
from core.services.billing_addon_service import AddonError, redeem_addon_code


@skipUnless(connection.vendor == 'mysql', '需要独立 MySQL 测试数据库验证行锁')
@override_settings(CREDIT_BATCH_LEDGER_ENABLED=True, PLAN_BILLING_ENABLED=True)
class MySQLAddonRedemptionTests(TransactionTestCase):
    def setUp(self):
        self.users = [get_user_model().objects.create_user(f'race-addon-{i}') for i in range(2)]
        product = AddonProduct.objects.create(code='RACE_TRIAL', name='追加体验', kind='TRIAL')
        version = AddonProductVersion.objects.create(
            product=product, kind='TRIAL', version='race-v1', status='published',
            reference_price_cny=99, credits=5000, valid_months=12, requires_subscription=False,
        )
        self.code = RechargeCode.objects.create(code='RACE-ADDON', credits=0, code_type='ADDON', addon_version=version)

    def run_race(self, users):
        barrier = Barrier(2)

        def redeem(user_id):
            close_old_connections()
            try:
                user = get_user_model().objects.get(pk=user_id)
                barrier.wait(timeout=5)
                redeem_addon_code(user, self.code.code)
                return 'success'
            except AddonError:
                return 'rejected'
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(redeem, users))

    def test_same_user_double_submission_grants_once(self):
        self.assertEqual(sorted(self.run_race([self.users[0].pk] * 2)), ['rejected', 'success'])
        self.assertEqual(CreditGrantBatch.objects.filter(batch_key=f'addon-code:{self.code.pk}').count(), 1)

    def test_two_users_racing_for_one_code_have_one_winner(self):
        self.assertEqual(sorted(self.run_race([user.pk for user in self.users])), ['rejected', 'success'])
        self.assertEqual(CreditGrantBatch.objects.filter(batch_key=f'addon-code:{self.code.pk}').count(), 1)
