"""积分消费和充值操作的事务一致性测试。"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from core.models_billing import CreditAccount, CreditTransaction, RechargeCode
from core.services.billing_service import consume_credits


User = get_user_model()


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
