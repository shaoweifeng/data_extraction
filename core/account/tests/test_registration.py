import json
import importlib
from datetime import timedelta
from io import StringIO
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.core.management import call_command
from django.core import mail
from django.urls import reverse
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from core.models import UserProfile
from core.models_billing import CreditAccount, CreditTransaction
from core.services.billing_service import get_or_create_account, grant_credits

from ..models import AccountEmail, AccountVerificationToken
from ..services.client_ip import get_client_ip
from ..services.rate_limit import (
    RateLimitDecision,
    RateLimitUnavailable,
    consume_rate_limit,
)
from ..services.registration import register_pending_user, register_user
from ..services.verification import activate_email, digest_token, issue_email_activation_token
from ..tasks import send_verification_email

User = get_user_model()

STRONG_PASSWORD = 'Correct-Horse-Battery-Staple-2026'


class AccountFoundationTests(TestCase):
    def test_user_signal_only_creates_zero_balance_account(self):
        user = User.objects.create_user('zero-balance-user', password=STRONG_PASSWORD)

        account = CreditAccount.objects.get(user=user)
        self.assertEqual(account.balance, 0)
        self.assertEqual(account.total_granted, 0)
        self.assertFalse(CreditTransaction.objects.filter(account=account).exists())

    def test_missing_account_fallback_is_zero_balance(self):
        user = User.objects.create_user('missing-account-user', password=STRONG_PASSWORD)
        user.credit_account.delete()

        account = get_or_create_account(user)

        self.assertEqual(account.balance, 0)
        self.assertEqual(account.total_granted, 0)

    def test_grant_idempotency_key_only_applies_credit_once(self):
        user = User.objects.create_user('idempotent-user', password=STRONG_PASSWORD)

        first = grant_credits(user, 200, idempotency_key=f'welcome_grant:{user.pk}')
        second = grant_credits(user, 200, idempotency_key=f'welcome_grant:{user.pk}')

        user.credit_account.refresh_from_db()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(user.credit_account.balance, 200)
        self.assertEqual(CreditTransaction.objects.count(), 1)

    def test_account_email_normalizes_before_save(self):
        user = User.objects.create_user('email-user', password=STRONG_PASSWORD)
        identity = AccountEmail.objects.create(
            user=user,
            email='  User.Name@Example.COM  ',
            normalized_email='ignored@example.com',
        )

        self.assertEqual(identity.email, 'user.name@example.com')
        self.assertEqual(identity.normalized_email, 'user.name@example.com')

    def test_account_audit_reports_counts_without_email_values(self):
        User.objects.create_user('audit-empty-email', password=STRONG_PASSWORD)
        output = StringIO()

        call_command('audit_accounts', '--json', stdout=output)

        report = json.loads(output.getvalue())
        self.assertTrue(report['account_email_table_present'])
        self.assertGreaterEqual(report['users_without_email'], 1)
        self.assertNotIn('audit-empty-email', output.getvalue())

    def test_phase_two_backfill_only_claims_valid_unique_historical_emails(self):
        unique = User.objects.create_user(
            'backfill-unique', email=' Unique@Example.COM ', password=STRONG_PASSWORD,
        )
        duplicate_a = User.objects.create_user(
            'backfill-duplicate-a', email='duplicate@example.com', password=STRONG_PASSWORD,
        )
        duplicate_b = User.objects.create_user(
            'backfill-duplicate-b', email='DUPLICATE@example.com', password=STRONG_PASSWORD,
        )
        invalid = User.objects.create_user(
            'backfill-invalid', email='not-an-email', password=STRONG_PASSWORD,
        )
        migration = importlib.import_module('core.account.migrations.0002_email_verification')
        from django.apps import apps

        migration.backfill_unique_account_emails(apps, None)

        self.assertEqual(
            AccountEmail.objects.get(user=unique).normalized_email,
            'unique@example.com',
        )
        self.assertFalse(AccountEmail.objects.filter(user=duplicate_a).exists())
        self.assertFalse(AccountEmail.objects.filter(user=duplicate_b).exists())
        self.assertFalse(AccountEmail.objects.filter(user=invalid).exists())


