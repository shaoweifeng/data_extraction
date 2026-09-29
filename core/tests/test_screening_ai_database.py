"""Stage 7 database-backed AI screening regression tests."""

import hashlib
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from core.models import ActivityLog, DataFile, ManualReview, Project, QAReference, Task
from core.models_billing import CreditTransaction, TokenUsageLog
from core.executors.executor import StepExecutor
from core.screening.models import (
    ReferenceImportBatch,
    ReferenceImportFile,
    ScreeningCorpus,
    ScreeningReference,
    ScreeningResult,
    ScreeningRun,
)
from core.screening.selectors import load_ai_results
from core.screening.services.screening_run_service import (
    ScreeningRunError,
    complete_screening_run,
    next_result_batch,
    pause_screening_run,
    persist_result_batch,
    prepare_screening_run,
)
from core.services.billing_service import grant_credits
from core.services.project_service import initialize_project


@override_settings(BILLING_CREDIT_TOKEN_RATIO=1000)
class ScreeningAIDatabaseTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('screening-ai-user', password='pw')
        self.project = Project.objects.create(name='AI database project', owner=self.user)
        initialize_project(self.project, self.user)
        self.corpus = ScreeningCorpus.objects.create(
            project=self.project,
            revision=1,
            active_reference_count=2,
            active_source_file_count=1,
        )
        self.batch = ReferenceImportBatch.objects.create(
            project=self.project,
            corpus=self.corpus,
            created_by=self.user,
            operation=ReferenceImportBatch.Operation.ADD,
            status=ReferenceImportBatch.Status.COMPLETED,
            base_revision=0,
            target_revision=1,
            published_revision=1,
        )
        self.source_file = DataFile.objects.create(
            project=self.project,
            filename='source.ris',
            file='screening/source.ris',
            file_size=100,
            file_type='ris',
            created_by=self.user,
        )
        self.import_file = ReferenceImportFile.objects.create(
            import_batch=self.batch,
            source_file=self.source_file,
            original_filename='source.ris',
            sha256='a' * 64,
            source_format='ris',
            introduced_revision=1,
        )
        self.references = [self._reference(1), self._reference(2)]
        self.task = Task.objects.create(
            project=self.project,
            task_type='ai_screen',
            status='running',
            config={'ai_model': 'test-model'},
            created_by=self.user,
        )

    def _reference(self, position):
        title = f'Reference {position}'
        return ScreeningReference.objects.create(
            project=self.project,
            corpus=self.corpus,
            import_batch=self.batch,
            import_file=self.import_file,
            source_file=self.source_file,
            source_record_index=position,
            introduced_revision=1,
            title=title,
            abstract=f'Abstract {position}',
            authors=[f'Author {position}'],
            publication_year='2026',
            normalized_title_hash=hashlib.sha256(title.lower().encode()).hexdigest(),
            record_hash=f'{position:064x}',
        )

    def _prepare(self):
        return prepare_screening_run(
            project=self.project,
            task=self.task,
            criteria=['Exclude ineligible studies'],
            model_ids=['test-model'],
            config=self.task.config,
        )[0]

    def _complete_rows(self, run, *, tokens=1000):
        rows = next_result_batch(run, 10)
        persist_result_batch(rows, [
            {
                'decision': 'included',
                'consensus': 'included',
                'token_usage': {'prompt': tokens, 'completion': 0, 'total': tokens},
            },
            {
                'decision': 'conflict',
                'consensus': 'conflict',
                'ai_summary_reason': 'models disagree',
                'multi_model_results': [{'model_id': 'a'}, {'model_id': 'b'}],
            },
        ])

    def _completed_run_for_review(self):
        run = self._prepare()
        self._complete_rows(run)
        ScreeningRun.objects.filter(pk=run.pk).update(
            status=ScreeningRun.Status.COMPLETED,
            processed_count=2,
            included_count=1,
            uncertain_count=1,
        )
        run.refresh_from_db()
        return run

    def test_seeds_and_persists_one_result_per_reference_without_json_files(self):
        run = self._prepare()
        self.assertEqual(run.results.count(), 2)

        self._complete_rows(run)

        included, uncertain = run.results.order_by('reference_id')
        self.assertEqual(included.decision, ScreeningResult.Decision.INCLUDED)
        self.assertEqual(uncertain.decision, ScreeningResult.Decision.UNCERTAIN)
        self.assertEqual(uncertain.consensus, 'conflict')
        self.assertFalse(
            DataFile.objects.filter(
                project=self.project,
                metadata__artifact_type='screening_result_json',
            ).exists()
        )

    def test_pending_input_api_returns_database_titles_not_compatibility_filenames(self):
        self.client.force_login(self.user)
        response = self.client.get(
            f'/api/projects/{self.project.id}/ai_screen_inputs/',
            {'limit': 1, 'offset': 0},
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['total'], 2)
        self.assertEqual(response.json()['results'][0]['title'], 'Reference 1')
        self.assertEqual(response.json()['results'][0]['reference_id'], self.references[0].id)

    def test_stopped_run_resumes_same_rows_and_resets_processing_claims(self):
        run = self._prepare()
        claimed = next_result_batch(run, 1)
        self.assertEqual(claimed[0].status, ScreeningResult.Status.PROCESSING)
        pause_screening_run(run.id)

        resumed, created = prepare_screening_run(
            project=self.project,
            task=self.task,
            criteria=['changed client value is ignored on resume'],
            model_ids=['test-model'],
            config=self.task.config,
        )

        self.assertFalse(created)
        self.assertEqual(resumed.id, run.id)
        self.assertEqual(resumed.results.count(), 2)
        self.assertEqual(
            resumed.results.filter(status=ScreeningResult.Status.PENDING).count(),
            2,
        )

    @override_settings(SCREENING_AI_MAX_ATTEMPTS=2)
    def test_failed_results_retry_same_rows_until_attempt_limit(self):
        run = self._prepare()
        first_attempt = next_result_batch(run, 2)
        persist_result_batch(first_attempt, [{'error': 'timeout'}, {'error': 'timeout'}])

        retry = next_result_batch(run, 2)
        self.assertEqual(
            [row.id for row in retry],
            [row.id for row in first_attempt],
        )
        persist_result_batch(retry, [{'error': 'timeout'}, {'decision': 'included'}])

        self.assertEqual(next_result_batch(run, 2), [])
        run.refresh_from_db()
        self.assertEqual(run.processed_count, 2)
        self.assertEqual(run.failed_count, 1)
        self.assertEqual(run.included_count, 1)
        self.assertEqual(run.results.get(status=ScreeningResult.Status.FAILED).attempt_count, 2)

    def test_completion_and_retry_charge_once_and_selectors_read_database(self):
        grant_credits(self.user, 10, note='test')
        run = self._prepare()
        self._complete_rows(run)

        completed, _ = complete_screening_run(
            run.id,
            task=self.task,
            model_ids=['test-model'],
        )
        complete_screening_run(run.id, task=self.task, model_ids=['test-model'])

        self.user.credit_account.refresh_from_db()
        self.assertEqual(completed.status, ScreeningRun.Status.COMPLETED)
        self.assertEqual(self.user.credit_account.balance, 9)
        self.assertEqual(
            CreditTransaction.objects.filter(
                idempotency_key=f'screening-run:{run.id}:usage',
            ).count(),
            1,
        )
        self.assertEqual(TokenUsageLog.objects.filter(task=self.task).count(), 1)
        payloads = load_ai_results(self.project.id)
        self.assertEqual(len(payloads), 2)
        self.assertEqual(payloads[1]['consensus'], 'conflict')

        self.client.force_login(self.user)
        review_step = self.project.stages.get(stage_key='SCREEN_1').steps.get(step_key='review')
        response = self.client.get('/api/review/list/', {
            'project': self.project.id,
            'step': review_step.id,
            'page': 1,
            'page_size': 10,
        })
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['total'], 2)
        self.assertEqual(response.json()['results'][0]['reference_id'], self.references[0].id)

    def test_revision_conflict_rolls_back_billing_and_fails_run(self):
        grant_credits(self.user, 10, note='test')
        run = self._prepare()
        self._complete_rows(run)
        ScreeningCorpus.objects.filter(pk=self.corpus.pk).update(revision=2)

        with self.assertRaises(ScreeningRunError):
            complete_screening_run(run.id, task=self.task, model_ids=['test-model'])

        self.user.credit_account.refresh_from_db()
        run.refresh_from_db()
        self.assertEqual(self.user.credit_account.balance, 10)
        self.assertEqual(run.status, ScreeningRun.Status.FAILED)
        self.assertFalse(
            CreditTransaction.objects.filter(
                idempotency_key=f'screening-run:{run.id}:usage',
            ).exists()
        )

    def test_review_list_is_lightweight_and_detail_is_loaded_by_reference(self):
        run = self._completed_run_for_review()
        self.client.force_login(self.user)
        review_step = self.project.stages.get(stage_key='SCREEN_1').steps.get(step_key='review')

        response = self.client.get('/api/review/list/', {
            'project': self.project.id,
            'step': review_step.id,
            'run': run.id,
        })
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload['screening_run_id'], run.id)
        self.assertTrue(payload['is_current'])
        self.assertNotIn('abstract', payload['results'][0])
        self.assertNotIn('multi_model_results', payload['results'][0])

        detail = self.client.get(
            f'/api/review/runs/{run.id}/references/{self.references[0].id}/',
            {'project': self.project.id},
        )
        self.assertEqual(detail.status_code, 200, detail.content)
        self.assertEqual(detail.json()['abstract'], 'Abstract 1')
        self.assertIn('multi_model_results', detail.json())

    def test_review_stats_aggregate_database_results(self):
        run = self._completed_run_for_review()
        self.client.force_login(self.user)

        response = self.client.get('/api/review/stats/', {
            'project': self.project.id,
            'run': run.id,
        })

        self.assertEqual(response.status_code, 200, response.content)
        stats = response.json()
        self.assertEqual(stats['total'], 2)
        self.assertEqual(stats['unreviewed'], 2)
        self.assertEqual(stats['tab_included'], 1)
        self.assertEqual(stats['tab_excluded'], 0)
        self.assertEqual(stats['tab_pending'], 0)
        self.assertEqual(stats['tab_conflict'], 1)
        self.assertEqual(stats['screening_run_id'], run.id)
        self.assertTrue(stats['is_current'])

    def test_review_write_is_run_bound_audited_and_stale_run_is_read_only(self):
        run = self._completed_run_for_review()
        self.client.force_login(self.user)
        review_step = self.project.stages.get(stage_key='SCREEN_1').steps.get(step_key='review')
        url = f'/api/review/runs/{run.id}/references/{self.references[0].id}/'

        response = self.client.patch(url, data={
            'project': self.project.id,
            'step': review_step.id,
            'decision': 'excluded',
            'reason': 'Not eligible',
        }, content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        review = ManualReview.objects.get(screening_run=run, reference=self.references[0])
        self.assertEqual(review.decision, 'excluded')
        audit = ActivityLog.objects.get(operation_type='review_decision')
        self.assertEqual(audit.operation_detail['screening_run_id'], run.id)
        self.assertEqual(audit.operation_detail['reference_id'], self.references[0].id)
        self.assertIsNone(audit.operation_detail['before'])

        note_response = self.client.post(
            f'{url}notes/',
            data={
                'project': self.project.id,
                'step': review_step.id,
                'content': 'Needs a second reviewer',
            },
            content_type='application/json',
        )
        self.assertEqual(note_response.status_code, 200, note_response.content)
        self.assertEqual(
            ActivityLog.objects.filter(operation_type='review_note').count(),
            1,
        )
        notes = self.client.get(f'{url}notes/', {'project': self.project.id})
        self.assertEqual(notes.status_code, 200, notes.content)
        self.assertEqual(notes.json()['notes'][0]['content'], 'Needs a second reviewer')

        ScreeningCorpus.objects.filter(pk=self.corpus.pk).update(revision=2)
        detail = self.client.get(url, {'project': self.project.id})
        self.assertEqual(detail.status_code, 200, detail.content)
        self.assertFalse(detail.json()['is_current'])
        denied = self.client.patch(url, data={
            'project': self.project.id,
            'step': review_step.id,
            'decision': 'included',
            'reason': '',
        }, content_type='application/json')
        self.assertEqual(denied.status_code, 409, denied.content)
        self.assertEqual(denied.json()['error']['code'], 'screening_run_stale')

    def test_review_reference_ids_do_not_cross_project_boundaries(self):
        run = self._completed_run_for_review()
        other = Project.objects.create(name='Other project', owner=self.user)
        initialize_project(other, self.user)
        self.client.force_login(self.user)

        response = self.client.get(
            f'/api/review/runs/{run.id}/references/{self.references[0].id}/',
            {'project': other.id},
        )
        self.assertEqual(response.status_code, 404)

    def test_qa_import_uses_one_current_run_and_persists_source_snapshot(self):
        run = self._completed_run_for_review()
        review_step = self.project.stages.get(stage_key='SCREEN_1').steps.get(step_key='review')
        ManualReview.objects.create(
            project=self.project,
            step=review_step,
            reference=self.references[0],
            screening_run=run,
            ai_decision='included',
            decision='excluded',
            is_override=True,
            reviewer=self.user,
        )
        ManualReview.objects.create(
            project=self.project,
            step=review_step,
            reference=self.references[1],
            screening_run=run,
            ai_decision='conflict',
            decision='included',
            is_override=True,
            reviewer=self.user,
        )
        self.client.force_login(self.user)

        response = self.client.post(
            '/api/qa/refs/import/',
            {'project_id': self.project.id, 'source_stage': 'SCREEN_1'},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()['data']
        self.assertEqual(data['imported'], 1)
        self.assertEqual(data['skipped'], 1)
        self.assertEqual(data['skipped_by_decision'], {'excluded': 1})
        self.assertEqual(data['screening_run_id'], run.id)
        imported = QAReference.objects.get(project=self.project)
        self.assertEqual(imported.source_reference_id, self.references[1].id)
        self.assertEqual(imported.source_screening_run_id, run.id)
        self.assertEqual(imported.source_screening_decision, 'included')
        self.assertEqual(imported.title, self.references[1].title)
        self.assertEqual(imported.abstract, self.references[1].abstract)

    def test_qa_import_rejects_a_stale_completed_run(self):
        self._completed_run_for_review()
        ScreeningCorpus.objects.filter(pk=self.corpus.pk).update(revision=2)
        self.client.force_login(self.user)

        response = self.client.post(
            '/api/qa/refs/import/',
            {'project_id': self.project.id, 'source_stage': 'SCREEN_1'},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()['error']['code'], 'current_screening_run_required')

    def test_handler_reads_corpus_and_writes_only_database_results(self):
        grant_credits(self.user, 10, note='test')
        config = dict(self.task.config)
        config.update({'criteria': ['Include eligible studies'], 'concurrency': 2})
        self.task.config = config
        self.task.save(update_fields=['config'])

        with tempfile.TemporaryDirectory() as temp_dir, override_settings(BASE_DIR=Path(temp_dir)):
            executor = StepExecutor(self.task.id, 'ai_screen', self.project.id)
            executor.config.update(config)
            executor.initialize()
            success = executor.execute()
            executor.finalize(success)

        self.assertTrue(success)
        run = ScreeningRun.objects.get(project=self.project)
        self.assertEqual(run.status, ScreeningRun.Status.COMPLETED)
        self.assertEqual(run.results.count(), 2)
        step = self.project.stages.get(stage_key='SCREEN_1').steps.get(step_key='ai_screen')
        self.assertEqual(step.metadata['stats_version'], 3)
        self.assertFalse(
            DataFile.objects.filter(
                project=self.project,
                metadata__artifact_type='screening_result_json',
            ).exists()
        )
