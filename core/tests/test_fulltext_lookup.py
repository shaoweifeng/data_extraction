"""Durable local/open-access lookup with mocked third parties, never real API costs."""
from unittest.mock import patch, Mock
from django.test import override_settings
from core.fulltext.errors import FulltextError
from core.rescreening.errors import RescreenError
from core.fulltext.resolvers import europe_pmc, unpaywall
from core.fulltext.network import NetworkBudget
from core.models import Task
from core.rescreening.models import RescreenReference, FulltextLookupJob, FulltextCandidate
from core.rescreening.services.fulltext_fetch import process_lookup
from core.rescreening.services.fulltext_lookup import start_lookup, confirm_candidate
from core.rescreening.services.imports import start_import
from core.rescreening.services.processing import process_import
from core.tests.test_shared_fulltext import SharedFulltextFixture
from core.tests.test_qa_fulltext import make_pdf
from core.tests.test_screening_imports import ris_file
from core.tests.test_fulltext_network import FakeResponse


class FulltextLookupTests(SharedFulltextFixture):
    def setUp(self):
        super().setUp()
        batch = start_import(project=self.project, user=self.user, idempotency_key='source', uploads=[ris_file()])
        process_import(batch.pk)
        Task.objects.filter(pk=batch.task_id).update(status='completed')
        self.ref = RescreenReference.objects.get()
        self.ref.doi = '10.1234/study'
        self.ref.save(update_fields=['doi'])

    def start(self, **changes):
        return start_lookup(**dict(dict(project=self.project, user=self.user, ids=[self.ref.pk],
            mode='local', idempotency_key='lookup'), **changes))

    def candidate(self, **changes):
        return dict(dict(source='unpaywall', url='https://source.example/study.pdf', title='Study',
            doi=self.ref.doi, pmid='', license='cc-by', confidence='identifier', provenance={}), **changes)

    def test_local_exact_identifier_can_bind_and_versions_are_updated(self):
        asset, _ = self.ready(make_pdf(text='DOI: 10.1234/study research methods'))
        job = self.start(auto_bind=True)
        process_lookup(job.pk)
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.current_binding.asset_id, asset.pk)
        self.assertEqual(self.ref.input_version, 2)
        self.assertEqual(self.ref.raw_metadata_versions.count(), 2)
        self.assertEqual(job.items.get().candidates.get().status, 'bound')

    def test_multiple_matching_pdfs_require_manual_confirmation(self):
        self.ready(make_pdf(text='DOI: 10.1234/study Version one'))
        self.ready(make_pdf(text='DOI: 10.1234/study Version two'))
        job = self.start(auto_bind=True)
        process_lookup(job.pk)
        self.ref.refresh_from_db()
        self.assertIsNone(self.ref.current_binding_id)
        self.assertEqual(job.items.get().candidates.count(), 2)
        candidate = job.items.get().candidates.first()
        ref = confirm_candidate(candidate=candidate, user=self.user, expected_version=1)
        self.assertEqual(ref.current_binding.asset_id, candidate.asset_id)
        with self.assertRaisesMessage(FulltextError, '已变化'):
            confirm_candidate(candidate=candidate, user=self.user, expected_version=1)

    def test_external_default_is_off_and_local_does_not_make_network_calls(self):
        with self.assertRaisesMessage(FulltextError, '尚未启用'):
            self.start(mode='online')
        job = self.start()
        with patch('core.fulltext.network._open_pinned') as opened:
            process_lookup(job.pk)
        opened.assert_not_called()
        self.assertEqual(job.items.get().status, 'not_found')

    def test_job_idempotency_and_account_concurrency(self):
        job = self.start()
        self.assertEqual(self.start().pk, job.pk)
        with self.assertRaisesMessage(RescreenError, '活动任务'):
            self.start(idempotency_key='another')
        with self.assertRaisesMessage(FulltextError, '幂等键'):
            self.start(auto_bind=True)

    def test_cancel_never_downloads_or_binds(self):
        job = self.start()
        with self.assertRaisesMessage(FulltextError, '停止'):
            process_lookup(job.pk, check_stop=lambda: True)
        job.refresh_from_db()
        self.assertEqual(job.status, 'cancelled')
        self.assertEqual(FulltextCandidate.objects.count(), 0)
        self.ref.refresh_from_db()
        self.assertIsNone(self.ref.current_binding_id)

    @override_settings(FULLTEXT_LOOKUP_ENABLED=True)
    def test_open_pdf_download_scans_extracts_and_only_then_auto_binds(self):
        body = make_pdf(text='DOI: 10.1234/study Methods and Results')
        job = self.start(mode='online', download=True, auto_bind=True)
        with (patch('core.rescreening.services.fulltext_fetch.europe_pmc', return_value=([self.candidate()], '')),
                patch('core.rescreening.services.fulltext_fetch.unpaywall', return_value=([], 'email_not_configured')),
                patch('core.fulltext.network._open_pinned', return_value=(Mock(), FakeResponse(body,
                    headers={'Content-Type': 'application/pdf', 'Content-Length': str(len(body))})))):
            process_lookup(job.pk)
        self.ref.refresh_from_db()
        self.assertIsNotNone(self.ref.current_binding_id)
        self.assertEqual(self.ref.current_binding.asset.status, 'ready')
        job.refresh_from_db()
        self.assertEqual(job.received_bytes, len(body))
        self.assertEqual(job.request_count, 1)

    @override_settings(FULLTEXT_LOOKUP_ENABLED=True)
    def test_missing_license_offers_link_but_never_downloads(self):
        job = self.start(mode='online', download=True, auto_bind=True)
        with (patch('core.rescreening.services.fulltext_fetch.europe_pmc', return_value=([self.candidate(license='')], '')),
                patch('core.rescreening.services.fulltext_fetch.unpaywall', return_value=([], '')),
                patch('core.fulltext.network._open_pinned') as opened):
            process_lookup(job.pk)
        opened.assert_not_called()
        self.assertEqual(job.items.get().candidates.get().error_code, 'license_not_allowed')

    @override_settings(FULLTEXT_LOOKUP_ENABLED=True)
    def test_wrong_downloaded_identifier_is_never_auto_bound(self):
        body = make_pdf(text='DOI: 10.1234/different A different study')
        job = self.start(mode='online', download=True, auto_bind=True)
        with (patch('core.rescreening.services.fulltext_fetch.europe_pmc', return_value=([self.candidate()], '')),
                patch('core.rescreening.services.fulltext_fetch.unpaywall', return_value=([], '')),
                patch('core.fulltext.network._open_pinned', return_value=(Mock(), FakeResponse(body)))):
            process_lookup(job.pk)
        self.ref.refresh_from_db()
        self.assertIsNone(self.ref.current_binding_id)
        self.assertEqual(job.items.get().candidates.get().confidence, 'conflict')

    @override_settings(FULLTEXT_LOOKUP_ENABLED=True, FULLTEXT_LOOKUP_DAILY_BYTES=100)
    def test_daily_bytes_and_reference_count_limits(self):
        FulltextLookupJob.objects.create(project=self.project, created_by=self.user, mode='online',
            status='completed', idempotency_key='prior', request_hash='x', input_revision=1, received_bytes=100)
        with self.assertRaisesMessage(FulltextError, '今日'):
            self.start(mode='online')
        with self.assertRaisesMessage(FulltextError, '数量'):
            self.start(ids=[self.ref.pk]*51)

    def test_lookup_apis_are_paginated_and_isolated(self):
        self.ready(make_pdf(text='DOI: 10.1234/study original'))
        job = self.start()
        process_lookup(job.pk)
        response = self.client.get(f'/api/rescreening/lookups/{job.pk}/items/', {'page_size': 1})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['total'], 1)
        self.assertNotIn('bibliography_snapshot', str(response.json()))
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(f'/api/rescreening/lookups/{job.pk}/').status_code, 404)

    def test_resolvers_check_identity_oa_license_and_missing_credentials(self):
        cap = NetworkBudget(5, 10000, 2, 5, 2)
        result = {'doi': self.ref.doi, 'source': 'MED', 'id': '123', 'isOpenAccess': 'Y',
            'title': 'A Study', 'license': 'cc-by', 'fullTextUrlList': {'fullTextUrl': [
                {'documentStyle': 'pdf', 'availabilityCode': 'OA', 'url': 'https://source.example/a.pdf'}]}}
        with patch('core.fulltext.resolvers.fetch_json', return_value={'resultList': {'result': [result]}}):
            found, _ = europe_pmc({'doi': self.ref.doi}, budget=cap, max_json_bytes=1000, limit=5)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['license'], 'cc-by')
        with patch('core.fulltext.resolvers.fetch_json') as fetch:
            self.assertEqual(unpaywall({'doi': self.ref.doi}, budget=cap, max_json_bytes=1000, limit=5, email=''),
                             ([], 'email_not_configured'))
            fetch.assert_not_called()

    def test_manual_link_is_persisted_without_network_or_background_task(self):
        with patch('core.fulltext.network._open_pinned') as opened:
            job = self.start(mode='manual', manual_url='https://source.example/article?id=1')
        opened.assert_not_called()
        self.assertEqual(job.status, 'completed')
        self.assertIsNone(job.task_id)
        self.assertEqual(job.items.get().candidates.get().source, 'manual_link')

    def test_real_lookup_task_and_cancellation_endpoint(self):
        from core.executors.celery_tasks import execute_async_step
        job = self.start()
        result = execute_async_step.apply(args=[job.task_id, 'rescreen_fetch', self.project.pk], throw=True)
        self.assertTrue(result.result)
        job.refresh_from_db()
        self.assertEqual(job.status, 'completed')
        second = self.start(idempotency_key='second')
        response = self.client.post(f'/api/rescreening/lookups/{second.pk}/cancel/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['status'], 'cancelled')
        response = self.client.post(f'/api/rescreening/lookups/{second.pk}/retry/')
        self.assertEqual(response.status_code, 202, response.content)
        self.assertNotEqual(response.json()['data']['id'], second.pk)

    @override_settings(FULLTEXT_LOOKUP_ENABLED=True)
    def test_failed_download_counts_bytes_but_keeps_no_partial_file(self):
        job = self.start(mode='online', download=True)
        with (patch('core.rescreening.services.fulltext_fetch.europe_pmc', return_value=([self.candidate()], '')),
                patch('core.rescreening.services.fulltext_fetch.unpaywall', return_value=([], '')),
                patch('core.fulltext.network._open_pinned', return_value=(Mock(), FakeResponse(b'<html>login page</html>')))):
            process_lookup(job.pk)
        job.refresh_from_db()
        self.assertGreater(job.received_bytes, 0)
        self.assertEqual(job.items.get().status, 'failed')
        from core.fulltext.models import FulltextAsset
        self.assertEqual(FulltextAsset.objects.count(), 0)

    @override_settings(FULLTEXT_LOOKUP_ENABLED=True)
    def test_explicit_candidate_download_is_visible_in_its_new_job(self):
        original = self.start(mode='online')
        with (patch('core.rescreening.services.fulltext_fetch.europe_pmc', return_value=([self.candidate()], '')),
              patch('core.rescreening.services.fulltext_fetch.unpaywall', return_value=([], ''))):
            process_lookup(original.pk)
        Task.objects.filter(pk=original.task_id).update(status='completed')
        candidate = original.items.get().candidates.get()
        download = self.start(mode='download', candidate_id=candidate.pk, idempotency_key='download')
        body = make_pdf(text='DOI: 10.1234/study Confirmed full text')
        with patch('core.fulltext.network._open_pinned', return_value=(Mock(), FakeResponse(body))):
            process_lookup(download.pk)
        new_candidate = download.items.get().candidates.get()
        self.assertIsNotNone(new_candidate.asset_id)
        self.assertEqual(new_candidate.provenance['origin_candidate_id'], candidate.pk)