class RegistrationServiceTests(TestCase):
    def test_registration_creates_complete_zero_balance_account(self):
        user = register_user(
            username='new-researcher',
            email='researcher@example.com',
            password=STRONG_PASSWORD,
        )

        self.assertTrue(user.check_password(STRONG_PASSWORD))
        self.assertTrue(UserProfile.objects.filter(user=user).exists())
        self.assertEqual(user.credit_account.balance, 0)
        self.assertEqual(user.account_email.normalized_email, 'researcher@example.com')
        self.assertFalse(CreditTransaction.objects.filter(account=user.credit_account).exists())

    def test_registration_rolls_back_all_records_on_email_failure(self):
        with patch(
            'core.account.services.registration.AccountEmail.objects.create',
            side_effect=IntegrityError('email insert failed'),
        ):
            with self.assertRaises(IntegrityError):
                register_user(
                    username='rollback-user',
                    email='rollback@example.com',
                    password=STRONG_PASSWORD,
                )

        self.assertFalse(User.objects.filter(username='rollback-user').exists())
        self.assertFalse(AccountEmail.objects.filter(email='rollback@example.com').exists())


@override_settings(
    ACCOUNT_REGISTRATION_V2_ENABLED=True,
    ACCOUNT_RATE_LIMIT_ENABLED=False,
    REQUIRE_EMAIL_VERIFICATION=False,
)
class RegistrationApiTests(TestCase):
    def post(self, payload, content_type='application/json', **extra):
        return self.client.post('/api/auth/register/', payload, content_type=content_type, **extra)

    def valid_payload(self, **overrides):
        payload = {
            'username': 'api-researcher',
            'email': 'Researcher@Example.COM',
            'password': STRONG_PASSWORD,
            'password_confirm': STRONG_PASSWORD,
        }
        payload.update(overrides)
        return payload

    def test_v2_registration_creates_normalized_identity_without_grant(self):
        response = self.post(self.valid_payload())

        self.assertEqual(response.status_code, 201)
        user = User.objects.get(username='api-researcher')
        self.assertEqual(user.email, 'researcher@example.com')
        self.assertEqual(user.account_email.normalized_email, 'researcher@example.com')
        self.assertEqual(user.credit_account.balance, 0)

    def test_v2_registration_requires_matching_password_confirmation(self):
        response = self.post(self.valid_payload(password_confirm='different-password'))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'validation_error')
        self.assertIn('password_confirm', response.json()['fields'])
        self.assertFalse(User.objects.filter(username='api-researcher').exists())

    def test_v2_registration_requires_email(self):
        payload = self.valid_payload()
        payload.pop('email')

        response = self.post(payload)

        self.assertEqual(response.status_code, 400)
        self.assertIn('email', response.json()['fields'])

    def test_v2_registration_rejects_short_password(self):
        response = self.post(self.valid_payload(password='short7!', password_confirm='short7!'))

        self.assertEqual(response.status_code, 400)
        self.assertIn('password', response.json()['fields'])

    def test_v2_registration_rejects_normalized_duplicate_email(self):
        first = self.post(self.valid_payload())
        second = self.post(self.valid_payload(
            username='another-researcher',
            email='researcher@example.com',
        ))

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 400)
        self.assertIn('email', second.json()['fields'])

    def test_v2_registration_does_not_claim_historical_user_email(self):
        User.objects.create_user(
            'historical-user',
            email='historical@example.com',
            password=STRONG_PASSWORD,
        )

        response = self.post(self.valid_payload(
            email='Historical@Example.COM',
        ))

        self.assertEqual(response.status_code, 400)
        self.assertIn('email', response.json()['fields'])

    def test_registration_route_keeps_legacy_reverse_name(self):
        self.assertEqual(reverse('register'), '/api/auth/register/')

    def test_v2_registration_rejects_oversized_request_before_parsing(self):
        response = self.post(
            self.valid_payload(),
            CONTENT_LENGTH='20000',
        )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()['code'], 'request_too_large')

    def test_v2_registration_rejects_non_json_content(self):
        response = self.post(self.valid_payload(), content_type='application/x-www-form-urlencoded')

        self.assertEqual(response.status_code, 415)
        self.assertEqual(response.json()['code'], 'invalid_content_type')

    def test_v2_registration_rejects_json_array(self):
        response = self.post(['not', 'an', 'object'])

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'validation_error')

    @override_settings(REQUIRE_EMAIL_VERIFICATION=True)
    @patch('core.account.api.views.queue_verification_email', return_value=True)
    def test_verification_registration_creates_inactive_zero_balance_user(self, queue_email):
        response = self.post(self.valid_payload())

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()['requires_email_verification'])
        self.assertTrue(response.json()['email_delivery_queued'])
        self.assertEqual(response.json()['resend_after'], 60)
        user = User.objects.get(username='api-researcher')
        self.assertFalse(user.is_active)
        self.assertEqual(user.credit_account.balance, 0)
        self.assertIsNone(user.account_email.verified_at)
        token = AccountVerificationToken.objects.get(user=user)
        queue_email.assert_called_once()
        self.assertEqual(queue_email.call_args.args[0], token.pk)
        self.assertNotEqual(queue_email.call_args.args[1], token.token_digest)

    @override_settings(REGISTRATION_ENABLED=False)
    def test_registration_can_be_closed(self):
        response = self.post(self.valid_payload())

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['code'], 'registration_closed')

    @patch('core.account.api.views.consume_rate_limit')
    @override_settings(ACCOUNT_RATE_LIMIT_ENABLED=True)
    def test_rate_limit_returns_retry_after(self, consume):
        consume.return_value = RateLimitDecision(False, count=20, retry_after=31, key='key')

        response = self.post(self.valid_payload())

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response['Retry-After'], '31')


