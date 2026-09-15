from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless

from django.db import close_old_connections, connection
from django.test import TransactionTestCase

from ..services.registration import RegistrationConflict, register_user

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
