import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import fitz
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings

from core.models import Project, QAFulltextAsset, QAReference
from core.quality.services.fulltext import process_fulltext_asset


User = get_user_model()


def make_pdf(*, pages=1, text='A sufficiently long body of research text. ' * 10, encrypted=False):
    document = fitz.open()
    for index in range(pages):
        page = document.new_page()
        page.insert_text((72, 72), f'PAGE-{index + 1}-MARKER {text}')
    options = {}
    if encrypted:
        options.update(
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw='owner-secret',
            user_pw='user-secret',
        )
    content = document.tobytes(**options)
    document.close()
    return content


class QAFulltextTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings = override_settings(
            QA_FULLTEXT_UPLOAD_ROOT=self.temp_dir.name,
            QA_FULLTEXT_MAX_FILES_PER_REQUEST=2,
            QA_FULLTEXT_MAX_FILE_BYTES=2 * 1024 * 1024,
            QA_FULLTEXT_MAX_TOTAL_BYTES=3 * 1024 * 1024,
            QA_FULLTEXT_MAX_PAGES=2,
            QA_PDF_TEXT_MAX_CHARS=2000,
            QA_AI_MAX_CONTENT_CHARS=1000,
            QA_CHUNK_TARGET_TOKENS=100,
            QA_CHUNK_OVERLAP_TOKENS=10,
            QA_FULLTEXT_REQUIRE_CLEAN_SCAN=False,
        )
        self.settings.enable()
        self.user = User.objects.create_user('qa-owner', password='pw')
        self.outsider = User.objects.create_user('qa-outsider', password='pw')
        self.project = Project.objects.create(name='QA fulltext', owner=self.user)
        self.client = Client()
        self.client.force_login(self.user)

    def tearDown(self):
        self.settings.disable()
        self.temp_dir.cleanup()

    def upload(self, content=None, *, name='study.pdf', content_type='application/pdf'):
        file = SimpleUploadedFile(name, content or make_pdf(), content_type=content_type)
        with patch('core.quality.tasks.parse_qa_pdf_meta.delay') as delay:
            response = self.client.post(
                '/api/qa/refs/upload/',
                {'project_id': str(self.project.id), 'files': [file]},
            )
        return response, delay

    def test_upload_is_private_pending_hashed_and_dispatched(self):
        response, delay = self.upload()

        self.assertEqual(response.status_code, 201)
        ref = QAReference.objects.get(project=self.project)
        asset = ref.fulltext_asset
        self.assertEqual(ref.fulltext_status, 'pending')
        self.assertEqual(asset.status, 'pending')
        self.assertEqual(len(asset.sha256), 64)
        self.assertNotIn('study.pdf', asset.raw_file.name)
        with self.assertRaises(ValueError):
            asset.raw_file.storage.url(asset.raw_file.name)
        delay.assert_called_once_with(ref.id)

    def test_rejects_spoofed_pdf_and_wrong_mime(self):
        response, _ = self.upload(b'not a pdf')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error']['code'], 'invalid_pdf_signature')

        response, _ = self.upload(content_type='text/plain')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error']['code'], 'invalid_mime_type')
        self.assertFalse(QAFulltextAsset.objects.exists())

    def test_duplicate_pdf_is_isolated_per_project(self):
        content = make_pdf()
        response, _ = self.upload(content)
        self.assertEqual(response.status_code, 201)
        response, _ = self.upload(content, name='copy.pdf')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error']['code'], 'duplicate_fulltext')

        other = Project.objects.create(name='Other', owner=self.user)
        file = SimpleUploadedFile('copy.pdf', content, content_type='application/pdf')
        with patch('core.quality.tasks.parse_qa_pdf_meta.delay'):
            response = self.client.post(
                '/api/qa/refs/upload/', {'project_id': str(other.id), 'files': [file]},
            )
        self.assertEqual(response.status_code, 201)

    def test_processing_extracts_text_and_download_is_authorized(self):
        response, _ = self.upload()
        asset_id = response.json()['data']['refs'][0]['fulltext_asset']['id']
        process_fulltext_asset(asset_id)

        asset = QAFulltextAsset.objects.get(pk=asset_id)
        asset.qa_reference.refresh_from_db()
        self.assertEqual(asset.status, 'ready')
        self.assertEqual(asset.scan_status, 'not_configured')
        self.assertEqual(asset.extraction_status, 'completed')
        self.assertEqual(asset.page_count, 1)
        self.assertEqual(asset.qa_reference.fulltext_status, 'available')
        self.assertTrue(asset.extracted_text_file.name)
        self.assertTrue(asset.chunk_index_file.name)
        self.assertEqual(asset.extracted_page_count, 1)
        self.assertFalse(asset.extraction_truncated)
        self.assertGreater(asset.chunk_count, 0)

        download = self.client.get(f'/api/qa/fulltext-assets/{asset.id}/download/')
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download['Content-Type'], 'application/pdf')
        self.client.force_login(self.outsider)
        self.assertEqual(
            self.client.get(f'/api/qa/fulltext-assets/{asset.id}/download/').status_code,
            404,
        )

    def test_encrypted_and_excessive_page_pdfs_are_rejected(self):
        response, _ = self.upload(make_pdf(encrypted=True), name='encrypted.pdf')
        encrypted = QAFulltextAsset.objects.get(
            pk=response.json()['data']['refs'][0]['fulltext_asset']['id']
        )
        process_fulltext_asset(encrypted.id)
        encrypted.refresh_from_db()
        self.assertEqual((encrypted.status, encrypted.error_code), ('rejected', 'pdf_encrypted'))

        response, _ = self.upload(make_pdf(pages=3), name='long.pdf')
        long_pdf = QAFulltextAsset.objects.get(
            pk=response.json()['data']['refs'][0]['fulltext_asset']['id']
        )
        process_fulltext_asset(long_pdf.id)
        long_pdf.refresh_from_db()
        self.assertEqual((long_pdf.status, long_pdf.error_code), ('rejected', 'too_many_pages'))
        self.assertEqual(long_pdf.page_count, 3)

    def test_asset_deletion_removes_private_files(self):
        response, _ = self.upload()
        asset = QAFulltextAsset.objects.get(
            pk=response.json()['data']['refs'][0]['fulltext_asset']['id']
        )
        process_fulltext_asset(asset.id)
        asset.refresh_from_db()
        storage = asset.raw_file.storage
        name = asset.raw_file.name
        text_name = asset.extracted_text_file.name
        chunk_name = asset.chunk_index_file.name
        self.assertTrue(storage.exists(name))
        asset.delete()
        self.assertFalse(storage.exists(name))
        self.assertFalse(storage.exists(text_name))
        self.assertFalse(storage.exists(chunk_name))

    @override_settings(QA_FULLTEXT_MAX_PAGES=30, QA_PDF_TEXT_MAX_CHARS=100000)
    def test_processing_extracts_beyond_twenty_pages_and_chunks_are_stable(self):
        response, _ = self.upload(make_pdf(pages=25), name='long-study.pdf')
        asset_id = response.json()['data']['refs'][0]['fulltext_asset']['id']
        process_fulltext_asset(asset_id)

        asset = QAFulltextAsset.objects.get(pk=asset_id)
        self.assertEqual(asset.page_count, 25)
        self.assertEqual(asset.extracted_page_count, 25)
        self.assertFalse(asset.extraction_truncated)
        self.assertGreater(asset.chunk_count, 0)
        asset.extracted_text_file.open('rb')
        try:
            extracted = asset.extracted_text_file.read().decode('utf-8')
        finally:
            asset.extracted_text_file.close()
        self.assertIn('<<<QA_PAGE:21>>>', extracted)
        self.assertIn('PAGE-25-MARKER', extracted)

        first_text_hash = asset.extracted_text_sha256
        first_chunk_hash = asset.chunk_index_sha256
        process_fulltext_asset(asset_id, force=True)
        asset.refresh_from_db()
        self.assertEqual(asset.extracted_text_sha256, first_text_hash)
        self.assertEqual(asset.chunk_index_sha256, first_chunk_hash)

    @override_settings(QA_FULLTEXT_MAX_PAGES=10, QA_PDF_TEXT_MAX_CHARS=180)
    def test_processing_records_character_truncation(self):
        response, _ = self.upload(make_pdf(pages=3, text='truncation body ' * 40), name='truncated.pdf')
        asset_id = response.json()['data']['refs'][0]['fulltext_asset']['id']
        process_fulltext_asset(asset_id)

        asset = QAFulltextAsset.objects.get(pk=asset_id)
        self.assertTrue(asset.extraction_truncated)
        self.assertIsNotNone(asset.truncated_at_page)
        self.assertLessEqual(asset.extracted_text_chars, 180)

    def test_inspection_command_writes_bounded_report(self):
        response, _ = self.upload(make_pdf(text='inspection-needle research body'))
        asset_id = response.json()['data']['refs'][0]['fulltext_asset']['id']
        process_fulltext_asset(asset_id)

        with tempfile.TemporaryDirectory() as output_dir:
            call_command(
                'inspect_qa_fulltext',
                asset_id=asset_id,
                output=output_dir,
                find=['inspection-needle'],
            )
            markdown = Path(output_dir, f'qa-fulltext-asset-{asset_id}.md').read_text('utf-8')
            payload = Path(output_dir, f'qa-fulltext-asset-{asset_id}.json').read_text('utf-8')
        self.assertIn('inspection-needle', markdown)
        self.assertIn('"chunk_count"', payload)

    def test_evidence_inspection_command_is_read_only_and_bounded(self):
        response, _ = self.upload(make_pdf(
            text='Methods Consecutive patients were enrolled using random sampling. ' * 8,
        ))
        asset_id = response.json()['data']['refs'][0]['fulltext_asset']['id']
        asset = QAFulltextAsset.objects.get(pk=asset_id)
        QAReference.objects.filter(pk=asset.qa_reference_id).update(quality_method='QUADAS2')
        process_fulltext_asset(asset_id)

        with tempfile.TemporaryDirectory() as output_dir:
            call_command(
                'inspect_qa_evidence',
                reference_id=asset.qa_reference_id,
                output=output_dir,
                signal_key=['ps_consecutive'],
            )
            markdown = Path(
                output_dir, f'qa-evidence-reference-{asset.qa_reference_id}.md'
            ).read_text('utf-8')
            payload = Path(
                output_dir, f'qa-evidence-reference-{asset.qa_reference_id}.json'
            ).read_text('utf-8')
        self.assertIn('ps_consecutive', markdown)
        self.assertIn('Consecutive patients', markdown)
        self.assertNotIn('"text":', payload)
        self.assertIn('"preview":', payload)

    def test_rebuild_command_supports_dry_run_and_bounded_asset_scope(self):
        response, _ = self.upload()
        asset_id = response.json()['data']['refs'][0]['fulltext_asset']['id']
        call_command('rebuild_qa_fulltext', asset_id=asset_id, limit=1, dry_run=True)
        asset = QAFulltextAsset.objects.get(pk=asset_id)
        self.assertEqual(asset.status, 'pending')

        call_command('rebuild_qa_fulltext', asset_id=asset_id, limit=1, dry_run=False)
        asset.refresh_from_db()
        self.assertEqual(asset.status, 'ready')
        self.assertGreater(asset.chunk_count, 0)

        with tempfile.TemporaryDirectory() as output_dir:
            report = Path(output_dir, 'rebuild.json')
            call_command(
                'rebuild_qa_fulltext', asset_id=asset_id, limit=1,
                resume=True, report=str(report),
            )
            self.assertFalse(report.exists())

            retry = Path(output_dir, 'previous.json')
            retry.write_text(json.dumps({
                'failed': [{'asset_id': asset_id, 'error': 'previous'}],
            }), encoding='utf-8')
            call_command(
                'rebuild_qa_fulltext', retry_report=str(retry), limit=1,
                dry_run=True,
            )

    def test_failed_force_rebuild_preserves_previous_derived_files(self):
        response, _ = self.upload()
        asset_id = response.json()['data']['refs'][0]['fulltext_asset']['id']
        process_fulltext_asset(asset_id)
        asset = QAFulltextAsset.objects.get(pk=asset_id)
        text_name = asset.extracted_text_file.name
        chunk_name = asset.chunk_index_file.name
        text_hash = asset.extracted_text_sha256
        chunk_hash = asset.chunk_index_sha256

        with patch(
            'core.quality.services.fulltext.build_chunks',
            side_effect=RuntimeError('chunking failed'),
        ):
            with self.assertRaises(RuntimeError):
                process_fulltext_asset(asset_id, force=True)

        asset.refresh_from_db()
        self.assertEqual(asset.status, 'ready')
        self.assertEqual(asset.error_code, 'pdf_rebuild_failed')
        self.assertEqual(asset.extracted_text_file.name, text_name)
        self.assertEqual(asset.chunk_index_file.name, chunk_name)
        self.assertEqual(asset.extracted_text_sha256, text_hash)
        self.assertEqual(asset.chunk_index_sha256, chunk_hash)
        self.assertTrue(asset.extracted_text_file.storage.exists(text_name))
        self.assertTrue(asset.chunk_index_file.storage.exists(chunk_name))


class QAStorageMaterializationTests(TestCase):
    def test_remote_storage_without_path_is_materialized_and_cleaned(self):
        from django.core.files.base import ContentFile
        from django.core.files.storage import InMemoryStorage
        from django.db.models.fields.files import FieldFile
        from core.quality.storage import materialized_storage_path

        storage = InMemoryStorage()
        name = storage.save('remote/document.pdf', ContentFile(b'%PDF-test'))
        field = type('StorageField', (), {'storage': storage})()
        field_file = FieldFile(None, field, name)
        with materialized_storage_path(field_file, suffix='.pdf') as local_path:
            self.assertEqual(Path(local_path).read_bytes(), b'%PDF-test')
            materialized = local_path
        self.assertFalse(Path(materialized).exists())