class LegacyRegistrationCompatibilityTests(TestCase):
    @override_settings(
        ACCOUNT_REGISTRATION_V2_ENABLED=False,
        REQUIRE_EMAIL_VERIFICATION=False,
        BILLING_FREE_CREDITS_ON_REGISTER=200,
    )
    def test_legacy_registration_keeps_explicit_welcome_grant(self):
        response = self.client.post(
            '/api/auth/register/',
            {'username': 'legacy-user', 'email': '', 'password': 'legacy-password'},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 201)
        user = User.objects.get(username='legacy-user')
        self.assertEqual(user.credit_account.balance, 200)
        transaction = CreditTransaction.objects.get(account=user.credit_account)
        self.assertEqual(transaction.idempotency_key, f'legacy_welcome_grant:{user.pk}')
        self.assertFalse(AccountEmail.objects.filter(user=user).exists())


@override_settings(
    ACCOUNT_REGISTRATION_V2_ENABLED=True,
    ACCOUNT_RATE_LIMIT_ENABLED=False,
    REQUIRE_EMAIL_VERIFICATION=True,
    BILLING_FREE_CREDITS_ON_REGISTER=200,
)
class EmailVerificationTests(TestCase):
    def setUp(self):
        self.pending = register_pending_user(
            username='pending-user',
            email='pending@example.com',
            password=STRONG_PASSWORD,
        )

    def verify(self, token=None):
        return self.client.post(
            '/api/auth/email/verify/',
            {'token': token or self.pending.verification.raw_token},
            content_type='application/json',
        )

    def test_raw_token_is_not_persisted(self):
        record = self.pending.verification.record
        self.assertEqual(record.token_digest, digest_token(self.pending.verification.raw_token))
        self.assertNotEqual(record.token_digest, self.pending.verification.raw_token)

    def test_activation_verifies_email_activates_user_and_grants_once(self):
        response = self.verify()

        self.assertEqual(response.status_code, 200)
        self.pending.user.refresh_from_db()
        self.pending.user.account_email.refresh_from_db()
        self.pending.user.credit_account.refresh_from_db()
        self.assertTrue(self.pending.user.is_active)
        self.assertIsNotNone(self.pending.user.account_email.verified_at)
        self.assertEqual(self.pending.user.credit_account.balance, 200)
        self.assertEqual(
            CreditTransaction.objects.filter(
                idempotency_key=f'welcome_grant:{self.pending.user.pk}',
            ).count(),
            1,
        )

        repeated = self.verify()
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.json()['code'], 'already_verified')
        self.pending.user.credit_account.refresh_from_db()
        self.assertEqual(self.pending.user.credit_account.balance, 200)

    def test_pending_user_cannot_login(self):
        response = self.client.post(
            '/api/auth/login/',
            {'username': 'pending-user', 'password': STRONG_PASSWORD},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 401)

    def test_invalid_and_expired_tokens_are_rejected(self):
        invalid = self.verify('not-a-real-token')
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid.json()['code'], 'invalid_token')

        AccountVerificationToken.objects.filter(
            pk=self.pending.verification.record.pk,
        ).update(expires_at=timezone.now() - timedelta(seconds=1))
        expired = self.verify()
        self.assertEqual(expired.status_code, 400)
        self.assertEqual(expired.json()['code'], 'expired_token')

    def test_resend_revokes_old_token_and_keeps_generic_response(self):
        response = self.client.post(
            '/api/auth/email/resend/',
            {'email': 'Pending@Example.COM'},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('exists', response.json())
        self.pending.verification.record.refresh_from_db()
        self.assertIsNotNone(self.pending.verification.record.revoked_at)
        self.assertEqual(AccountVerificationToken.objects.filter(user=self.pending.user).count(), 2)

        unknown = self.client.post(
            '/api/auth/email/resend/',
            {'email': 'unknown@example.com'},
            content_type='application/json',
        )
        self.assertEqual(unknown.status_code, 200)
        self.assertEqual(unknown.json(), response.json())

    def test_email_task_sends_activation_link_and_records_delivery(self):
        record = self.pending.verification.record
        result = send_verification_email.run(record.pk, self.pending.verification.raw_token)

        self.assertEqual(result['status'], 'sent')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('/verify-email#token=', mail.outbox[0].body)
        self.assertIn(self.pending.verification.raw_token, mail.outbox[0].body)
        record.refresh_from_db()
        self.assertEqual(record.send_attempts, 1)
        self.assertIsNotNone(record.sent_at)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.console.EmailBackend')
    @patch('core.account.tasks.EmailMultiAlternatives')
    def test_console_email_task_logs_activation_link(self, message_class):
        record = self.pending.verification.record

        with self.assertLogs('core.account.tasks', level='INFO') as captured:
            result = send_verification_email.run(
                record.pk,
                self.pending.verification.raw_token,
            )

        self.assertEqual(result['status'], 'sent')
        message_class.return_value.send.assert_called_once_with(fail_silently=False)
        output = '\n'.join(captured.output)
        self.assertIn('[本地调试] 验证链接:', output)
        self.assertIn(self.pending.verification.raw_token, output)

    def test_service_activation_is_idempotent(self):
        first = activate_email(self.pending.verification.raw_token)
        second = activate_email(self.pending.verification.raw_token)
        self.assertFalse(first.already_verified)
        self.assertTrue(second.already_verified)

    def test_cleanup_pending_accounts_defaults_to_preview(self):
        historical = User.objects.create_user(
            'historical-inactive',
            email='historical-inactive@example.com',
            password=STRONG_PASSWORD,
            is_active=False,
        )
        AccountEmail.objects.create(
            user=historical,
            email=historical.email,
            normalized_email=historical.email,
        )
        User.objects.filter(pk=self.pending.user.pk).update(
            date_joined=timezone.now() - timedelta(days=8),
        )
        User.objects.filter(pk=historical.pk).update(
            date_joined=timezone.now() - timedelta(days=30),
        )
        output = StringIO()
        call_command('cleanup_pending_accounts', stdout=output)
        self.assertTrue(User.objects.filter(pk=self.pending.user.pk).exists())
        self.assertIn('预览模式', output.getvalue())

        call_command('cleanup_pending_accounts', '--delete', stdout=StringIO())
        self.assertFalse(User.objects.filter(pk=self.pending.user.pk).exists())
        self.assertTrue(User.objects.filter(pk=historical.pk).exists())


class LoginRateLimitTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('login-user', password=STRONG_PASSWORD)

    @override_settings(ACCOUNT_RATE_LIMIT_ENABLED=True)
    @patch('core.account.api.authentication_views.refund_rate_limit')
    @patch('core.account.api.authentication_views.consume_rate_limit')
    def test_successful_login_refunds_failure_reservations(self, consume, refund):
        consume.side_effect = [
            RateLimitDecision(True, key='ip-key'),
            RateLimitDecision(True, key='identifier-key'),
        ]

        response = self.client.post(
            '/api/auth/login/',
            {'username': self.user.username, 'password': STRONG_PASSWORD},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(refund.call_count, 2)

    @override_settings(ACCOUNT_RATE_LIMIT_ENABLED=True)
    @patch('core.account.api.authentication_views.consume_rate_limit')
    def test_blocked_ip_does_not_consume_identifier_bucket(self, consume):
        consume.return_value = RateLimitDecision(False, retry_after=25, key='ip-key')

        response = self.client.post(
            '/api/auth/login/',
            {'username': self.user.username, 'password': 'wrong-password'},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response['Retry-After'], '25')
        self.assertEqual(consume.call_count, 1)

    @override_settings(ACCOUNT_RATE_LIMIT_ENABLED=True)
    @patch('core.account.api.authentication_views.refund_rate_limit')
    @patch('core.account.api.authentication_views.consume_rate_limit')
    def test_failed_login_keeps_failure_reservations(self, consume, refund):
        consume.return_value = RateLimitDecision(True, key='rate-key')

        response = self.client.post(
            '/api/auth/login/',
            {'username': self.user.username, 'password': 'wrong-password'},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 401)
        refund.assert_not_called()


class TrustedClientIpTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @override_settings(TRUSTED_PROXY_IPS=['10.0.0.0/8'])
    def test_untrusted_remote_cannot_spoof_forwarded_header(self):
        request = self.factory.get(
            '/',
            REMOTE_ADDR='203.0.113.9',
            HTTP_X_FORWARDED_FOR='198.51.100.7',
        )
        self.assertEqual(get_client_ip(request), '203.0.113.9')

    @override_settings(TRUSTED_PROXY_IPS=['10.0.0.0/8'])
    def test_trusted_proxy_returns_closest_untrusted_address(self):
        request = self.factory.get(
            '/',
            REMOTE_ADDR='10.0.0.3',
            HTTP_X_FORWARDED_FOR='198.51.100.7, 10.0.0.2',
        )
        self.assertEqual(get_client_ip(request), '198.51.100.7')


@override_settings(
    ACCOUNT_RATE_LIMIT_ENABLED=True,
    RATE_LIMIT_REDIS_URL='redis://example.invalid/2',
)
class RateLimitServiceTests(TestCase):
    @patch('core.account.services.rate_limit._client')
    def test_atomic_result_is_exposed_without_plain_identifier(self, client):
        redis_client = Mock()
        redis_client.eval.return_value = [1, 2, 55]
        client.return_value = redis_client

        decision = consume_rate_limit(
            'register:email-request',
            'private@example.com',
            limit=5,
            window_seconds=60,
            fail_closed=True,
        )

        self.assertTrue(decision.allowed)
        self.assertNotIn('private@example.com', decision.key)
        self.assertEqual(decision.retry_after, 55)

    @patch('core.account.services.rate_limit._client', side_effect=OSError('redis down'))
    def test_registration_limit_fails_closed(self, _client):
        with self.assertRaises(RateLimitUnavailable):
            consume_rate_limit(
                'register:ip-request',
                '127.0.0.1',
                limit=20,
                window_seconds=60,
                fail_closed=True,
            )

    @patch('core.account.services.rate_limit._client', side_effect=OSError('redis down'))
    def test_login_limit_can_fail_open(self, _client):
        decision = consume_rate_limit(
            'login:ip',
            '127.0.0.1',
            limit=50,
            window_seconds=60,
            fail_closed=False,
        )

        self.assertTrue(decision.allowed)
        self.assertTrue(decision.unavailable)
