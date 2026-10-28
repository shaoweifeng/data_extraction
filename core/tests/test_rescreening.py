"""Stages 0–2: private imports, atomic publication, metadata and access isolation."""
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.bibliography import BIBLIOGRAPHY_FIELDS, bibliography_fields, bibliography_snapshot, parser_record
from core.fulltext.models import FulltextAsset
from core.models import Project, Task
from core.rescreening.errors import RescreenError
from core.rescreening.models import RescreenCorpus, RescreenImportBatch, RescreenReference, RescreenReferenceRawMetadata
from core.rescreening.services.imports import start_import, retry_import, remove_references
from core.rescreening.services.processing import process_import
from core.screening.services.import_errors import ScreeningImportError
from core.screening.services.import_limits import ImportLimits
from core.services.project_service import initialize_project
from core.services.storage_quota_service import user_storage_usage_bytes
from core.tests.test_screening_imports import ris_file, two_record_ris, bibtex_with_recoverable_invalid_key


class RescreeningTests(TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.override = override_settings(BASE_DIR=self.root, MEDIA_ROOT=self.root / 'media',
            RESCREEN_IMPORT_UPLOAD_ROOT=self.root / 'imports', FULLTEXT_UPLOAD_ROOT=self.root / 'assets')
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.user = get_user_model().objects.create_user('rescreen-user', password='pw')
        self.other = get_user_model().objects.create_user('rescreen-other', password='pw')
        self.project = Project.objects.create(name='Standalone', owner=self.user)
        initialize_project(self.project, self.user)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def start(self, files=None, key='key', preview=None):
        return start_import(project=self.project, user=self.user, idempotency_key=key,
                            uploads=files, preview=preview)

    def completed(self, files=None, key='key'):
        batch = self.start(files or [ris_file()], key=key)
        return process_import(batch.pk)

    def finish_task(self, batch):
        Task.objects.filter(pk=batch.task_id).update(status='completed')

    def test_shared_mapping_round_trip_all_fields(self):
        record = dict(title='完整题名', abstract='摘要', authors=['甲', '乙'], keywords=['词'],
            year='2026', date='2026-10', reference_type='Journal Article', page='1-8',
            source_identifier='original-id')
        for field in BIBLIOGRAPHY_FIELDS:
            if field not in record and field not in ('publication_year', 'publication_date', 'publication_type', 'pages'):
                record[field] = field + '-value'
        fields = bibliography_fields(record)
        self.assertEqual(bibliography_fields(parser_record(fields)), fields)
        self.assertEqual(set(fields), set(BIBLIOGRAPHY_FIELDS))

    def test_upload_private_then_publish_and_raw_retained(self):
        batch = self.start([ris_file()])
        source = batch.files.get()
        self.assertEqual(batch.status, 'uploaded')
        self.assertEqual(RescreenReference.objects.active().count(), 0)
        self.assertTrue(source.raw_file.storage.exists(source.raw_file.name))
        with self.assertRaises(ValueError):
            _ = source.raw_file.url
        self.assertEqual(user_storage_usage_bytes(self.user), source.size_bytes)
        process_import(batch.pk)
        reference = RescreenReference.objects.active().get()
        self.assertEqual(reference.title, 'Example title')
        self.assertEqual(reference.publication_year, '2026')
        self.assertTrue(reference.raw_metadata_versions.get().raw_fields)
        self.assertEqual(reference.corpus.revision, 1)
        self.assertEqual(process_import(batch.pk).status, 'completed')
        self.assertEqual(RescreenReference.objects.count(), 1)

    def test_idempotency_and_payload_conflict(self):
        batch = self.start([ris_file()])
        again = self.start([ris_file()])
        self.assertEqual(batch.pk, again.pk)
        self.assertEqual(Task.objects.filter(task_type='rescreen_import').count(), 1)
        with self.assertRaisesMessage(RescreenError, '幂等键'):
            self.start([ris_file(title='Changed')])

    def test_project_and_user_concurrency(self):
        self.start([ris_file()])
        with self.assertRaisesMessage(RescreenError, '活动任务'):
            self.start([ris_file('two.ris')], key='second')
        another = Project.objects.create(name='Another', owner=self.user)
        with self.assertRaisesMessage(RescreenError, '已有导入任务'):
            start_import(project=another, user=self.user, idempotency_key='x', uploads=[ris_file()])

    @override_settings(SCREENING_IMPORT_DB_BATCH_SIZE=1)
    def test_failed_staging_is_removed_and_retry_publishes_once(self):
        batch = self.start([two_record_ris()])
        original = __import__('core.rescreening.services.persistence', fromlist=['ReferenceWriter']).ReferenceWriter.add
        calls = []
        def fail_second(writer, record, **kwargs):
            calls.append(record)
            if len(calls) == 2:
                raise RuntimeError('simulated parser failure')
            return original(writer, record, **kwargs)
        with patch('core.rescreening.services.persistence.ReferenceWriter.add', new=fail_second):
            with self.assertRaises(RescreenError):
                process_import(batch.pk)
        batch.refresh_from_db()
        self.assertEqual(batch.status, 'failed')
        self.assertEqual(RescreenReference.objects.count(), 0)
        self.assertEqual(RescreenCorpus.objects.get().revision, 0)
        self.assertTrue(batch.files.get().report)
        Task.objects.filter(pk=batch.task_id).update(status='failed')
        retry_import(batch_id=batch.pk, user=self.user)
        process_import(batch.pk)
        self.assertEqual(RescreenReference.objects.active().count(), 2)
        self.assertEqual(RescreenCorpus.objects.get().revision, 1)

    def test_nonblocking_parser_warning_still_imports(self):
        batch = self.completed([bibtex_with_recoverable_invalid_key()])
        self.assertEqual(batch.accepted_count, 1)
        self.assertEqual(batch.status, 'completed')
        self.assertGreater(batch.files.get().report['error_count'], 0)

    def test_reference_limit_is_hard_even_with_partial_import(self):
        batch = self.start([two_record_ris()])
        snapshot = dict(batch.limits_snapshot, max_references=1, warning_references=1,
                        max_reported_errors=1, db_batch_size=1, allow_partial=True)
        RescreenImportBatch.objects.filter(pk=batch.pk).update(limits_snapshot=snapshot)
        with self.assertRaises(ScreeningImportError):
            process_import(batch.pk)
        self.assertEqual(RescreenReference.objects.active().count(), 0)
        self.assertEqual(RescreenCorpus.objects.get().revision, 0)

    def test_stop_never_publishes(self):
        batch = self.start([ris_file()])
        with self.assertRaisesMessage(RescreenError, '停止'):
            process_import(batch.pk, stop_checker=lambda: True)
        batch.refresh_from_db()
        self.assertEqual(batch.status, 'cancelled')
        self.assertEqual(RescreenReference.objects.active().count(), 0)

    def test_remove_is_revision_checked_and_soft(self):
        batch = self.completed()
        self.finish_task(batch)
        ref = RescreenReference.objects.get()
        with self.assertRaisesMessage(RescreenError, '已变化'):
            remove_references(project=self.project, user=self.user, ids=[ref.pk], expected_revision=0)
        result = remove_references(project=self.project, user=self.user, ids=[ref.pk], expected_revision=1)
        self.assertEqual(result, {'removed': 1, 'revision': 2, 'total': 0})
        self.assertTrue(RescreenReference.objects.filter(pk=ref.pk).exists())
        self.assertEqual(RescreenReference.objects.active().count(), 0)
        self.assertEqual(RescreenReferenceRawMetadata.objects.count(), 1)

    def test_duplicate_completed_source_file_rejected(self):
        batch = self.completed()
        self.finish_task(batch)
        with self.assertRaisesMessage(RescreenError, '已成功导入'):
            self.start([ris_file('different-name.ris')], key='next')

    def test_original_metadata_cannot_be_overwritten(self):
        self.completed()
        raw = RescreenReferenceRawMetadata.objects.get()
        with self.assertRaisesMessage(ValueError, '不可覆盖'):
            raw.save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            RescreenReferenceRawMetadata.objects.bulk_create([RescreenReferenceRawMetadata(
                reference_id=raw.reference_id, input_version=1, raw_fields={}, raw_hash='', raw_size_bytes=0)])

    def test_list_is_paginated_and_does_not_fetch_cold_metadata(self):
        self.completed([two_record_ris()])
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get('/api/rescreening/references/',
                {'project_id': self.project.pk, 'page_size': 1, 'page': 2})
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()['data']
        self.assertEqual(data['total'], 2)
        self.assertEqual(len(data['items']), 1)
        self.assertNotIn('raw_fields', str(data))
        self.assertFalse(any('plat_rescreen_reference_raw' in row['sql'] for row in queries))
        self.assertTrue(any('LIMIT 1 OFFSET 1' in row['sql'] for row in queries))
        self.assertEqual(self.client.get('/api/rescreening/references/',
            {'project_id': self.project.pk, 'page_size': 201}).status_code, 400)

    def test_resource_isolation_and_role_diagnostics(self):
        batch = self.completed()
        ref = RescreenReference.objects.get()
        path = f'/api/rescreening/references/{ref.pk}/raw/'
        self.assertEqual(self.client.get(path).status_code, 403)
        self.user.profile.role = 'researcher'
        self.user.profile.save(update_fields=['role'])
        self.assertEqual(self.client.get(path).status_code, 200)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.client.get(f'/api/rescreening/imports/{batch.pk}/').status_code, 404)
        self.assertEqual(self.client.get(f'/api/rescreening/imports/files/{batch.files.get().pk}/download/').status_code, 404)

    def test_http_upload_dispatch_and_original_download(self):
        with patch('core.executors.celery_tasks.execute_async_step.delay', return_value=SimpleNamespace(id='job')) as dispatch, self.captureOnCommitCallbacks(execute=True):
            response = self.client.post('/api/rescreening/imports/upload/',
                {'project_id': self.project.pk, 'files': [ris_file()]}, format='multipart', HTTP_IDEMPOTENCY_KEY='http-key')
        self.assertEqual(response.status_code, 202, response.content)
        dispatch.assert_called_once()
        batch = RescreenImportBatch.objects.get(pk=response.json()['data']['id'])
        response = self.client.get(f'/api/rescreening/imports/files/{batch.files.get().pk}/download/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'TI  - Example title', b''.join(response.streaming_content))

    def test_real_task_executor_without_model_calls(self):
        batch = self.start([ris_file()])
        from core.executors.celery_tasks import execute_async_step
        result = execute_async_step.apply(args=[batch.task_id, 'rescreen_import', self.project.pk], throw=True)
        self.assertTrue(result.result)
        batch.refresh_from_db()
        self.assertEqual(batch.status, 'completed')
        self.assertEqual(Task.objects.get(pk=batch.task_id).status, 'completed')

    def test_project_deletion_removes_private_files_and_rows(self):
        batch = self.completed()
        source = batch.files.get().raw_file
        with self.captureOnCommitCallbacks(execute=True):
            self.project.delete()
        self.assertFalse(source.storage.exists(source.name))
        self.assertEqual(RescreenReferenceRawMetadata.objects.count(), 0)

    def test_shared_asset_quota_and_deletion(self):
        asset = FulltextAsset(project=self.project, sha256='a'*64, original_filename='x.pdf', size_bytes=3)
        asset.raw_file.save('x.pdf', ContentFile(b'pdf'), save=False)
        asset.extracted_text_file.save('x.txt', ContentFile(b'12345'), save=False)
        asset.save()
        original = asset.raw_file.path
        self.assertEqual(user_storage_usage_bytes(self.user), 8)
        with self.captureOnCommitCallbacks(execute=True):
            asset.delete()
        self.assertFalse(Path(original).exists())

    @override_settings(SCREENING_IMPORT_RATE_LIMIT_REQUESTS=1)
    def test_retry_counts_toward_rate_limit(self):
        batch = self.start([ris_file()])
        RescreenImportBatch.objects.filter(pk=batch.pk).update(status='failed')
        Task.objects.filter(pk=batch.task_id).update(status='failed')
        with self.assertRaisesMessage(RescreenError, '频繁'):
            retry_import(batch_id=batch.pk, user=self.user)

    def screening_source(self):
        from core.models import DataFile, StageStep
        from core.screening.models import (ScreeningCorpus, ReferenceImportBatch, ReferenceImportFile,
            ScreeningReference, ScreeningReferenceRawMetadata, ScreeningRun, ScreeningResult)
        from core.rescreening.services.source import digest
        corpus = ScreeningCorpus.objects.create(project=self.project, revision=1, active_reference_count=1)
        batch = ReferenceImportBatch.objects.create(project=self.project, corpus=corpus,
            base_revision=0, target_revision=1, status='completed', operation='add')
        data_file = DataFile.objects.create(project=self.project, filename='original.ris', file_type='ris')
        source_file = ReferenceImportFile.objects.create(import_batch=batch, source_file=data_file,
            original_filename='original.ris', sha256='f'*64, source_format='ris', introduced_revision=1)
        fields = bibliography_fields(dict(title='完整来源标题', authors=['作者'], year='2026',
            date='2026/10', journal='期刊', doi='10.1/example', page='1-10',
            source_identifier='original-0001', keywords=['关键字'], publisher='出版社',
            abstract='完整摘要', organization='单位', address='地址', database='数据库',
            pmid='123', pmcid='PMC123', isbn='isbn', issn='issn', url='https://example.org',
            language='zh', volume='12', issue='3', reference_type='Journal Article'))
        reference = ScreeningReference.objects.create(project=self.project, corpus=corpus,
            import_batch=batch, import_file=source_file, source_file=data_file, source_record_index=1,
            introduced_revision=1, normalized_title_hash='a'*64, record_hash='b'*64, **fields)
        raw = {'TY': ['JOUR'], 'CUSTOM': ['额外原始字段']}
        ScreeningReferenceRawMetadata.objects.create(reference=reference, import_file=source_file, raw_fields=raw,
            raw_hash=digest(raw), raw_size_bytes=64, source_format='ris', parser_version='source-v1')
        run = ScreeningRun.objects.create(project=self.project, corpus=corpus, corpus_revision=1,
            status='completed', created_by=self.user)
        result = ScreeningResult.objects.create(screening_run=run, reference=reference,
            status='completed', decision='included', consensus='included', extracted_fields={'design': 'RCT'})
        StageStep.objects.filter(stage__project=self.project, step_key='field_extraction').update(
            metadata={'fields': [{'key': 'design', 'name': '研究设计'}]})
        return reference, run, result

    def test_screening_import_preserves_every_field_and_cold_metadata(self):
        from core.rescreening.services.source import source_preview
        source, run, result = self.screening_source()
        preview = source_preview(self.project)
        self.assertEqual(preview['new_count'], 1)
        batch = self.start(preview=preview)
        process_import(batch.pk)
        reference = RescreenReference.objects.active().get()
        self.assertEqual(bibliography_snapshot(reference), bibliography_snapshot(source))
        self.assertEqual(reference.source_reference_id, source.pk)
        self.assertEqual(reference.source_screening_run_id, run.pk)
        raw = reference.raw_metadata_versions.get()
        self.assertEqual(raw.raw_fields, source.raw_metadata_record.raw_fields)
        self.assertEqual(raw.source_extracted_fields, result.extracted_fields)
        self.assertEqual(raw.source_field_definitions['captured_from'], 'stage_at_import')
        self.finish_task(batch)
        again = self.start(key='second', preview=source_preview(self.project))
        process_import(again.pk)
        self.assertEqual(RescreenReference.objects.active().count(), 1)
        self.assertEqual(RescreenCorpus.objects.get().revision, 1)

    def test_source_change_does_not_silently_overwrite(self):
        from core.rescreening.services.source import source_preview
        source, run, result = self.screening_source()
        batch = self.start(preview=source_preview(self.project))
        process_import(batch.pk)
        self.finish_task(batch)
        source.title = '来源修改后的标题'
        source.save(update_fields=['title'])
        preview = source_preview(self.project)
        self.assertEqual(preview['changed_count'], 1)
        with self.assertRaisesMessage(RescreenError, '来源有变化'):
            self.start(key='second', preview=preview)
        self.assertEqual(RescreenReference.objects.get().title, '完整来源标题')

    def test_source_change_during_import_prevents_publication(self):
        from core.rescreening.services.source import source_preview
        source, run, result = self.screening_source()
        batch = self.start(preview=source_preview(self.project))
        result.extracted_fields = {'design': 'changed'}
        result.save(update_fields=['extracted_fields'])
        with self.assertRaisesMessage(RescreenError, '导入期间变化'):
            process_import(batch.pk)
        self.assertEqual(RescreenReference.objects.count(), 0)
        self.assertEqual(RescreenCorpus.objects.get().revision, 0)

    def test_manual_final_decision_controls_source_import(self):
        from core.models import ManualReview, StageStep
        from core.rescreening.services.source import source_preview
        source, run, result = self.screening_source()
        ManualReview.objects.create(project=self.project, reference=source, screening_run=run,
            decision='excluded', step=StageStep.objects.get(stage__project=self.project, step_key='review'))
        preview = source_preview(self.project)
        self.assertEqual(preview['new_count'], 0)
        self.assertEqual(preview['counts']['excluded'], 1)

    def test_cancelling_worker_blocks_retry_and_old_task_cannot_fail_new_attempt(self):
        from core.rescreening.services.lifecycle import finish_unpublished_batch
        batch = self.start([ris_file()])
        old_task_id = batch.task_id
        RescreenImportBatch.objects.filter(pk=batch.pk).update(status='importing')
        Task.objects.filter(pk=old_task_id).update(status='stopped')
        finish_unpublished_batch(batch.pk, cancelled=True, requested=True, task_id=old_task_id)
        batch.refresh_from_db()
        self.assertEqual(batch.status, 'cancelling')
        with self.assertRaisesMessage(RescreenError, '只有失败'):
            retry_import(batch_id=batch.pk, user=self.user)
        finish_unpublished_batch(batch.pk, cancelled=True, task_id=old_task_id)
        retry_import(batch_id=batch.pk, user=self.user)
        finish_unpublished_batch(batch.pk, task_id=old_task_id)
        batch.refresh_from_db()
        self.assertEqual(batch.status, 'uploaded')
        with self.assertRaisesMessage(RescreenError, '新的导入尝试'):
            process_import(batch.pk, expected_task_id=old_task_id)
        batch.refresh_from_db()
        self.assertEqual(batch.status, 'uploaded')

    def test_registered_formats_keep_bibliography_and_original_fields(self):
        samples = {
            'record.xml': '<xml><records><record><rec-number>42</rec-number><ref-type name="Journal Article">17</ref-type><titles><title>XML Title</title><secondary-title>Journal</secondary-title></titles><contributors><authors><author>Author</author></authors></contributors><dates><year>2026</year></dates><abstract>Abstract</abstract><custom1>keep-custom</custom1></record></records></xml>',
            'record.enw': '%0 Journal Article\n%T ENW Title\n%A Author\n%D 2026\n%X Abstract\n',
            'record.nbib': 'PMID- 123456\nTI  - NBIB Title\nAU  - Author\nDP  - 2026\nAB  - Abstract\n',
            'record.ciw': 'FN Clarivate Analytics Web of Science\nVR 1.0\nPT J\nTI CIW Title\nAU Author\nPY 2026\nAB Abstract\nER\nEF\n',
            'record.bib': '@article{example, title={Bib Title}, author={Author}, year={2026}, abstract={Abstract}, custom={keep-custom}}',
        }
        for index, (name, payload) in enumerate(samples.items()):
            with self.subTest(name=name):
                batch = self.completed([SimpleUploadedFile(name, payload.encode())], key=f'format-{index}')
                reference = batch.references.get()
                self.assertTrue(reference.title)
                self.assertEqual(reference.publication_year, '2026')
                self.assertTrue(reference.raw_metadata_versions.get().raw_fields)
                self.finish_task(batch)

    def test_local_regression_samples_when_available(self):
        from core.screening.parsers import iter_file, validate_reference_record, ReferenceRecordValidationError
        from core.screening.services.reference_persistence import _raw_metadata_payload
        root = Path(__file__).resolve().parents[2] / 'meta_project' / 'Screen_input'
        if not root.is_dir():
            self.skipTest('本地回归样本未随仓库提交；基础格式矩阵另有固定测试。')
        for index, path in enumerate(sorted(root.iterdir())):
            if not path.is_file() or path.name.startswith('.'):
                continue
            with self.subTest(filename=path.name):
                batch = self.start([SimpleUploadedFile(path.name, path.read_bytes())], key=f'sample-{index}')
                try:
                    batch = process_import(batch.pk)
                except RescreenError as exc:
                    self.assertEqual(exc.code, 'blocking_parse_errors')
                    self.assertEqual(path.name, '机械通气.xml')
                    self.assertEqual(RescreenReference.objects.filter(import_batch=batch).count(), 0)
                    issues = batch.files.get().report['issues']
                    self.assertTrue(any(item['code'] == 'too_many_authors' for item in issues))
                    Task.objects.filter(pk=batch.task_id).update(status='failed')
                    with override_settings(SCREENING_IMPORT_ALLOW_PARTIAL=True):
                        retry_import(batch_id=batch.pk, user=self.user)
                        batch = process_import(batch.pk)
                    self.assertEqual(batch.rejected_count, 3)
                references = iter(batch.references.order_by('source_record_index'))
                raws = {raw.reference_id: raw for raw in RescreenReferenceRawMetadata.objects.filter(reference__import_batch=batch)}
                count = 0
                for record in iter_file(str(path)):
                    try:
                        validate_reference_record(record, ImportLimits.from_settings())
                    except ReferenceRecordValidationError:
                        continue
                    ref = next(references)
                    self.assertEqual(bibliography_snapshot(ref), bibliography_fields(record))
                    self.assertEqual(raws[ref.pk].raw_fields, _raw_metadata_payload(record)[0])
                    count += 1
                self.assertIsNone(next(references, None))
                self.assertEqual(batch.accepted_count, count)
                self.finish_task(batch)
                print(f'复筛离线样本: {path.name} → {count} 条，全部标准字段及原始元数据一致')

    def test_failed_retention_cleanup_does_not_touch_successful_import(self):
        from datetime import timedelta
        from django.utils import timezone
        from core.rescreening.services.cleanup import cleanup_failed_imports
        successful = self.completed()
        self.finish_task(successful)
        failed = self.start([ris_file('bad.ris', 'Another')], key='failed')
        failed_file = failed.files.get().raw_file
        RescreenImportBatch.objects.filter(pk=failed.pk).update(status='failed',
            finished_at=timezone.now()-timedelta(days=30))
        Task.objects.filter(pk=failed.task_id).update(status='failed')
        with self.captureOnCommitCallbacks(execute=True):
            result = cleanup_failed_imports()
        self.assertEqual(result['purged_files'], 1)
        self.assertFalse(failed_file.storage.exists(failed_file.name))
        self.assertTrue(successful.files.exists())
        self.assertEqual(RescreenReference.objects.active().count(), 1)
        with self.assertRaisesMessage(RescreenError, '超过保留期'):
            retry_import(batch_id=failed.pk, user=self.user)

    def test_admin_audit_is_readonly_and_does_not_block_project_cascade(self):
        from django.contrib import admin
        from django.contrib.admin.utils import get_deleted_objects
        from django.test import RequestFactory
        from django.test import Client
        batch = self.completed()
        superuser = get_user_model().objects.create_superuser('rescreen-admin', password='pw')
        request = RequestFactory().get(f'/admin/core/project/{self.project.pk}/delete/')
        request.user = superuser
        _, _, permissions, protected = get_deleted_objects([self.project], request, admin.site)
        self.assertEqual(permissions, set())
        self.assertEqual(protected, [])
        client = Client()
        client.force_login(superuser)
        file_id = batch.files.get().pk
        response = client.get(f'/admin/core/rescreenimportfile/{file_id}/change/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(client.post(f'/admin/core/rescreenimportfile/{file_id}/change/', {}).status_code, 403)
