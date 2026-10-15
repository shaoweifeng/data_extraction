from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
from threading import Barrier
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections, connection
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from core.ai import AIQuotaService, AIUsageContext, AIUsageSettlementService, TokenUsageAccumulator
from core.ai.usage_schema import normalize_provider_usage
from core.models import Project, Task
from core.models_billing import (
    CreditAccount, CreditAllocation, CreditGrantBatch, CreditReservation,
    CreditTransaction, RechargeCode,
)
from core.services.credit_ledger_service import (
    account_reconciliation, consume_batch_credits, grant_batch_credits,
    redeem_credit_code, refund_consumption, release_reservation,
    reserve_credits, settle_reservation,
)
from core.workflow.services.task_launcher import create_step_task


User = get_user_model()


class CreditBatchLedgerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ledger-user', password='pw')
        self.account = CreditAccount.objects.get(user=self.user)

    def grant(self, amount, key, *, expires_at=None, batch_type='WELCOME'):
        return grant_batch_credits(
            self.user,
            amount,
            batch_type=batch_type,
            batch_key=key,
            expires_at=expires_at,
            note=key,
        )

    def test_grant_is_idempotent_and_fefo_consumption_spans_batches(self):
        soon = timezone.now() + timedelta(days=1)
        first = self.grant(30, 'grant:first', expires_at=soon)
        self.assertEqual(self.grant(30, 'grant:first', expires_at=soon), first)
        self.grant(40, 'grant:second')

        consumed = consume_batch_credits(
            self.user, 35, idempotency_key='consume:one', note='test',
        )

        self.account.refresh_from_db()
        batches = list(CreditGrantBatch.objects.order_by('created_at'))
        self.assertEqual(self.account.balance, 35)
        self.assertEqual(self.account.total_granted, 70)
        self.assertEqual(self.account.total_consumed, 35)
        self.assertEqual([batch.remaining_amount for batch in batches], [0, 35])
        self.assertEqual(
            list(CreditAllocation.objects.filter(transaction=consumed).values_list('amount', flat=True)),
            [30, 5],
        )
        self.assertEqual(account_reconciliation(self.account)['difference'], 0)

    def test_refund_returns_to_original_batches(self):
        self.grant(20, 'grant:a', expires_at=timezone.now() + timedelta(days=1))
        self.grant(30, 'grant:b')
        consumed = consume_batch_credits(self.user, 25, idempotency_key='consume:refund')

        refunded = refund_consumption(
            consumed, 10, idempotency_key='refund:one', note='partial refund',
        )

        self.account.refresh_from_db()
        self.assertEqual(refunded.reverses_transaction, consumed)
        self.assertEqual(self.account.balance, 35)
        self.assertEqual(self.account.total_consumed, 15)
        self.assertEqual(account_reconciliation(self.account)['difference'], 0)

    def test_reservation_releases_unused_amount_on_settlement(self):
        self.grant(100, 'grant:reserve')
        reservation = reserve_credits(
            self.user,
            60,
            task=None,
            idempotency_key='reserve:one',
            pricing_version='test-v2',
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, 40)

        transaction = settle_reservation(reservation, 45)

        self.account.refresh_from_db()
        reservation.refresh_from_db()
        batch = CreditGrantBatch.objects.get(batch_key='grant:reserve')
        self.assertEqual(transaction.amount, -45)
        self.assertEqual(self.account.balance, 55)
        self.assertEqual(batch.remaining_amount, 55)
        self.assertEqual(batch.reserved_amount, 0)
        self.assertEqual(reservation.settled_credits, 45)
        self.assertEqual(reservation.platform_covered_credits, 0)

    def test_retry_with_less_remaining_work_reuses_original_reservation(self):
        self.grant(100, 'grant:retry')
        original = reserve_credits(
            self.user,
            60,
            task=None,
            idempotency_key='reserve:retry',
            pricing_version='test-v2',
        )

        retried = reserve_credits(
            self.user,
            20,
            task=None,
            idempotency_key='reserve:retry',
            pricing_version='test-v2',
        )

        self.account.refresh_from_db()
        self.assertEqual(retried.pk, original.pk)
        self.assertEqual(self.account.balance, 40)
        self.assertEqual(CreditReservation.objects.count(), 1)

    def test_reservation_supplements_from_available_balance(self):
        self.grant(100, 'grant:extra')
        reservation = reserve_credits(
            self.user,
            20,
            task=None,
            idempotency_key='reserve:extra',
            pricing_version='test-v2',
        )

        settle_reservation(reservation, 30)

        self.account.refresh_from_db()
        reservation.refresh_from_db()
        self.assertEqual(self.account.balance, 70)
        self.assertEqual(reservation.actual_credits, 30)
        self.assertEqual(reservation.settled_credits, 30)
        self.assertEqual(account_reconciliation(self.account)['difference'], 0)

    def test_post_call_overage_never_creates_negative_balance(self):
        self.grant(100, 'grant:overage')
        reservation = reserve_credits(
            self.user,
            80,
            task=None,
            idempotency_key='reserve:overage',
            pricing_version='test-v2',
        )

        settle_reservation(reservation, 120)

        self.account.refresh_from_db()
        reservation.refresh_from_db()
        self.assertEqual(self.account.balance, 0)
        self.assertEqual(reservation.actual_credits, 120)
        self.assertEqual(reservation.settled_credits, 100)
        self.assertEqual(reservation.platform_covered_credits, 20)
        self.assertEqual(account_reconciliation(self.account)['difference'], 0)

    def test_expired_reserved_credit_is_not_returned_to_available_balance(self):
        self.grant(20, 'grant:expires', expires_at=timezone.now() + timedelta(days=1))
        reservation = reserve_credits(
            self.user,
            20,
            task=None,
            idempotency_key='reserve:expires',
            pricing_version='test-v2',
        )
        CreditGrantBatch.objects.filter(batch_key='grant:expires').update(
            expires_at=timezone.now() - timedelta(seconds=1),
        )

        released = release_reservation(reservation, status='expired', reason='timeout')

        self.account.refresh_from_db()
        batch = CreditGrantBatch.objects.get(batch_key='grant:expires')
        self.assertEqual(released, 0)
        self.assertEqual(self.account.balance, 0)
        self.assertEqual(batch.remaining_amount, 0)
        self.assertEqual(batch.reserved_amount, 0)

    def test_credit_code_creates_purchased_batch_once(self):
        code = RechargeCode.objects.create(code='V2-CREDIT-ONE', code_type='CREDIT', credits=25)

        transaction = redeem_credit_code(self.user, code.code)

        self.account.refresh_from_db()
        code.refresh_from_db()
        self.assertEqual(transaction.txn_type, 'recharge')
        self.assertEqual(self.account.balance, 25)
        self.assertTrue(code.is_used)
        self.assertTrue(CreditGrantBatch.objects.filter(
            batch_key=f'recharge-code:{code.pk}', batch_type='PURCHASED',
        ).exists())
        with self.assertRaisesMessage(ValueError, 'code_invalid'):
            redeem_credit_code(self.user, code.code)

    @override_settings(CREDIT_BATCH_LEDGER_ENABLED=True)
    def test_redeem_api_uses_batch_ledger_when_enabled(self):
        code = RechargeCode.objects.create(code='V2-API-CREDIT', code_type='CREDIT', credits=12)
        client = Client()
        client.force_login(self.user)

        response = client.post(
            '/api/billing/redeem/',
            {'code': code.code},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['new_balance'], 12)
        self.assertTrue(CreditGrantBatch.objects.filter(
            batch_key=f'recharge-code:{code.pk}',
            remaining_amount=12,
        ).exists())

    def test_expiration_command_is_preview_first_and_writes_expiry_ledger(self):
        self.grant(15, 'grant:already-expired')
        CreditGrantBatch.objects.filter(batch_key='grant:already-expired').update(
            expires_at=timezone.now() - timedelta(seconds=1),
        )

        call_command('process_credit_expirations', stdout=StringIO())
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, 15)

        call_command('process_credit_expirations', apply=True, stdout=StringIO())

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, 0)
        self.assertTrue(CreditTransaction.objects.filter(
            account=self.account,
            txn_type='expire',
            amount=-15,
        ).exists())
        self.assertEqual(account_reconciliation(self.account)['difference'], 0)


