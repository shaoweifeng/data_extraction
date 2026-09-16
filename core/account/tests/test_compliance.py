import json
from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from ..models import AccountAdminAuditEvent, AccountSecurityEvent, AgreementAcceptance
from ..services.legal import get_current_legal_document

User = get_user_model()


class ComplianceTests(TestCase):
    def test_failed_login_records_only_fingerprints(self):
        response = self.client.post(
            '/api/auth/login/',
            {'username': 'private@example.com', 'password': 'wrong'},
            content_type='application/json',
            HTTP_X_FORWARDED_FOR='203.0.113.42',
            HTTP_USER_AGENT='Private Browser',
        )
        self.assertEqual(response.status_code, 401)
        event = AccountSecurityEvent.objects.get(event_type='login')
        self.assertEqual(event.outcome, 'failure')
        self.assertEqual(event.ip_masked, '203.0.113.0/24')
        serialized = json.dumps({
            'identifier_hash': event.identifier_hash,
            'ip_hash': event.ip_hash,
            'user_agent_hash': event.user_agent_hash,
        })
        self.assertNotIn('private@example.com', serialized)
        self.assertNotIn('Private Browser', serialized)

    def test_security_event_cleanup_is_preview_first(self):
        event = AccountSecurityEvent.objects.create(event_type='login', outcome='failure')
        AccountSecurityEvent.objects.filter(pk=event.pk).update(
            created_at=timezone.now() - timedelta(days=181),
        )
        output = StringIO()
        call_command('cleanup_account_security_events', stdout=output)
        self.assertTrue(AccountSecurityEvent.objects.filter(pk=event.pk).exists())
        call_command('cleanup_account_security_events', '--delete', stdout=output)
        self.assertFalse(AccountSecurityEvent.objects.filter(pk=event.pk).exists())


class AccountAdminAuditTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('phase4-admin', password='pw')
        self.target = User.objects.create_user('phase4-target', password='pw')
        self.client.force_login(self.admin)

    def test_ban_action_requires_confirmation_and_reason(self):
        url = '/admin/auth/user/'
        selection = {'action': 'ban_accounts', '_selected_action': [str(self.target.pk)]}
        confirmation = self.client.post(url, selection)
        self.assertEqual(confirmation.status_code, 200)
        self.target.profile.refresh_from_db()
        self.assertFalse(self.target.profile.is_banned)

        missing_reason = self.client.post(url, {**selection, 'confirmed': 'yes', 'reason': ''})
        self.assertEqual(missing_reason.status_code, 302)
        self.assertFalse(AccountAdminAuditEvent.objects.exists())

        response = self.client.post(
            url, {**selection, 'confirmed': 'yes', 'reason': '异常登录调查'},
        )
        self.assertEqual(response.status_code, 302)
        self.target.profile.refresh_from_db()
        self.assertTrue(self.target.profile.is_banned)
        audit = AccountAdminAuditEvent.objects.get(action='account_ban')
        self.assertEqual(audit.actor, self.admin)
        self.assertEqual(audit.reason, '异常登录调查')

    def test_user_delete_cascades_acceptance_and_preserves_audit_snapshot(self):
        document = get_current_legal_document('terms')
        AgreementAcceptance.objects.create(
            user=self.target,
            document_type='terms',
            version=document.version,
            content_sha256=document.content_sha256,
        )
        url = '/admin/auth/user/'
        selection = {
            'action': 'delete_selected',
            '_selected_action': [str(self.target.pk)],
        }
        confirmation = self.client.post(url, selection)
        self.assertEqual(confirmation.status_code, 200)
        self.assertEqual(confirmation.context['perms_lacking'], set())
        response = self.client.post(url, {**selection, 'post': 'yes'})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(User.objects.filter(pk=self.target.pk).exists())
        audit = AccountAdminAuditEvent.objects.get(action='user_delete')
        self.assertIsNone(audit.target_user)
        self.assertEqual(audit.target_username_snapshot, 'phase4-target')
