"""Upload limits, import state transitions and incremental source handling."""

import tempfile
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from core.artifacts.types import ArtifactType
from core.executors.celery_tasks import execute_async_step
from core.models import DataFile, Project, Task
from core.screening.models import (
    ReferenceImportBatch,
    ReferenceImportFile,
    ScreeningCorpus,
    ScreeningReference,
    ScreeningReferenceRawMetadata,
)
from core.screening.services.import_service import (
    cleanup_abandoned_import_files,
    fail_import_batch,
)
from core.services.project_service import initialize_project
from core.workflow.domain.statuses import TaskStatus
from core.workflow.services.lifecycle import transition_task


User = get_user_model()


def ris_file(name='sample.ris', title='Example title'):
    return SimpleUploadedFile(
        name,
        (
            'TY  - JOUR\n'
            f'TI  - {title}\n'
            'AB  - An abstract\n'
            'PY  - 2026\n'
            'ER  -\n'
        ).encode(),
        content_type='application/x-research-info-systems',
    )


def two_record_ris(name='two-records.ris'):
    return SimpleUploadedFile(
        name,
        (
            'TY  - JOUR\nTI  - First\nAB  - One\nER  -\n'
            'TY  - JOUR\nTI  - Second\nAB  - Two\nER  -\n'
        ).encode(),
        content_type='application/x-research-info-systems',
    )


def bibtex_with_recoverable_invalid_key(name='citation-export.bib'):
    return SimpleUploadedFile(
        name,
        (
            '@article{ValidKey,\n'
            'title = {Valid title},\nabstract = {Present},\ncustomfield = {Keep me},\n}\n'
            '@article{Invalid Key,\n'
            'title = {Skipped title},\nabstract = {Present},\n}\n'
        ).encode(),
        content_type='application/x-bibtex',
    )