@override_settings(
    CREDIT_BATCH_LEDGER_ENABLED=True,
    BILLING_RESERVATION_ENABLED=True,
    MODEL_WEIGHTED_BILLING_ENABLED=True,
    MODEL_WEIGHTED_BILLING_ALLOW_DRAFT=True,
    MODEL_WEIGHTED_BILLING_PRICING_VERSION='credit-v2-draft-2026-10-13',
)
class WeightedReservationIntegrationTests(TestCase):
    @override_settings(MODEL_WEIGHTED_BILLING_PRICING_VERSION='frozen-v2')
    def test_ai_task_freezes_pricing_version_when_created(self):
        user = User.objects.create_user('freeze-user', password='pw')
        project = Project.objects.create(name='Freeze', owner=user)

        task = create_step_task(project.pk, 'ai_screen', user.pk, {})

        self.assertEqual(task.config['billing_pricing_version'], 'frozen-v2')

    def test_preflight_reserves_and_weighted_settlement_releases_difference(self):
        user = User.objects.create_user('weighted-user', password='pw')
        project = Project.objects.create(name='Weighted', owner=user)
        task = Task.objects.create(project=project, task_type='ai_screen', created_by=user)
        grant_batch_credits(
            user,
            20,
            batch_type='WELCOME',
            batch_key='weighted:welcome',
        )
        estimated = AIQuotaService.preflight(
            user,
            1,
            ['qwen3-7-flash'],
            feature='ai_screen',
            task=task,
        )
        usage = TokenUsageAccumulator()
        usage.add(normalize_provider_usage(
            {'prompt_tokens': 1000, 'completion_tokens': 100, 'total_tokens': 1100},
            provider='qwen',
            model_id='qwen3-7-flash',
            provider_model='qwen3.7-flash',
            region='cn-beijing',
        ), model_id='qwen3-7-flash')

        result = AIUsageSettlementService.settle(AIUsageContext(
            feature='AI筛选',
            user=user,
            project=project,
            task=task,
            model_ids=['qwen3-7-flash'],
            idempotency_key='weighted:settlement',
        ), usage)

        account = CreditAccount.objects.get(user=user)
        reservation = CreditReservation.objects.get(task=task)
        self.assertEqual(estimated, 1)
        self.assertEqual(result['credits_actual'], 1)
        self.assertEqual(result['credits_consumed'], 1)
        self.assertEqual(account.balance, 19)
        self.assertEqual(reservation.status, 'settled')
        self.assertEqual(reservation.settled_credits, 1)
        self.assertEqual(task.model_usage_details.count(), 1)
        self.assertIsNotNone(task.model_usage_details.get().rate_id)


