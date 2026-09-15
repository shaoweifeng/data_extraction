from pathlib import Path

from django.core import checks
from django.test import SimpleTestCase
from django.test import override_settings


class AccountModuleBoundaryTests(SimpleTestCase):
    def test_account_domain_has_expected_layers(self):
        account_root = Path(__file__).resolve().parents[1]
        expected = (
            'api/serializers.py',
            'api/views.py',
            'api/verification_views.py',
            'api/responses.py',
            'checks.py',
            'models/email.py',
            'models/verification.py',
            'selectors.py',
            'tasks.py',
            'services/client_ip.py',
            'services/rate_limit.py',
            'services/registration.py',
            'services/verification.py',
        )
        for relative_path in expected:
            with self.subTest(path=relative_path):
                self.assertTrue((account_root / relative_path).is_file())

    @override_settings(
        ACCOUNT_REGISTRATION_V2_ENABLED=False,
        REQUIRE_EMAIL_VERIFICATION=True,
    )
    def test_email_verification_requires_v2_registration(self):
        message_ids = {message.id for message in checks.run_checks(tags=[checks.Tags.security])}
        self.assertIn('account.E007', message_ids)

    @override_settings(
        APP_ENV='production',
        ACCOUNT_REGISTRATION_V2_ENABLED=True,
        REQUIRE_EMAIL_VERIFICATION=True,
        EMAIL_BACKEND='django.core.mail.backends.console.EmailBackend',
    )
    def test_production_verification_rejects_console_email_backend(self):
        message_ids = {message.id for message in checks.run_checks(tags=[checks.Tags.security])}
        self.assertIn('account.E008', message_ids)
