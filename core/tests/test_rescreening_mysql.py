"""Optional real MySQL lock tests; never use SQLite to claim race safety."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.test import TransactionTestCase, override_settings
from core.models import Project, Task
from core.models_billing import CreditAccount, CreditReservation, CreditTransaction
from core.services.credit_ledger_service import (CreditLedgerError, account_reconciliation,
    grant_batch_credits, reserve_credits, extend_reservation, settle_reservation)


@skipUnless(connection.vendor == 'mysql', '复筛积分锁竞争需要独立 MySQL 测试库')
@override_settings(CREDIT_BATCH_LEDGER_ENABLED=True)
class RescreenMySQLReservationTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('rescreen-credit-race')
        self.project = Project.objects.create(name='Rescreen credit race', owner=self.user)
        grant_batch_credits(self.user, 100, batch_type='manual', batch_key='race-funds')
        self.account = CreditAccount.objects.get(user=self.user)
        self.initial = self.account.balance

    def hold(self):
        task = Task.objects.create(project=self.project, task_type='rescreen_ai', created_by=self.user)
        return reserve_credits(self.user, 1, task=task, idempotency_key=f'race-hold:{task.pk}',
                               pricing_version=settings.MODEL_WEIGHTED_BILLING_PRICING_VERSION)

    def race(self, ids, action):
        barrier = Barrier(2)
        def execute(pk):
            close_old_connections()
            try:
                reservation = CreditReservation.objects.get(pk=pk)
                barrier.wait(timeout=5)
                action(reservation)
                return 'ok'
            except CreditLedgerError:
                return 'rejected'
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(execute, ids))

    def test_same_hold_concurrent_growth_does_not_reserve_twice(self):
        hold = self.hold()
        target = self.initial - 10
        self.assertEqual(self.race([hold.pk]*2, lambda row: extend_reservation(row, target)), ['ok', 'ok'])
        hold.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(hold.reserved_credits, target)
        self.assertEqual(self.account.balance, 10)
        self.assertEqual(account_reconciliation(self.account)['difference'], 0)

    def test_two_holds_cannot_grow_past_one_available_balance(self):
        holds = [self.hold(), self.hold()]
        target = self.initial - 10
        self.assertEqual(sorted(self.race([row.pk for row in holds], lambda row: extend_reservation(row, target))), ['ok', 'rejected'])
        self.account.refresh_from_db()
        self.assertGreaterEqual(self.account.balance, 0)
        self.assertEqual(account_reconciliation(self.account)['difference'], 0)

    def test_concurrent_settlement_consumes_once(self):
        hold = self.hold()
        extend_reservation(hold, 50)
        self.assertEqual(self.race([hold.pk]*2, lambda row: settle_reservation(row, 20)), ['ok', 'ok'])
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, self.initial-20)
        self.assertEqual(CreditTransaction.objects.filter(task=hold.task, txn_type='consume').count(), 1)
        self.assertEqual(account_reconciliation(self.account)['difference'], 0)


@skipUnless(connection.vendor == 'mysql', '复筛导出/QA 导入竞争需要独立 MySQL 测试库')
class RescreenMySQLDeliveryTests(TransactionTestCase):
    def setUp(self):
        from core.rescreening.models import RescreenCorpus, RescreenImportBatch, RescreenReference, RescreenReferenceRawMetadata
        from core.rescreening.services.workspace import save_review
        from core.services.project_service import initialize_project
        self.user = get_user_model().objects.create_user('rescreen-delivery-race')
        self.project = Project.objects.create(name='Delivery race', owner=self.user)
        initialize_project(self.project, self.user)
        corpus = RescreenCorpus.objects.create(project=self.project, revision=1, active_reference_count=1)
        batch = RescreenImportBatch.objects.create(project=self.project, corpus=corpus, status='completed', source_type='pdf',
            base_revision=0, target_revision=1, idempotency_key='fixture', request_hash='a'*64, limits_snapshot={})
        ref = RescreenReference.objects.create(project=self.project, corpus=corpus, import_batch=batch, source_key='fixture',
            introduced_revision=1, title='Race source', normalized_title_hash='b'*64, record_hash='c'*64)
        RescreenReferenceRawMetadata.objects.create(reference=ref, raw_fields={}, source_format='pdf', raw_hash='d'*64, raw_size_bytes=2)
        save_review(project=self.project, user=self.user, reference_id=ref.pk, input_version=1, expected_version=0,
            criteria_revision_id=None, suggestion_id=None, suggestion_revision=0, decision='included')

    def race(self, action):
        from core.rescreening.errors import RescreenError
        barrier = Barrier(2)
        def execute(index):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return action(index)
            except RescreenError as exc:
                return exc.code
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(execute, range(2)))

    def test_same_export_key_serializes_to_one_receipt(self):
        from unittest.mock import patch
        from core.rescreening.services.exports import fingerprint, start_export
        from core.rescreening.models import RescreenExport
        current = fingerprint(self.project)
        with patch('core.rescreening.services.exports._dispatch'):
            ids = self.race(lambda index: start_export(project=self.project, user=self.user, format='xml', scope='all',
                mode='final', idempotency_key='same-race', expected_fingerprint=current).pk)
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(RescreenExport.objects.count(), 1)

    def test_concurrent_handoff_never_duplicates_qa(self):
        from core.rescreening.services.qa_handoff import preview, handoff
        from core.models import QAReference
        token = preview(self.project)['confirmation_token']
        results = self.race(lambda index: handoff(project=self.project, user=self.user, confirmation_token=token)['imported'])
        self.assertCountEqual(results, [1, 'qa_source_changed'])
        self.assertEqual(QAReference.objects.count(), 1)
