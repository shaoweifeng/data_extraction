from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import authenticate, get_user_model
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from ..models import AccountEmail, AccountEmailChangeRequest, AccountVerificationToken
from ..services.email_change import issue_email_change_token
from ..services.password_reset import issue_password_reset_token
from ..tasks import (
    send_email_change_confirmation,
    send_email_changed_notice,
    send_password_changed_notice,
    send_password_reset_email,
)

User = get_user_model()
OLD_PASSWORD = 'Existing-Password-2026'
NEW_PASSWORD = 'Replacement-Password-2026'


@override_settings(ACCOUNT_RATE_LIMIT_ENABLED=False)
class AccountSecurityApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='security-user',
            email='security@example.com',
            password=OLD_PASSWORD,
        )
        self.identity = AccountEmail.objects.create(
            user=self.user,
            email='security@example.com',
            normalized_email='security@example.com',
            verified_at=timezone.now(),
        )

    def post(self, path, data, client=None):
        return (client or self.client).post(path, data, content_type='application/json')

    def test_login_accepts_username_and_verified_email(self):
        by_username = self.post('/api/auth/login/', {
            'username': 'security-user', 'password': OLD_PASSWORD,
        })
        self.assertEqual(by_username.status_code, 200)
        self.client.logout()

        by_email = self.post('/api/auth/login/', {
            'username': 'SECURITY@EXAMPLE.COM', 'password': OLD_PASSWORD,
        })
        self.assertEqual(by_email.status_code, 200)

    def test_unverified_email_is_not_a_login_identifier(self):
        self.identity.verified_at = None
        self.identity.save(update_fields=['verified_at'])

        response = self.post('/api/auth/login/', {
            'username': 'security@example.com', 'password': OLD_PASSWORD,
        })

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['error'], '用户名或密码错误')

    @patch('core.account.api.security_views.queue_password_reset_email', return_value=True)
    def test_forgot_password_is_generic_and_queues_for_verified_account(self, queue):
        existing = self.post('/api/auth/password/forgot/', {'email': 'SECURITY@EXAMPLE.COM'})
        unknown = self.post('/api/auth/password/forgot/', {'email': 'unknown@example.com'})

        self.assertEqual(existing.status_code, 200)
        self.assertEqual(unknown.status_code, 200)
        self.assertEqual(existing.json(), unknown.json())
        record = AccountVerificationToken.objects.get(user=self.user)
        queue.assert_called_once()
        self.assertEqual(queue.call_args.args[0], record.pk)
        self.assertNotEqual(queue.call_args.args[1], record.token_digest)

    @patch('core.account.api.security_views.queue_password_changed_notice', return_value=True)
    def test_reset_password_consumes_token_and_invalidates_existing_session(self, notice):
        old_session = Client()
        self.assertTrue(old_session.login(username='security-user', password=OLD_PASSWORD))
        issued = issue_password_reset_token(self.user)

        response = self.post('/api/auth/password/reset/', {
            'token': issued.raw_token,
            'password': NEW_PASSWORD,
            'password_confirm': NEW_PASSWORD,
        })

        self.assertEqual(response.status_code, 200)
        issued.record.refresh_from_db()
        self.assertIsNotNone(issued.record.used_at)
        self.assertIsNone(authenticate(username='security-user', password=OLD_PASSWORD))
        self.assertIsNotNone(authenticate(username='security-user', password=NEW_PASSWORD))
        self.assertIn(old_session.get('/api/auth/me/').status_code, {401, 403})
        notice.assert_called_once()

        repeated = self.post('/api/auth/password/reset/', {
            'token': issued.raw_token,
            'password': OLD_PASSWORD,
            'password_confirm': OLD_PASSWORD,
        })
        self.assertEqual(repeated.status_code, 400)
        self.assertEqual(repeated.json()['code'], 'invalid_token')

    def test_expired_password_reset_token_is_rejected(self):
        issued = issue_password_reset_token(self.user)
        AccountVerificationToken.objects.filter(pk=issued.record.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1),
        )

        response = self.post('/api/auth/password/reset/', {
            'token': issued.raw_token,
            'password': NEW_PASSWORD,
            'password_confirm': NEW_PASSWORD,
        })

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'expired_token')

    @patch('core.account.api.security_views.queue_password_changed_notice', return_value=True)
    def test_authenticated_password_change_keeps_current_session(self, notice):
        self.client.force_login(self.user)

        response = self.post('/api/auth/password/change/', {
            'current_password': OLD_PASSWORD,
            'new_password': NEW_PASSWORD,
            'new_password_confirm': NEW_PASSWORD,
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get('/api/auth/me/').status_code, 200)
        self.assertIsNotNone(authenticate(username='security-user', password=NEW_PASSWORD))
        notice.assert_called_once()

    @patch('core.account.api.security_views.queue_email_change_confirmation', return_value=True)
    def test_email_change_keeps_old_email_until_confirmation(self, queue):
        self.client.force_login(self.user)
        response = self.post('/api/auth/email/change/request/', {
            'current_password': OLD_PASSWORD,
            'new_email': 'New.Address@Example.COM',
        })

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.identity.refresh_from_db()
        self.assertEqual(self.user.email, 'security@example.com')
        self.assertEqual(self.identity.email, 'security@example.com')
        request = AccountEmailChangeRequest.objects.get(user=self.user)
        queue.assert_called_once()
        raw_token = queue.call_args.args[1]

        with patch('core.account.tasks.queue_email_changed_notice', return_value=True):
            confirmed = self.post('/api/auth/email/change/confirm/', {'token': raw_token})
        self.assertEqual(confirmed.status_code, 200)
        self.user.refresh_from_db()
        self.identity.refresh_from_db()
        request.refresh_from_db()
        self.assertEqual(self.user.email, 'new.address@example.com')
        self.assertEqual(self.identity.normalized_email, 'new.address@example.com')
        self.assertIsNotNone(self.identity.verified_at)
        self.assertIsNotNone(request.used_at)

    def test_email_change_requires_current_password_and_unique_email(self):
        other = User.objects.create_user(
            username='other-user', email='other@example.com', password=OLD_PASSWORD,
        )
        AccountEmail.objects.create(
            user=other,
            email='other@example.com',
            normalized_email='other@example.com',
            verified_at=timezone.now(),
        )
        self.client.force_login(self.user)

        wrong_password = self.post('/api/auth/email/change/request/', {
            'current_password': 'incorrect-password',
            'new_email': 'available@example.com',
        })
        conflict = self.post('/api/auth/email/change/request/', {
            'current_password': OLD_PASSWORD,
            'new_email': 'OTHER@EXAMPLE.COM',
        })

        self.assertEqual(wrong_password.status_code, 400)
        self.assertEqual(conflict.status_code, 400)
        self.assertEqual(conflict.json()['code'], 'email_conflict')

    def test_email_change_confirmation_is_single_use(self):
        issued = issue_email_change_token(self.user, 'new@example.com')

        first = self.post('/api/auth/email/change/confirm/', {'token': issued.raw_token})
        repeated = self.post('/api/auth/email/change/confirm/', {'token': issued.raw_token})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(repeated.status_code, 400)
        self.assertEqual(repeated.json()['code'], 'invalid_token')

    def test_password_reset_and_change_notification_emails(self):
        issued = issue_password_reset_token(self.user)
        result = send_password_reset_email.run(issued.record.pk, issued.raw_token)

        self.assertEqual(result['status'], 'sent')
        self.assertIn('/reset-password#token=', mail.outbox[0].body)
        self.assertIn(issued.raw_token, mail.outbox[0].body)

        notice = send_password_changed_notice.run(self.user.pk)
        self.assertEqual(notice['status'], 'sent')
        self.assertEqual(mail.outbox[1].to, ['security@example.com'])

    def test_email_change_confirmation_and_old_email_notice(self):
        issued = issue_email_change_token(self.user, 'next@example.com')
        result = send_email_change_confirmation.run(issued.record.pk, issued.raw_token)

        self.assertEqual(result['status'], 'sent')
        self.assertEqual(mail.outbox[0].to, ['next@example.com'])
        self.assertIn('/verify-email-change#token=', mail.outbox[0].body)

        notice = send_email_changed_notice.run(
            self.user.pk, 'security@example.com', 'next@example.com',
        )
        self.assertEqual(notice['status'], 'sent')
        self.assertEqual(mail.outbox[1].to, ['security@example.com'])