class CreditV2InitializationCommandTests(TestCase):
    def test_command_resets_internal_accounts_and_refuses_second_run(self):
        regular = User.objects.create_user('cutover-user', password='pw')
        admin = User.objects.create_superuser('cutover-admin', password='pw')
        account = CreditAccount.objects.get(user=regular)
        account.balance = 999
        account.total_granted = 999
        account.total_consumed = 10
        account.save()
        CreditTransaction.objects.create(
            account=account,
            txn_type='grant',
            amount=999,
            balance_after=999,
        )
        old_code = RechargeCode.objects.create(code='OLD-CODE', credits=100)

        output = StringIO()
        call_command(
            'initialize_credit_v2',
            initial_credits=200,
            confirm='RESET-CREDIT-V2',
            stdout=output,
        )

        account.refresh_from_db()
        admin.credit_account.refresh_from_db()
        old_code.refresh_from_db()
        self.assertEqual(account.balance, 200)
        self.assertEqual(account.total_granted, 200)
        self.assertEqual(account.total_consumed, 0)
        self.assertEqual(admin.credit_account.balance, 0)
        self.assertIsNotNone(old_code.expires_at)
        self.assertEqual(account_reconciliation(account)['difference'], 0)
        with self.assertRaises(CommandError):
            call_command(
                'initialize_credit_v2',
                initial_credits=200,
                confirm='RESET-CREDIT-V2',
                stdout=StringIO(),
            )


@skipUnless(connection.vendor == 'mysql', '需要 MySQL 测试数据库')
class CreditLedgerConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def test_concurrent_reservations_cannot_spend_the_same_batch_twice(self):
        user = User.objects.create_user('reservation-race', password='pw')
        grant_batch_credits(
            user,
            10,
            batch_type='WELCOME',
            batch_key='race:welcome',
        )
        barrier = Barrier(2)

        def reserve(index):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                reserve_credits(
                    User.objects.get(pk=user.pk),
                    7,
                    task=None,
                    idempotency_key=f'race:reservation:{index}',
                    pricing_version='test-v2',
                )
                return 'reserved'
            except ValueError:
                return 'insufficient'
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(reserve, range(2)))

        account = CreditAccount.objects.get(user=user)
        batch = CreditGrantBatch.objects.get(batch_key='race:welcome')
        self.assertEqual(sorted(outcomes), ['insufficient', 'reserved'])
        self.assertEqual(account.balance, 3)
        self.assertEqual(batch.remaining_amount, 3)
        self.assertEqual(batch.reserved_amount, 7)
