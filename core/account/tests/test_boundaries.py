from pathlib import Path

from django.test import SimpleTestCase


class AccountModuleBoundaryTests(SimpleTestCase):
    def test_account_domain_has_expected_layers(self):
        account_root = Path(__file__).resolve().parents[1]
        expected = (
            'api/serializers.py',
            'api/views.py',
            'checks.py',
            'models/email.py',
            'selectors.py',
            'services/client_ip.py',
            'services/rate_limit.py',
            'services/registration.py',
        )
        for relative_path in expected:
            with self.subTest(path=relative_path):
                self.assertTrue((account_root / relative_path).is_file())
