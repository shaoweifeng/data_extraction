from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless

from django.db import close_old_connections, connection
from django.test import TransactionTestCase
from django.utils import timezone

from core.models_billing import CreditTransaction

from ..models import AccountEmail
from ..services.email_change import (
    EmailChangeConflict,
    confirm_email_change,
    issue_email_change_token,
)
from ..services.password_reset import issue_password_reset_token, reset_password
from ..services.registration import RegistrationConflict, register_pending_user, register_user
from ..services.verification import InvalidVerificationToken, activate_email

STRONG_PASSWORD = 'Correct-Horse-Battery-Staple-2026'


@skipUnless(connection.vendor == 'mysql', '需要 MySQL 测试数据库')
class MySQLRegistrationConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def _run_concurrently(self, registrations):
        barrier = Barrier(len(registrations))

        def create(payload):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                user = register_user(password=STRONG_PASSWORD, **payload)
                return ('created', user.pk)
            except RegistrationConflict as exc:
                return ('conflict', exc.field)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=len(registrations)) as executor:
            return list(executor.map(create, registrations))

    def test_same_email_creates_at_most_one_identity(self):
        results = self._run_concurrently([
            {'username': 'email-race-a', 'email': 'race@example.com'},
            {'username': 'email-race-b', 'email': 'race@example.com'},
        ])

        self.assertEqual(sum(result[0] == 'created' for result in results), 1)
        self.assertIn(('conflict', 'email'), results)

    def test_same_username_creates_at_most_one_user(self):
        results = self._run_concurrently([
            {'username': 'username-race', 'email': 'race-a@example.com'},
            {'username': 'username-race', 'email': 'race-b@example.com'},
        ])

        self.assertEqual(sum(result[0] == 'created' for result in results), 1)
        self.assertIn(('conflict', 'username'), results)

    def test_concurrent_activation_grants_welcome_credit_once(self):
        pending = register_pending_user(
            username='activation-race',
            email='activation-race@example.com',
            password=STRONG_PASSWORD,
        )
        barrier = Barrier(2)

        def activate(_index):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                return activate_email(pending.verification.raw_token).already_verified
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(activate, range(2)))

        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(
            CreditTransaction.objects.filter(
                idempotency_key=f'welcome_grant:{pending.user.pk}',
            ).count(),
            1,
        )

    def test_password_reset_token_can_only_be_consumed_once(self):
        user = register_user(
            username='password-reset-race',
            email='password-reset-race@example.com',
            password=STRONG_PASSWORD,
        )
        AccountEmail.objects.filter(user=user).update(verified_at=timezone.now())
        issued = issue_password_reset_token(user)
        barrier = Barrier(2)

        def reset(index):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                reset_password(issued.raw_token, f'Concurrent-Password-{index}-2026')
                return 'changed'
            except InvalidVerificationToken:
                return 'invalid'
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(reset, range(2)))

        self.assertEqual(sorted(results), ['changed', 'invalid'])

    def test_concurrent_email_change_conflict_has_one_winner(self):
        users = []
        for suffix in ('a', 'b'):
            user = register_user(
                username=f'email-change-race-{suffix}',
                email=f'email-change-race-{suffix}@example.com',
                password=STRONG_PASSWORD,
            )
            AccountEmail.objects.filter(user=user).update(verified_at=timezone.now())
            users.append(user)
        issued = [
            issue_email_change_token(user, 'shared-new-email@example.com')
            for user in users
        ]
        barrier = Barrier(2)

        def confirm(item):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                confirm_email_change(item.raw_token)
                return 'changed'
            except EmailChangeConflict:
                return 'conflict'
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(confirm, issued))

        self.assertEqual(sorted(results), ['changed', 'conflict'])
        self.assertEqual(
            AccountEmail.objects.filter(normalized_email='shared-new-email@example.com').count(),
            1,
        )
