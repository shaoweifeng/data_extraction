import io
import os
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from PIL import Image

from .models import ExternalImageUpload


API_KEY = 'external-image-test-key-32-characters-long'


def image_upload(name='../../unsafe name.png', image_format='PNG'):
    output = io.BytesIO()
    Image.new('RGB', (32, 18), color=(10, 120, 200)).save(output, format=image_format)
    mime = 'image/jpeg' if image_format == 'JPEG' else f'image/{image_format.lower()}'
    return SimpleUploadedFile(name, output.getvalue(), content_type=mime)


class ExternalImageUploadApiTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temp_dir = TemporaryDirectory(prefix='external-image-tests-')
        cls._settings = override_settings(
            EXTERNAL_IMAGE_UPLOAD_ENABLED=True,
            EXTERNAL_IMAGE_UPLOAD_API_KEY=API_KEY,
            EXTERNAL_IMAGE_UPLOAD_ROOT=cls._temp_dir.name,
        )
        cls._settings.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        try:
            super().tearDownClass()
        finally:
            cls._settings.disable()
            cls._temp_dir.cleanup()

    def upload(self, *, request_id=None, image=None, api_key=API_KEY, source='private-tool'):
        return self.client.post(
            '/api/external/images/',
            {'image': image or image_upload(), 'source': source},
            HTTP_AUTHORIZATION=f'Bearer {api_key}',
            HTTP_IDEMPOTENCY_KEY=str(request_id or uuid.uuid4()),
        )

    def test_upload_is_private_reencoded_and_persisted(self):
        response = self.upload()

        self.assertEqual(response.status_code, 201, response.content)
        upload = ExternalImageUpload.objects.get()
        self.assertEqual(upload.width, 32)
        self.assertEqual(upload.height, 18)
        self.assertEqual(upload.source, 'private-tool')
        self.assertNotIn('unsafe', upload.file.name)
        self.assertRegex(upload.file.name, r'^\d{4}/\d{2}/\d{2}/[0-9a-f]{32}\.png$')
        self.assertEqual(response.json()['path'], upload.file.path)
        self.assertEqual(response.json()['relative_path'], upload.file.name)
        self.assertTrue(upload.file.storage.exists(upload.file.name))
        with self.assertRaises(ValueError):
            upload.file.storage.url(upload.file.name)

    def test_idempotent_retry_returns_existing_record(self):
        request_id = uuid.uuid4()
        first = self.upload(request_id=request_id)
        second = self.upload(request_id=request_id, image=image_upload('different.png'))

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()['id'], second.json()['id'])
        self.assertEqual(first.json()['path'], second.json()['path'])
        self.assertEqual(first.json()['relative_path'], second.json()['relative_path'])
        self.assertEqual(ExternalImageUpload.objects.count(), 1)

    def test_api_key_and_idempotency_key_are_required(self):
        self.assertEqual(self.upload(api_key='wrong-key').status_code, 401)
        response = self.client.post(
            '/api/external/images/',
            {'image': image_upload()},
            HTTP_AUTHORIZATION=f'Bearer {API_KEY}',
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'INVALID_IDEMPOTENCY_KEY')

    def test_invalid_image_and_oversized_request_are_rejected(self):
        fake = SimpleUploadedFile('fake.png', b'<script>x</script>', content_type='image/png')
        response = self.upload(image=fake)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(ExternalImageUpload.objects.count(), 0)

        with override_settings(EXTERNAL_IMAGE_UPLOAD_MAX_REQUEST_BYTES=10):
            response = self.upload()
        self.assertEqual(response.status_code, 413)

    def test_disabled_endpoint_rejects_upload(self):
        with override_settings(EXTERNAL_IMAGE_UPLOAD_ENABLED=False):
            response = self.upload()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(ExternalImageUpload.objects.count(), 0)

    def test_deleting_record_deletes_file(self):
        self.upload()
        upload = ExternalImageUpload.objects.get()
        storage, name = upload.file.storage, upload.file.name
        upload.delete()
        self.assertFalse(storage.exists(name))

    def test_orphan_cleanup_is_preview_first(self):
        orphan = Path(self._temp_dir.name) / '2020' / '01' / '01' / 'orphan.png'
        orphan.parent.mkdir(parents=True, exist_ok=True)
        orphan.write_bytes(b'orphan')
        os.utime(orphan, (1_600_000_000, 1_600_000_000))

        call_command('cleanup_external_image_orphans', older_than_hours=1)
        self.assertTrue(orphan.exists())
        call_command('cleanup_external_image_orphans', apply=True, older_than_hours=1)
        self.assertFalse(orphan.exists())
