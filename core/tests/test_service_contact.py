import io
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from PIL import Image

from core.admin import ServiceContactSettingAdminForm
from core.models import ServiceContactSetting
from core.service_contact.storage import service_contact_storage


User = get_user_model()


def _image_bytes(image_format='PNG'):
    output = io.BytesIO()
    Image.new('RGB', (16, 16), 'white').save(output, format=image_format)
    return output.getvalue()


@override_settings(SERVICE_CONTACT_ENABLED=True)
class ServiceContactApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('contact-user', password='pw')
        self.client = Client()

    def test_contact_requires_authentication(self):
        response = self.client.get('/api/billing/service-contact/')
        self.assertIn(response.status_code, {401, 403})

    def test_disabled_contact_does_not_leak_fields(self):
        ServiceContactSetting.objects.create(
            enabled=False,
            wechat_id='should-not-leak',
            contact_email='private@example.com',
        )
        self.client.force_login(self.user)

        response = self.client.get('/api/billing/service-contact/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'enabled': False})

    def test_missing_contact_uses_safe_default_information(self):
        self.client.force_login(self.user)

        response = self.client.get('/api/billing/service-contact/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['enabled'])
        self.assertFalse(payload['configured'])
        self.assertEqual(payload['display_name'], 'MetaFlow 服务助手')
        self.assertIn('申请使用', payload['description'])
        self.assertFalse(payload['qr_available'])

    @override_settings(SERVICE_CONTACT_ENABLED=False)
    def test_global_feature_switch_overrides_database(self):
        ServiceContactSetting.objects.create(enabled=True, wechat_id='metaflow')
        self.client.force_login(self.user)

        response = self.client.get('/api/billing/service-contact/')

        self.assertEqual(response.json(), {'enabled': False})

    def test_enabled_contact_returns_public_contact_fields_only(self):
        ServiceContactSetting.objects.create(
            enabled=True,
            display_name='MetaFlow 服务助手',
            wechat_id='metaflow-test',
            contact_email='service@example.com',
            service_hours='工作日 09:00-18:00',
        )
        self.client.force_login(self.user)

        response = self.client.get('/api/billing/service-contact/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['enabled'])
        self.assertTrue(payload['configured'])
        self.assertEqual(payload['wechat_id'], 'metaflow-test')
        self.assertFalse(payload['qr_available'])
        self.assertNotIn('updated_by', payload)

    def test_qr_is_served_only_to_authenticated_users(self):
        with tempfile.TemporaryDirectory() as directory:
            old_location = service_contact_storage.location
            service_contact_storage._location = directory
            try:
                setting = ServiceContactSetting.objects.create(enabled=True, wechat_id='metaflow')
                setting.wechat_qr.save('contact.png', ContentFile(_image_bytes(), name='contact.png'))

                anonymous = self.client.get('/api/billing/service-contact/qr/')
                self.assertIn(anonymous.status_code, {401, 403})

                self.client.force_login(self.user)
                response = self.client.get('/api/billing/service-contact/qr/')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
                self.assertTrue(response['Cache-Control'].startswith('private'))
            finally:
                service_contact_storage._location = old_location


class ServiceContactAdminFormTests(TestCase):
    def test_rejects_non_image_qr_upload(self):
        form = ServiceContactSettingAdminForm(
            data={'enabled': False, 'display_name': 'MetaFlow 服务助手'},
            files={'wechat_qr': SimpleUploadedFile('fake.png', b'not-an-image', 'image/png')},
        )

        self.assertFalse(form.is_valid())
        self.assertIn('wechat_qr', form.errors)

    def test_accepts_and_reencodes_png_qr_upload(self):
        form = ServiceContactSettingAdminForm(
            data={'enabled': False, 'display_name': 'MetaFlow 服务助手'},
            files={'wechat_qr': SimpleUploadedFile('qr.png', _image_bytes(), 'image/png')},
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['wechat_qr'].name, 'upload.png')
