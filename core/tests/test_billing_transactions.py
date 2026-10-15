"""积分消费和充值操作的事务一致性测试。"""

import re
from unittest.mock import patch

from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

from core.models_billing import (
    CreditAccount, CreditTransaction, PlanCatalog, PlanPriceVersion, RechargeCode,
)
from core.services.billing_service import consume_credits
from core.services.recharge_code_service import generate_secure_recharge_code


User = get_user_model()


@override_settings(CREDIT_BATCH_LEDGER_ENABLED=False)
class BillingTransactionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('billing-user', password='pw')
        self.account = CreditAccount.objects.get(user=self.user)
        self.account.balance = 10
        self.account.total_consumed = 0
        self.account.save(update_fields=['balance', 'total_consumed'])

    def test_locked_consumption_prevents_double_spend(self):
        with patch.object(
            CreditAccount.objects,
            'select_for_update',
            wraps=CreditAccount.objects.select_for_update,
        ) as lock:
            transaction = consume_credits(self.user, 7, note='first')
        lock.assert_called_once_with()
        self.assertEqual(transaction.amount, -7)

        with self.assertRaises(ValueError):
            consume_credits(self.user, 4, note='would overdraw')

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, 3)
        self.assertEqual(self.account.total_consumed, 7)
        self.assertEqual(
            CreditTransaction.objects.filter(account=self.account, txn_type='consume').count(),
            1,
        )

    def test_ledger_failure_rolls_back_balance_update(self):
        with patch.object(CreditTransaction.objects, 'create', side_effect=RuntimeError('ledger unavailable')):
            with self.assertRaises(RuntimeError):
                consume_credits(self.user, 3)

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, 10)
        self.assertEqual(self.account.total_consumed, 0)

    def test_recharge_code_can_only_be_redeemed_once(self):
        code = RechargeCode.objects.create(code='REDEEM-ONCE', credits=8)
        client = Client()
        client.force_login(self.user)

        first = client.post('/api/billing/redeem/', {'code': code.code}, content_type='application/json')
        second = client.post('/api/billing/redeem/', {'code': code.code}, content_type='application/json')

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 410)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, 18)
        self.assertEqual(
            CreditTransaction.objects.filter(account=self.account, txn_type='recharge').count(),
            1,
        )

    def test_admin_list_handles_used_code_after_user_deletion(self):
        code = RechargeCode.objects.create(
            code='USED-BY-DELETED-USER',
            credits=8,
            is_used=True,
            used_by=self.user,
        )
        self.user.delete()
        code.refresh_from_db()
        self.assertIsNone(code.used_by)
        self.assertIn('已使用（原用户已删除）', str(code))

        admin_user = User.objects.create_superuser('billing-admin', password='pw')
        self.client.force_login(admin_user)
        response = self.client.get('/admin/core/rechargecode/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'USED-BY-DELETED-USER')
        self.assertContains(response, '已使用（原用户已删除）')


class RechargeCodeAdminTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser('code-admin', password='pw')
        self.client.force_login(self.admin_user)

    def test_secure_generator_uses_unambiguous_75_bit_format(self):
        codes = {generate_secure_recharge_code('sale bad') for _ in range(200)}

        self.assertEqual(len(codes), 200)
        for code in codes:
            self.assertRegex(code, r'^SALEBAD-[23456789A-HJ-NP-Z]{5}(?:-[23456789A-HJ-NP-Z]{5}){2}$')

    def test_batch_credit_codes_record_creator_batch_and_admin_log(self):
        response = self.client.post('/admin/core/rechargecode/batch-generate/', {
            'count': '3',
            'code_type': 'CREDIT',
            'credits': '25',
            'prefix': 'internal 01',
            'batch_no': '',
            'valid_months': '1',
            'note': '内部发放',
            'expires_at': '',
        })

        self.assertEqual(response.status_code, 200)
        rows = list(RechargeCode.objects.order_by('pk'))
        self.assertEqual(len(rows), 3)
        self.assertEqual({row.created_by_id for row in rows}, {self.admin_user.pk})
        self.assertEqual(len({row.batch_no for row in rows}), 1)
        self.assertTrue(rows[0].batch_no.startswith('ADMIN-'))
        self.assertTrue(all(row.credits == 25 for row in rows))
        self.assertTrue(all(re.match(r'^INTERNAL01-[23456789A-HJ-NP-Z-]+$', row.code) for row in rows))
        self.assertEqual(LogEntry.objects.filter(user=self.admin_user).count(), 3)

    def test_batch_plan_code_uses_published_version_and_zero_credit_value(self):
        plan = PlanCatalog.objects.create(code='LITE-ADMIN', name='Lite Admin')
        version = PlanPriceVersion.objects.create(
            plan=plan,
            version='admin-test-v1',
            status='published',
            monthly_price_cny=399,
            included_credits=20000,
            ai_call_slots=4,
            project_limit=5,
        )

        response = self.client.post('/admin/core/rechargecode/batch-generate/', {
            'count': '1',
            'code_type': 'PLAN',
            'credits': '99999',
            'plan_price_version': str(version.pk),
            'valid_months': '2',
            'prefix': 'lite',
            'batch_no': 'PLAN-ADMIN-TEST',
            'note': '',
            'expires_at': '',
        })

        self.assertEqual(response.status_code, 200)
        code = RechargeCode.objects.get()
        self.assertEqual(code.credits, 0)
        self.assertEqual(code.plan_price_version, version)
        self.assertEqual(code.valid_months, 2)
        self.assertEqual(code.created_by, self.admin_user)

    def test_manually_added_code_records_admin_creator(self):
        response = self.client.post('/admin/core/rechargecode/add/', {
            'code': 'MANUAL-AUDITED-CODE',
            'code_type': 'CREDIT',
            'credits': '10',
            'valid_months': '1',
            'batch_no': 'MANUAL-TEST',
            'note': '',
            'expires_at_0': '',
            'expires_at_1': '',
            '_save': '保存',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(RechargeCode.objects.get().created_by, self.admin_user)

    def test_batch_generation_requires_model_add_permission(self):
        staff = User.objects.create_user('readonly-staff', password='pw', is_staff=True)
        self.client.force_login(staff)

        response = self.client.get('/admin/core/rechargecode/batch-generate/')

        self.assertEqual(response.status_code, 403)
