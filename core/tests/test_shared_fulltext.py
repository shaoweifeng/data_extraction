"""Shared private PDF assets, compatibility, versioned binding and downloads."""
import tempfile
from pathlib import Path
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from core.fulltext.errors import FulltextError
from core.fulltext.models import FulltextAsset
from core.fulltext.processing import process_asset
from core.fulltext.services import create_assets, delete_asset, retry_asset
from core.models import Project, QAReference, QAFulltextAsset, Task
from core.quality.services.pdf_scanner import ScanResult
from core.rescreening.models import RescreenReference, RescreenCorpus
from core.rescreening.services.fulltext_binding import bind_fulltext
from core.services.project_service import initialize_project
from core.tests.test_qa_fulltext import make_pdf


class SharedFulltextFixture(TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.settings_override = override_settings(BASE_DIR=self.root, MEDIA_ROOT=self.root/'media',
            FULLTEXT_UPLOAD_ROOT=self.root/'shared', QA_FULLTEXT_UPLOAD_ROOT=self.root/'qa',
            RESCREEN_IMPORT_UPLOAD_ROOT=self.root/'imports', RESCREEN_EXPORT_UPLOAD_ROOT=self.root/'exports', FULLTEXT_LOOKUP_ENABLED=False,
            FULLTEXT_UNPAYWALL_EMAIL='', QA_FULLTEXT_REQUIRE_CLEAN_SCAN=False,
            QA_MALWARE_SCANNER_BACKEND='core.quality.services.pdf_scanner.DisabledScanner')
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.user = get_user_model().objects.create_user('shared-owner', password='pw')
        self.other = get_user_model().objects.create_user('shared-other', password='pw')
        self.project = Project.objects.create(name='Shared assets', owner=self.user)
        initialize_project(self.project, self.user)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def upload(self, content=None, *, name='study.pdf', references=False, schedule=False):
        return create_assets(project=self.project, user=self.user, create_references=references,
            schedule=schedule, files=[SimpleUploadedFile(name, content or make_pdf(), content_type='application/pdf')])

    def ready(self, content=None, *, name='study.pdf', references=False):
        assets, refs = self.upload(content, name=name, references=references)
        return process_asset(assets[0].pk), refs


class SharedFulltextTests(SharedFulltextFixture):
    def test_pdf_only_import_is_independent_and_preserves_filename_title(self):
        import fitz
        with fitz.open(stream=make_pdf(), filetype='pdf') as document:
            document.set_metadata({'title': 'CNKI', 'author': 'Microsoft Administrator'})
            body = document.tobytes()
        asset, refs = self.ready(body, name='Real research title.pdf', references=True)
        ref = RescreenReference.objects.active().get()
        self.assertEqual(ref.title, 'Real research title')
        self.assertEqual(ref.authors, [])
        self.assertEqual(ref.current_binding.asset_id, asset.pk)
        self.assertEqual(ref.raw_metadata_versions.get().source_format, 'pdf')
        self.assertEqual(QAReference.objects.count(), 0)
        self.assertEqual(RescreenCorpus.objects.get().revision, 1)
        with self.assertRaises(ValueError):
            _ = asset.raw_file.url

    def test_duplicate_pdf_reuses_asset_and_standalone_reference(self):
        body = make_pdf()
        first, refs = self.upload(body, references=True)
        second, second_refs = self.upload(body, name='renamed.pdf', references=True)
        self.assertEqual(first[0].pk, second[0].pk)
        self.assertEqual(refs[0].pk, second_refs[0].pk)
        self.assertEqual(FulltextAsset.objects.count(), 1)
        self.assertEqual(RescreenReference.objects.count(), 1)

    def test_extraction_is_identical_to_existing_qa_and_keeps_tail_pages(self):
        from django.core.files.base import ContentFile
        from core.quality.services.fulltext import process_fulltext_asset
        body = make_pdf(pages=25)
        shared, _ = self.ready(body)
        ref = QAReference.objects.create(project=self.project, title='Legacy QA')
        legacy = QAFulltextAsset(qa_reference=ref, project=self.project, original_filename='legacy.pdf',
            sha256='a'*64, size_bytes=len(body))
        legacy.raw_file.save('legacy.pdf', ContentFile(body), save=False)
        legacy.save()
        process_fulltext_asset(legacy.pk)
        legacy.refresh_from_db()
        self.assertEqual(shared.extracted_text_sha256, legacy.extracted_text_sha256)
        self.assertEqual(shared.chunk_index_sha256, legacy.chunk_index_sha256)
        self.assertEqual(shared.extracted_page_count, 25)
        with shared.extracted_text_file.open('rb') as handle:
            text = handle.read().decode()
        self.assertIn('PAGE-1-MARKER', text)
        self.assertIn('PAGE-25-MARKER', text)

    @override_settings(QA_PDF_TEXT_MAX_CHARS=100)
    def test_truncation_is_explicit_and_not_ai_ready(self):
        asset, _ = self.ready(make_pdf(pages=3))
        self.assertTrue(asset.extraction_truncated)
        data = self.client.get(f'/api/fulltext/assets/{asset.pk}/').json()['data']
        self.assertFalse(data['ai_ready'])
        self.assertLessEqual(asset.extracted_text_chars, 100)

    def test_corrupt_encrypted_and_page_limit_fail_closed(self):
        for body, code in ((b'%PDF-fake', 'pdf_corrupt'), (make_pdf(encrypted=True), 'pdf_encrypted')):
            with self.subTest(code=code):
                assets, _ = self.upload(body)
                with self.assertRaises(FulltextError):
                    process_asset(assets[0].pk)
                assets[0].refresh_from_db()
                self.assertEqual(assets[0].status, 'rejected')
                self.assertEqual(assets[0].error_code, code)
        with override_settings(QA_FULLTEXT_MAX_PAGES=1):
            assets, _ = self.upload(make_pdf(pages=2))
            with self.assertRaisesMessage(FulltextError, '页数限制'):
                process_asset(assets[0].pk)

    def test_scan_failure_and_required_clean_scan_do_not_publish_text(self):
        for scan, expected in ((ScanResult('infected'), 'rejected'), (ScanResult('failed'), 'failed')):
            assets, _ = self.upload(make_pdf(text=str(scan)))
            with patch('core.fulltext.processing.scan_pdf', return_value=scan):
                process_asset(assets[0].pk)
            assets[0].refresh_from_db()
            self.assertEqual(assets[0].status, expected)
            self.assertFalse(assets[0].extracted_text_file)
        assets, _ = self.upload()
        with override_settings(QA_FULLTEXT_REQUIRE_CLEAN_SCAN=True):
            process_asset(assets[0].pk)
        assets[0].refresh_from_db()
        self.assertEqual(assets[0].status, 'failed')

    def test_binding_is_versioned_and_rejects_stale_or_foreign_assets(self):
        first, refs = self.ready(references=True)
        second, _ = self.ready(make_pdf(text='Replacement PDF'))
        ref = bind_fulltext(reference=refs[0], asset=second, user=self.user, expected_version=1, expected_revision=1)
        self.assertEqual(ref.input_version, 2)
        self.assertEqual(ref.bindings.count(), 2)
        self.assertEqual(ref.raw_metadata_versions.count(), 2)
        with self.assertRaisesMessage(FulltextError, '已变化'):
            bind_fulltext(reference=ref, asset=first, user=self.user, expected_version=1)
        foreign_project = Project.objects.create(name='Other project', owner=self.user)
        FulltextAsset.objects.filter(pk=first.pk).update(project=foreign_project)
        with self.assertRaisesMessage(FulltextError, '其他项目'):
            bind_fulltext(reference=ref, asset=first, user=self.user, expected_version=2)

    def test_download_range_head_and_access_isolation(self):
        body = make_pdf()
        asset, _ = self.ready(body)
        url = f'/api/fulltext/assets/{asset.pk}/download/'
        response = self.client.get(url, HTTP_RANGE='bytes=0-7')
        self.assertEqual(response.status_code, 206)
        self.assertEqual(b''.join(response.streaming_content), body[:8])
        self.assertEqual(response['Content-Range'], f'bytes 0-7/{len(body)}')
        response = self.client.get(url, HTTP_RANGE='bytes=-10')
        self.assertEqual(b''.join(response.streaming_content), body[-10:])
        self.assertEqual(self.client.head(url).status_code, 200)
        self.assertEqual(self.client.get(url, HTTP_RANGE='bytes=0-1,4-5').status_code, 416)
        self.assertEqual(self.client.get(url, HTTP_RANGE=f'bytes={len(body)}-').status_code, 416)
        self.assertEqual(self.client.get(url, HTTP_RANGE='bytes='+('9'*5000)+'-').status_code, 416)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.get(f'/api/fulltext/assets/{asset.pk}/').status_code, 404)

    def test_shared_qa_adapter_reads_evidence_without_duplicating_pdf(self):
        from core.fulltext.access import asset_for_qa
        from core.quality.api.common import _serialize_ref
        from core.quality.services.evidence_retrieval import build_reference_evidence_packages
        asset, _ = self.ready()
        ref = QAReference.objects.create(project=self.project, title='Preserved bibliography',
            shared_fulltext_asset=asset, quality_method='QUADAS2', fulltext_status='available')
        self.assertEqual(asset_for_qa(ref).pk, asset.pk)
        self.assertEqual(_serialize_ref(ref)['fulltext_url'], f'/api/fulltext/assets/{asset.pk}/download/')
        self.assertTrue(build_reference_evidence_packages(ref))
        ref.refresh_from_db()
        self.assertEqual(ref.title, 'Preserved bibliography')
        self.assertEqual(QAFulltextAsset.objects.count(), 0)
        with self.assertRaisesMessage(FulltextError, '引用'):
            delete_asset(asset, self.user)

    def test_protected_history_and_project_cascade(self):
        asset, refs = self.ready(references=True)
        path = asset.raw_file.path
        bind_fulltext(reference=refs[0], asset=None, user=self.user, expected_version=1)
        with self.assertRaisesMessage(FulltextError, '引用'):
            delete_asset(asset, self.user)
        with self.captureOnCommitCallbacks(execute=True):
            self.project.delete()
        self.assertFalse(Path(path).exists())

    def test_storage_quota_failure_preserves_source_and_removes_new_outputs(self):
        from core.services.storage_quota_service import StorageQuotaExceeded, StorageQuotaSnapshot
        assets, _ = self.upload()
        with patch('core.fulltext.processing.user_storage_quota_guard', side_effect=StorageQuotaExceeded(StorageQuotaSnapshot(0, 0), 1)):
            with self.assertRaises(StorageQuotaExceeded):
                process_asset(assets[0].pk)
        assets[0].refresh_from_db()
        self.assertEqual(assets[0].status, 'failed')
        self.assertTrue(Path(assets[0].raw_file.path).exists())
        self.assertFalse(assets[0].extracted_text_file)

    def test_cancelled_processing_cannot_publish_or_overwrite_retry(self):
        assets, _ = self.upload(schedule=True)
        asset = assets[0]
        old_task = asset.processing_task_id
        with self.assertRaisesMessage(FulltextError, '停止'):
            process_asset(asset.pk, expected_task_id=old_task, check_stop=lambda: True)
        asset.refresh_from_db()
        self.assertEqual(asset.status, 'failed')
        retry_asset(asset, self.user)
        with self.assertRaisesMessage(FulltextError, '替代'):
            process_asset(asset.pk, expected_task_id=old_task)
        asset.refresh_from_db()
        self.assertEqual(asset.status, 'pending')

    def test_real_task_wrapper_finishes_without_model_calls(self):
        from core.executors.celery_tasks import execute_async_step
        assets, _ = self.upload(schedule=True)
        result = execute_async_step.apply(args=[assets[0].processing_task_id, 'rescreen_pdf', self.project.pk], throw=True)
        self.assertTrue(result.result)
        self.assertEqual(FulltextAsset.objects.get().status, 'ready')

    def test_pending_limit_and_file_size_boundaries(self):
        with override_settings(FULLTEXT_MAX_PENDING_PER_USER=1):
            self.upload()
            with self.assertRaisesMessage(FulltextError, '过多'):
                self.upload(make_pdf(text='Different PDF'))
        with override_settings(QA_FULLTEXT_MAX_FILE_BYTES=5):
            with self.assertRaisesMessage(FulltextError, '超过'):
                self.upload()
        with override_settings(FULLTEXT_MAX_ASSETS_PER_PROJECT=1):
            with self.assertRaisesMessage(FulltextError, '数量已达上限'):
                self.upload(make_pdf(text='Small-file limit'))
        with override_settings(FULLTEXT_UPLOAD_RATE_PER_MINUTE=1):
            with self.assertRaisesMessage(FulltextError, '过于频繁'):
                self.upload(make_pdf(text='Rate limit'))

    def test_unused_asset_rebuild_is_deterministic_and_bound_asset_is_protected(self):
        from core.fulltext.services import rebuild_asset
        asset, _ = self.ready()
        original_hash = asset.chunk_index_sha256
        rebuild_asset(asset, self.user, schedule=False)
        asset = process_asset(asset.pk)
        self.assertEqual(asset.chunk_index_sha256, original_hash)
        bound, _ = self.ready(make_pdf(text='Bound input'), references=True)
        with self.assertRaisesMessage(FulltextError, '被引用'):
            rebuild_asset(bound, self.user, schedule=False)

    def test_interrupted_worker_recovery_and_reference_safe_retention(self):
        from datetime import timedelta
        from django.utils import timezone
        from core.fulltext.cleanup import cleanup_fulltext
        assets, _ = self.upload(schedule=True)
        FulltextAsset.objects.filter(pk=assets[0].pk).update(status='extracting', updated_at=timezone.now()-timedelta(hours=2))
        result = cleanup_fulltext()
        self.assertEqual(result['recovered_assets'], 1)
        self.assertEqual(Task.objects.get(pk=assets[0].processing_task_id).status, 'failed')
        referenced, _ = self.upload(make_pdf(text='Retained failed source'), references=True)
        FulltextAsset.objects.filter(pk__in=[assets[0].pk, referenced[0].pk]).update(
            status='failed', updated_at=timezone.now()-timedelta(days=30))
        with self.captureOnCommitCallbacks(execute=True):
            result = cleanup_fulltext()
        self.assertEqual(result['deleted_assets'], 1)
        self.assertTrue(FulltextAsset.objects.filter(pk=referenced[0].pk).exists())

    def test_cli_shared_inspection_and_rebuild_keep_legacy_namespace_separate(self):
        from django.core.management import call_command
        asset, _ = self.ready()
        call_command('inspect_qa_fulltext', asset_id=asset.pk, asset_kind='shared', output=str(self.root/'report'))
        self.assertTrue((self.root/'report'/f'shared-fulltext-asset-{asset.pk}.md').exists())
        call_command('rebuild_qa_fulltext', asset_id=asset.pk, asset_kind='shared', limit=1)
        asset.refresh_from_db()
        self.assertEqual(asset.status, 'ready')

    def test_upload_api_dispatch_has_hard_timeout_and_no_public_storage_path(self):
        from types import SimpleNamespace
        with patch('core.executors.celery_tasks.execute_async_step.apply_async',
                return_value=SimpleNamespace(id='pdf-worker')) as dispatch, self.captureOnCommitCallbacks(execute=True):
            response = self.client.post('/api/fulltext/assets/upload/',
                {'project_id': self.project.pk, 'files': [SimpleUploadedFile('api.pdf', make_pdf(), content_type='application/pdf')],
                 'create_references': 'true'}, format='multipart')
        self.assertEqual(response.status_code, 202, response.content)
        self.assertEqual(dispatch.call_args.kwargs['time_limit'], 150)
        self.assertNotIn('raw_file', str(response.json()))
        self.assertEqual(len(response.json()['data']['references']), 1)

    def test_source_integrity_check_rejects_disk_tampering(self):
        assets, _ = self.upload()
        # Simulates damaged storage using the storage API rather than replacing repository files.
        with assets[0].raw_file.storage.open(assets[0].raw_file.name, 'wb') as handle:
            handle.write(b'%PDF-damaged')
        with self.assertRaisesMessage(FulltextError, '校验失败'):
            process_asset(assets[0].pk)

    def test_image_only_pdf_is_readable_but_not_ai_ready(self):
        import fitz
        with fitz.open() as document:
            document.new_page()
            body = document.tobytes()
        asset, _ = self.ready(body)
        self.assertEqual(asset.status, 'ready')
        self.assertEqual(asset.extraction_status, 'skipped')
        self.assertEqual(asset.chunk_count, 0)
        self.assertFalse(self.client.get(f'/api/fulltext/assets/{asset.pk}/').json()['data']['ai_ready'])

    def test_real_pdf_samples_match_shared_kernel_when_available(self):
        import fitz
        from core.fulltext.extraction import extract_page_text
        from core.quality.services.evidence_retrieval import load_verified_chunks
        root = Path(__file__).resolve().parents[2]/'meta_project'/'QA_input'
        samples = sorted(root.glob('*.pdf'))[:3]
        if not samples:
            self.skipTest('本地 PDF 样本不随 Git 提交。')
        for path in samples:
            with self.subTest(pdf=path.name):
                asset, _ = self.ready(path.read_bytes(), name=path.name)
                with fitz.open(path) as document:
                    expected = extract_page_text(document, max_chars=200000)
                with asset.extracted_text_file.open('rb') as handle:
                    self.assertEqual(handle.read().decode(), expected['text'])
                chunks = load_verified_chunks(asset)
                self.assertTrue(chunks)
                self.assertEqual(chunks[-1]['page_end'], expected['pages'][-1].page_number)
                print(f'共享全文离线样本: {path.name} → {asset.page_count} 页 / {asset.chunk_count} 块')