class ScreeningImportApiTests(TransactionTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.settings_override = override_settings(
            BASE_DIR=root,
            MEDIA_ROOT=root / 'media',
            SCREENING_IMPORT_UPLOAD_ROOT=root / 'private-imports',
        )
        self.settings_override.enable()
        self.user = User.objects.create_user('import-user', password='pw')
        self.project = Project.objects.create(name='Import project', owner=self.user)
        initialize_project(self.project, self.user)
        self.client.force_login(self.user)

    def tearDown(self):
        self.settings_override.disable()
        self.temp_dir.cleanup()

    def upload_batch(self, *files):
        with patch(
            'core.executors.celery_tasks.execute_async_step.delay',
            return_value=SimpleNamespace(id='broker-import-job'),
        ):
            return self.client.post(
                '/api/screening-imports/',
                {'project': str(self.project.id), 'files': list(files)},
            )

    def test_batch_upload_is_private_and_dispatches_exact_file_ids(self):
        response = self.upload_batch(ris_file('one.ris', 'One'), ris_file('two.ris', 'Two'))

        self.assertEqual(response.status_code, 201, response.content)
        payload = response.json()
        batch = ReferenceImportBatch.objects.get(pk=payload['id'])
        self.assertEqual(batch.status, ReferenceImportBatch.Status.UPLOADED)
        self.assertEqual(batch.file_count, 2)
        self.assertEqual(len(payload['files']), 2)
        self.assertEqual(payload['task']['status'], 'pending')

        task = Task.objects.get(pk=payload['task']['id'])
        source_ids = list(batch.files.order_by('id').values_list('source_file_id', flat=True))
        self.assertEqual(set(task.config['file_ids']), set(source_ids))
        self.assertEqual(task.config['import_batch_id'], batch.id)
        for item in batch.files.select_related('source_file'):
            self.assertFalse(item.source_file.file)
            self.assertTrue(Path(item.raw_file.path).is_file())
            self.assertNotIn(item.original_filename, Path(item.raw_file.name).name)

    def test_generic_file_endpoint_rejects_screening_index_uploads(self):
        response = self.client.post(
            '/api/files/',
            {
                'project': self.project.id,
                'data_category': 'input',
                'filename': 'bypass.ris',
                'file': ris_file('bypass.ris'),
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()['error']['code'],
            'screening_import_endpoint_required',
        )
        self.assertEqual(DataFile.objects.count(), 0)

    @override_settings(SCREENING_IMPORT_MAX_FILE_BYTES=16)
    def test_oversized_request_is_rejected_without_partial_database_rows(self):
        response = self.upload_batch(ris_file())

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()['error']['code'], 'file_too_large')
        self.assertEqual(ReferenceImportBatch.objects.count(), 0)
        self.assertEqual(ReferenceImportFile.objects.count(), 0)
        self.assertEqual(DataFile.objects.count(), 0)

    def test_unsupported_or_mismatched_file_is_rejected(self):
        unsupported = SimpleUploadedFile('malware.exe', b'MZ fake')
        response = self.upload_batch(unsupported)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['error']['code'], 'unsupported_format')

        fake_ris = SimpleUploadedFile('fake.ris', b'plain text without records')
        response = self.upload_batch(fake_ris)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['error']['code'], 'file_signature_mismatch')

    def test_second_active_import_is_rejected(self):
        first = self.upload_batch(ris_file('one.ris', 'One'))
        self.assertEqual(first.status_code, 201)

        second = self.upload_batch(ris_file('two.ris', 'Two'))
        self.assertEqual(second.status_code, 409)
        self.assertIn(
            second.json()['error']['code'],
            {'screening_task_active', 'import_already_running'},
        )
        self.assertEqual(ReferenceImportBatch.objects.count(), 1)

    def test_pending_batch_can_be_cancelled_and_retried(self):
        response = self.upload_batch(ris_file())
        batch = ReferenceImportBatch.objects.get(pk=response.json()['id'])
        original_task_id = batch.task_id

        cancelled = self.client.post(f'/api/screening-imports/{batch.id}/cancel/')
        self.assertEqual(cancelled.status_code, 200, cancelled.content)
        batch.refresh_from_db()
        self.assertEqual(batch.status, ReferenceImportBatch.Status.CANCELLED)
        self.assertEqual(Task.objects.get(pk=original_task_id).status, TaskStatus.STOPPED)

        with patch(
            'core.executors.celery_tasks.execute_async_step.delay',
            return_value=SimpleNamespace(id='broker-retry-job'),
        ):
            retried = self.client.post(f'/api/screening-imports/{batch.id}/retry/')

        self.assertEqual(retried.status_code, 202, retried.content)
        batch.refresh_from_db()
        self.assertEqual(batch.status, ReferenceImportBatch.Status.UPLOADED)
        self.assertNotEqual(batch.task_id, original_task_id)
        self.assertEqual(batch.task.celery_task_id, 'broker-retry-job')

    def test_dispatch_failure_keeps_retryable_private_assets(self):
        with patch(
            'core.executors.celery_tasks.execute_async_step.delay',
            side_effect=RuntimeError('broker unavailable'),
        ):
            response = self.client.post(
                '/api/screening-imports/',
                {'project': self.project.id, 'files': [ris_file()]},
            )

        self.assertEqual(response.status_code, 503, response.content)
        batch = ReferenceImportBatch.objects.get()
        self.assertEqual(batch.status, ReferenceImportBatch.Status.FAILED)
        self.assertTrue(Path(batch.files.get().raw_file.path).is_file())

    def test_failed_batch_can_be_deleted_with_all_retained_files(self):
        response = self.upload_batch(ris_file())
        batch = ReferenceImportBatch.objects.get(pk=response.json()['id'])
        transition_task(batch.task, TaskStatus.FAILED)
        fail_import_batch(batch.id)
        import_file = batch.files.get()
        private_path = Path(import_file.raw_file.path)
        source_file_id = import_file.source_file_id

        deleted = self.client.delete(f'/api/screening-imports/{batch.id}/')

        self.assertEqual(deleted.status_code, 204, deleted.content)
        self.assertFalse(ReferenceImportBatch.objects.filter(pk=batch.id).exists())
        self.assertFalse(DataFile.objects.filter(pk=source_file_id).exists())
        self.assertFalse(private_path.exists())

    def test_completed_batch_cannot_be_deleted_as_failed_history(self):
        response = self.upload_batch(ris_file())
        batch = ReferenceImportBatch.objects.get(pk=response.json()['id'])
        self.assertTrue(execute_async_step.run(batch.task_id, 'parse', self.project.id))

        deleted = self.client.delete(f'/api/screening-imports/{batch.id}/')

        self.assertEqual(deleted.status_code, 409, deleted.content)
        self.assertEqual(deleted.json()['error']['code'], 'invalid_import_state')
        self.assertTrue(ReferenceImportBatch.objects.filter(pk=batch.id).exists())

    def test_import_batch_list_can_be_scoped_to_project(self):
        visible_project = Project.objects.create(name='Second project', owner=self.user)
        initialize_project(visible_project, self.user)
        first = self.upload_batch(ris_file('first.ris', 'First')).json()['id']
        self.client.post(f'/api/screening-imports/{first}/cancel/')
        with patch(
            'core.executors.celery_tasks.execute_async_step.delay',
            return_value=SimpleNamespace(id='broker-second-project'),
        ):
            second_response = self.client.post(
                '/api/screening-imports/',
                {'project': visible_project.id, 'files': [ris_file('second.ris', 'Second')]},
            )
        second = second_response.json()['id']

        listed = self.client.get('/api/screening-imports/', {'project': self.project.id})

        self.assertEqual(listed.status_code, 200, listed.content)
        self.assertEqual([item['id'] for item in listed.json()['results']], [first])
        self.assertNotIn(second, [item['id'] for item in listed.json()['results']])

    def test_old_failed_batch_private_files_can_be_purged(self):
        response = self.upload_batch(ris_file())
        batch = ReferenceImportBatch.objects.get(pk=response.json()['id'])
        transition_task(batch.task, TaskStatus.FAILED)
        fail_import_batch(batch.id)
        old_time = timezone.now() - timedelta(days=8)
        ReferenceImportBatch.objects.filter(pk=batch.pk).update(finished_at=old_time)
        import_file = batch.files.get()
        private_path = Path(import_file.raw_file.path)
        source_file_id = import_file.source_file_id

        result = cleanup_abandoned_import_files(now=timezone.now())

        self.assertEqual(result['purged_files'], 1)
        self.assertFalse(private_path.exists())
        self.assertFalse(DataFile.objects.filter(pk=source_file_id).exists())
        batch.refresh_from_db()
        self.assertFalse(batch.files.exists())
        self.assertIn('raw_files_purged_at', batch.config_snapshot)

    def test_user_cannot_create_import_for_another_project(self):
        owner = User.objects.create_user('other-owner')
        other_project = Project.objects.create(name='Other', owner=owner)
        initialize_project(other_project, owner)

        response = self.client.post(
            '/api/screening-imports/',
            {'project': other_project.id, 'files': [ris_file()]},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(ReferenceImportBatch.objects.count(), 0)

    def test_incremental_add_and_remove_preserve_unaffected_parse_outputs(self):
        first_response = self.upload_batch(ris_file('one.ris', 'One'))
        first_batch = ReferenceImportBatch.objects.get(pk=first_response.json()['id'])
        self.assertTrue(execute_async_step.run(first_batch.task_id, 'parse', self.project.id))
        first_batch.refresh_from_db()
        self.assertEqual(first_batch.status, ReferenceImportBatch.Status.COMPLETED)

        second_response = self.upload_batch(ris_file('two.ris', 'Two'))
        second_batch = ReferenceImportBatch.objects.get(pk=second_response.json()['id'])
        self.assertTrue(execute_async_step.run(second_batch.task_id, 'parse', self.project.id))
        second_batch.refresh_from_db()
        self.assertEqual(second_batch.status, ReferenceImportBatch.Status.COMPLETED)

        corpus = ScreeningCorpus.objects.get(project=self.project)
        self.assertEqual(corpus.revision, 2)
        self.assertEqual(corpus.active_reference_count, 2)
        self.assertEqual(corpus.active_source_file_count, 2)
        self.assertEqual(
            list(
                ScreeningReference.objects.current()
                .order_by('title')
                .values_list('title', 'introduced_revision')
            ),
            [('One', 1), ('Two', 2)],
        )
        first_reference = ScreeningReference.objects.get(title='One')
        self.assertEqual(first_reference.source_record_index, 1)
        self.assertEqual(len(first_reference.normalized_title_hash), 64)
        self.assertEqual(len(first_reference.record_hash), 64)
        parsed = DataFile.objects.filter(
            project=self.project,
            metadata__artifact_type='screening_parsed_reference_xml',
        )
        self.assertEqual(parsed.count(), 0)
        first_source = first_batch.files.get().source_file
        second_source = second_batch.files.get().source_file

        delete_response = self.client.delete(f'/api/files/{first_source.id}/')
        self.assertEqual(delete_response.status_code, 204, delete_response.content)
        corpus.refresh_from_db()
        self.assertEqual(corpus.revision, 3)
        self.assertEqual(corpus.active_reference_count, 1)
        self.assertEqual(corpus.active_source_file_count, 1)
        self.assertEqual(
            list(ScreeningReference.objects.current().values_list('title', flat=True)),
            ['Two'],
        )
        removed_reference = ScreeningReference.objects.get(title='One')
        self.assertEqual(removed_reference.removed_revision, 3)
        self.assertTrue(DataFile.objects.filter(pk=first_source.id).exists())
        self.assertFalse(parsed.filter(metadata__source_file_id=first_source.id).exists())
        self.assertFalse(parsed.filter(metadata__source_file_id=second_source.id).exists())

        listed = self.client.get(
            '/api/files/',
            {'project': self.project.id, 'data_category': 'input'},
        ).json()['results']
        self.assertEqual([item['id'] for item in listed], [second_source.id])

    def test_recoverable_bibtex_diagnostic_does_not_reject_valid_records(self):
        response = self.upload_batch(bibtex_with_recoverable_invalid_key())
        batch = ReferenceImportBatch.objects.get(pk=response.json()['id'])

        self.assertTrue(execute_async_step.run(batch.task_id, 'parse', self.project.id))

        batch.refresh_from_db()
        corpus = ScreeningCorpus.objects.get(project=self.project)
        import_file = batch.files.get()
        self.assertEqual(batch.status, ReferenceImportBatch.Status.COMPLETED)
        self.assertEqual(corpus.active_reference_count, 1)
        self.assertEqual(import_file.detected_count, 2)
        self.assertEqual(import_file.parsed_count, 1)
        self.assertEqual(import_file.skipped_count, 1)
        self.assertEqual(import_file.error_count, 1)
        self.assertTrue(import_file.issues.filter(code='invalid_citation_key').exists())
        reference = ScreeningReference.objects.get(import_batch=batch)
        raw = ScreeningReferenceRawMetadata.objects.get(reference=reference)
        self.assertEqual(raw.raw_fields['customfield'], 'Keep me')
        self.assertEqual(raw.source_format, 'BIB')
        self.assertGreater(raw.raw_size_bytes, 0)
        self.assertEqual(len(raw.raw_hash), 64)

        report = self.client.get(f'/api/files/{import_file.source_file_id}/parse-report/')
        self.assertEqual(report.status_code, 200)
        self.assertEqual(report.json()['blocking_error_count'], 0)

    @override_settings(SCREENING_IMPORT_MAX_TITLE_CHARS=5)
    def test_rejected_records_never_remain_as_staged_database_rows(self):
        response = self.upload_batch(ris_file(title='Title too long'))
        batch = ReferenceImportBatch.objects.get(pk=response.json()['id'])

        with self.assertRaises(RuntimeError):
            execute_async_step.run(batch.task_id, 'parse', self.project.id)

        batch.refresh_from_db()
        corpus = ScreeningCorpus.objects.get(project=self.project)
        self.assertEqual(batch.status, ReferenceImportBatch.Status.FAILED)
        self.assertEqual(corpus.revision, 0)
        self.assertEqual(ScreeningReference.objects.filter(import_batch=batch).count(), 0)
        import_file = batch.files.get()
        self.assertGreaterEqual(import_file.error_count, 1)
        self.assertTrue(import_file.issues.filter(code='title_too_long').exists())
        self.assertTrue(DataFile.objects.filter(
            project=self.project,
            metadata__artifact_type=ArtifactType.SCREENING_PARSE_REPORT_JSON,
            metadata__source_file_id=import_file.source_file_id,
        ).exists())

    @override_settings(SCREENING_IMPORT_MAX_TITLE_CHARS=10)
    def test_blocking_partial_failure_keeps_diagnostic_report(self):
        uploaded = SimpleUploadedFile(
            'mixed.ris',
            (
                'TY  - JOUR\nTI  - Short\nAB  - Valid\nER  -\n'
                'TY  - JOUR\nTI  - This title is too long\nAB  - Invalid\nER  -\n'
            ).encode(),
            content_type='application/x-research-info-systems',
        )
        response = self.upload_batch(uploaded)
        batch = ReferenceImportBatch.objects.get(pk=response.json()['id'])

        with self.assertRaises(RuntimeError):
            execute_async_step.run(batch.task_id, 'parse', self.project.id)

        batch.refresh_from_db()
        import_file = batch.files.get()
        self.assertEqual(batch.status, ReferenceImportBatch.Status.FAILED)
        self.assertEqual(ScreeningCorpus.objects.get(project=self.project).revision, 0)
        report = self.client.get(f'/api/files/{import_file.source_file_id}/parse-report/')
        self.assertEqual(report.status_code, 200)
        self.assertEqual(report.json()['blocking_error_count'], 1)
        self.assertEqual(report.json()['parsed_entries'], 1)
        self.assertFalse(ScreeningReferenceRawMetadata.objects.filter(
            reference__import_batch=batch,
        ).exists())

    @override_settings(SCREENING_IMPORT_MAX_RAW_METADATA_BYTES=16)
    def test_oversized_raw_metadata_is_rejected_before_persistence(self):
        response = self.upload_batch(ris_file())
        batch = ReferenceImportBatch.objects.get(pk=response.json()['id'])

        with self.assertRaises(RuntimeError):
            execute_async_step.run(batch.task_id, 'parse', self.project.id)

        batch.refresh_from_db()
        import_file = batch.files.get()
        self.assertEqual(batch.status, ReferenceImportBatch.Status.FAILED)
        self.assertTrue(import_file.issues.filter(code='raw_metadata_too_large').exists())
        self.assertFalse(ScreeningReference.objects.filter(import_batch=batch).exists())
        self.assertFalse(ScreeningReferenceRawMetadata.objects.filter(
            reference__import_batch=batch,
        ).exists())

    @override_settings(
        SCREENING_IMPORT_MAX_REFERENCES=1,
        SCREENING_IMPORT_WARNING_REFERENCES=1,
        SCREENING_IMPORT_DB_BATCH_SIZE=1,
        SCREENING_PROCESSING_BATCH_SIZE=1,
        SCREENING_IMPORT_MAX_REPORTED_ERRORS=1,
    )
    def test_capacity_limit_includes_already_published_references(self):
        first_response = self.upload_batch(ris_file('one.ris', 'One'))
        first_batch = ReferenceImportBatch.objects.get(pk=first_response.json()['id'])
        self.assertTrue(execute_async_step.run(first_batch.task_id, 'parse', self.project.id))

        second_response = self.upload_batch(ris_file('two.ris', 'Two'))
        second_batch = ReferenceImportBatch.objects.get(pk=second_response.json()['id'])
        with self.assertRaises(RuntimeError):
            execute_async_step.run(second_batch.task_id, 'parse', self.project.id)

        second_batch.refresh_from_db()
        corpus = ScreeningCorpus.objects.get(project=self.project)
        self.assertEqual(second_batch.status, ReferenceImportBatch.Status.FAILED)
        self.assertEqual(corpus.revision, 1)
        self.assertEqual(corpus.active_reference_count, 1)
        self.assertEqual(
            list(ScreeningReference.objects.current().values_list('title', flat=True)),
            ['One'],
        )

    @override_settings(
        SCREENING_IMPORT_DB_BATCH_SIZE=1,
        SCREENING_PROCESSING_BATCH_SIZE=1,
    )
    def test_cancellation_removes_already_flushed_staged_rows(self):
        response = self.upload_batch(two_record_ris())
        batch = ReferenceImportBatch.objects.get(pk=response.json()['id'])

        with patch(
            'core.screening.executors.parse_handler.ParseHandler.check_stop_signal',
            side_effect=[False, False, True],
        ), self.assertRaises(RuntimeError):
            execute_async_step.run(batch.task_id, 'parse', self.project.id)

        batch.refresh_from_db()
        self.assertEqual(batch.status, ReferenceImportBatch.Status.CANCELLED)
        self.assertFalse(ScreeningReference.objects.filter(import_batch=batch).exists())
        self.assertEqual(ScreeningCorpus.objects.get(project=self.project).revision, 0)

    def test_revision_conflict_does_not_publish_staged_rows(self):
        response = self.upload_batch(ris_file())
        batch = ReferenceImportBatch.objects.get(pk=response.json()['id'])
        ScreeningCorpus.objects.filter(project=self.project).update(revision=1)

        with self.assertRaises(RuntimeError):
            execute_async_step.run(batch.task_id, 'parse', self.project.id)

        batch.refresh_from_db()
        corpus = ScreeningCorpus.objects.get(project=self.project)
        self.assertEqual(batch.status, ReferenceImportBatch.Status.FAILED)
        self.assertEqual(corpus.revision, 1)
        self.assertFalse(ScreeningReference.objects.filter(import_batch=batch).exists())
