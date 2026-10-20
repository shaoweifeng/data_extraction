"""文献复筛后端 MVP 回归测试。"""

from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase

from core.models import DataFile, Project, QAReference, RescreenCriteria, RescreenReference
from core.services.project_service import initialize_project


User = get_user_model()


class RescreeningApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('rescreen-user', password='pw')
        self.project = Project.objects.create(name='Rescreen project', owner=self.user)
        initialize_project(self.project, self.user)
        self.review_step = self.project.stages.get(stage_key='SCREEN_1').steps.get(step_key='review')
        self.client = Client()
        self.client.force_login(self.user)

    def test_refs_list_requires_login(self):
        response = Client().get('/api/rescreening/refs/', {'project_id': self.project.id})
        self.assertEqual(response.status_code, 302)

    def _resolved_record(self, ref_id, title, final_decision='included', **extra):
        reference = SimpleNamespace(
            id=ref_id,
            title=title,
            authors=extra.get('authors', []),
            publication_year=extra.get('publication_year', ''),
            journal=extra.get('journal', ''),
            abstract=extra.get('abstract', ''),
            doi=extra.get('doi', ''),
            pmid=extra.get('pmid', ''),
            source_record_key=extra.get('source_record_key', f'{ref_id}.xml'),
            source_identifier=extra.get('source_identifier', ''),
        )
        return SimpleNamespace(reference=reference, final_decision=final_decision)

    def test_import_from_screening_uses_final_included_records(self):
        resolved_records = [
            self._resolved_record(101, 'Human include', 'included'),
            self._resolved_record(102, 'Human exclude', 'excluded'),
            self._resolved_record(103, 'AI include', 'included', authors=['A', 'B']),
        ]

        with patch('core.rescreening.services.current_completed_screening_run', return_value=SimpleNamespace(id=1)), \
             patch('core.rescreening.services.iter_resolved_screening_records', return_value=resolved_records):
            response = self.client.post(
                '/api/rescreening/refs/import/',
                {'project_id': self.project.id, 'source_stage': 'SCREEN_1'},
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        titles = list(RescreenReference.objects.filter(project=self.project).values_list('title', flat=True))
        self.assertEqual(titles, ['Human include', 'AI include'])


    def test_import_from_screening_appends_without_replacing_existing_refs(self):
        existing = RescreenReference.objects.create(
            project=self.project,
            title='Existing manual PDF',
            source_type='pdf_upload',
            fulltext_status='bound',
        )
        resolved_records = [self._resolved_record(201, 'New include', 'included')]

        with patch('core.rescreening.services.current_completed_screening_run', return_value=SimpleNamespace(id=1)), \
             patch('core.rescreening.services.iter_resolved_screening_records', return_value=resolved_records):
            response = self.client.post(
                '/api/rescreening/refs/import/',
                {'project_id': self.project.id, 'source_stage': 'SCREEN_1'},
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['imported'], 1)
        titles = list(RescreenReference.objects.filter(project=self.project).order_by('id').values_list('title', flat=True))
        self.assertEqual(titles, [existing.title, 'New include'])

    def test_upload_bibliography_creates_unbound_references(self):
        ris = b"TY  - JOUR\nTI  - Bibliography title\nAU  - Zhang, San\nPY  - 2024\nJO  - Evidence Journal\nDO  - 10.1000/rescreen\nER  -\n"
        upload = SimpleUploadedFile('refs.ris', ris, content_type='application/x-research-info-systems')
        response = self.client.post('/api/rescreening/refs/upload-bibliography/', {'project_id': self.project.id, 'file': upload})

        self.assertEqual(response.status_code, 201)
        ref = RescreenReference.objects.get(project=self.project)
        self.assertEqual(ref.title, 'Bibliography title')
        self.assertEqual(ref.fulltext_status, 'unbound')
        self.assertEqual(ref.source_type, 'bibliography_upload')

    def test_upload_pdf_creates_bound_reference(self):
        pdf = SimpleUploadedFile('paper.pdf', b'%PDF-1.4\n%%EOF', content_type='application/pdf')
        response = self.client.post('/api/rescreening/fulltexts/upload/', {'project_id': self.project.id, 'files': [pdf]})

        self.assertEqual(response.status_code, 201)
        ref = RescreenReference.objects.get(project=self.project)
        self.assertEqual(ref.fulltext_status, 'bound')
        self.assertEqual(ref.source_type, 'pdf_upload')
        self.assertTrue(ref.fulltext_file_id)

    def test_save_criteria(self):
        response = self.client.post(
            '/api/rescreening/criteria/',
            {'project_id': self.project.id, 'criteria_list': ['纳入 RCT', '排除动物研究']},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        criteria = RescreenCriteria.objects.get(project=self.project)
        self.assertEqual(criteria.criteria_list, ['纳入 RCT', '排除动物研究'])

    def test_excluded_review_requires_reason(self):
        ref = RescreenReference.objects.create(project=self.project, title='待审文献')
        response = self.client.patch(
            f'/api/rescreening/review/{ref.id}/',
            {'human_decision': 'excluded', 'exclusion_reason': ''},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        ref.refresh_from_db()
        self.assertEqual(ref.human_decision, '')

    def test_auto_search_binds_existing_uploaded_pdf_by_title(self):
        target = RescreenReference.objects.create(
            project=self.project,
            title='Exact Matching Study Title',
            source_type='screening_import',
            fulltext_status='unbound',
        )
        pdf = SimpleUploadedFile('matching.pdf', b'%PDF-1.4\n%%EOF', content_type='application/pdf')
        data_file = DataFile.objects.create(
            project=self.project,
            filename='matching.pdf',
            file=pdf,
            created_by=self.user,
        )
        RescreenReference.objects.create(
            project=self.project,
            title='Exact Matching Study Title',
            source_type='pdf_upload',
            fulltext_status='bound',
            fulltext_file=data_file,
        )

        response = self.client.post(
            '/api/rescreening/fulltexts/auto-search/',
            {'project_id': self.project.id},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['bound'], 1)
        target.refresh_from_db()
        self.assertEqual(target.fulltext_status, 'bound')
        self.assertEqual(target.fulltext_file_id, data_file.id)
        self.assertEqual(target.fulltext_source, 'local_upload')
        self.assertEqual(target.fulltext_resolver, 'local_pdf')

    def test_auto_search_marks_bind_failed_when_no_open_pdf_found(self):
        from core.rescreening.fulltext_resolvers.base import ResolveResult

        class FakeNotFoundResolver:
            name = 'fake_not_found'

            def resolve(self, ref):
                return ResolveResult(False, self.name, 'not_found', '未找到开放 PDF')

        target = RescreenReference.objects.create(
            project=self.project,
            title='No OA PDF paper',
            doi='10.1000/no-oa-pdf',
            fulltext_status='unbound',
        )

        with patch('core.rescreening.fulltext_resolvers.pipeline.default_resolvers', return_value=[FakeNotFoundResolver()]):
            response = self.client.post(
                '/api/rescreening/fulltexts/auto-search/',
                {'project_id': self.project.id, 'ref_ids': [target.id]},
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['failed'], 1)
        target.refresh_from_db()
        self.assertEqual(target.fulltext_status, 'bind_failed')
        self.assertTrue(target.fulltext_attempts)
        self.assertIn('PDF', target.fulltext_error)

    def test_auto_search_external_resolver_downloads_and_records_source(self):
        from core.rescreening.fulltext_resolvers.base import ResolveResult
        from core.rescreening.fulltext_resolvers.pipeline import auto_bind_fulltexts_with_resolvers

        class FakeResolver:
            name = 'fake_oa'

            def resolve(self, ref):
                return ResolveResult(
                    found=True,
                    resolver=self.name,
                    status='downloaded',
                    message='测试开放全文命中',
                    source='fake_open_access',
                    source_url='https://example.org/paper.pdf',
                    license='cc-by',
                    filename='fake-paper.pdf',
                    content=b'%PDF-1.4\n%%EOF',
                )

        target = RescreenReference.objects.create(
            project=self.project,
            title='External OA PDF paper',
            doi='10.1000/external-oa',
            fulltext_status='unbound',
        )

        result = auto_bind_fulltexts_with_resolvers(self.project, ref_ids=[target.id], user=self.user, resolvers=[FakeResolver()])

        self.assertEqual(result['bound'], 1)
        target.refresh_from_db()
        self.assertEqual(target.fulltext_status, 'bound')
        self.assertEqual(target.fulltext_source, 'fake_open_access')
        self.assertEqual(target.fulltext_resolver, 'fake_oa')
        self.assertEqual(target.fulltext_license, 'cc-by')
        self.assertTrue(target.fulltext_file_id)
        self.assertTrue(target.fulltext_attempts)

    def test_refs_list_returns_online_lookup_url(self):
        RescreenReference.objects.create(
            project=self.project,
            title='Lookup paper',
            doi='10.1000/example.doi',
            fulltext_status='unbound',
        )

        response = self.client.get('/api/rescreening/refs/', {'project_id': self.project.id})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data'][0]['fulltext_lookup_url'], 'https://doi.org/10.1000/example.doi')

    def test_ai_start_requires_criteria(self):
        pdf = SimpleUploadedFile('paper.pdf', b'%PDF-1.4\n%%EOF', content_type='application/pdf')
        data_file = DataFile.objects.create(
            project=self.project,
            filename='paper.pdf',
            file=pdf,
            created_by=self.user,
        )
        RescreenReference.objects.create(
            project=self.project,
            title='No criteria',
            fulltext_status='bound',
            fulltext_file=data_file,
        )

        response = self.client.post(
            '/api/rescreening/ai/start/',
            {'project_id': self.project.id},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('复筛纳排标准', response.json()['error'])

    def test_ai_start_dispatches_rescreen_task_and_marks_fulltext_states(self):
        RescreenCriteria.objects.create(project=self.project, criteria_list=['纳入 RCT', '排除动物研究'])
        pdf = SimpleUploadedFile('paper.pdf', b'%PDF-1.4\n%%EOF', content_type='application/pdf')
        data_file = DataFile.objects.create(
            project=self.project,
            filename='paper.pdf',
            file=pdf,
            created_by=self.user,
        )
        bound = RescreenReference.objects.create(
            project=self.project,
            title='Bound paper',
            fulltext_status='bound',
            fulltext_file=data_file,
        )
        unbound = RescreenReference.objects.create(
            project=self.project,
            title='Unbound paper',
            fulltext_status='unbound',
        )

        with patch('core.services.start_task', return_value=SimpleNamespace(id=123)) as mocked_start:
            response = self.client.post(
                '/api/rescreening/ai/start/',
                {'project_id': self.project.id, 'ai_models': ['deepseek']},
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['task_id'], 123)
        mocked_start.assert_called_once()
        _, step_key, config, _ = mocked_start.call_args.args
        self.assertEqual(step_key, 'rescreen_ai')
        self.assertEqual(config['ref_ids'], [bound.id])
        bound.refresh_from_db()
        unbound.refresh_from_db()
        self.assertEqual(bound.ai_status, 'queued')
        self.assertEqual(unbound.ai_status, 'skipped_unbound')

    def test_quality_import_from_rescreening_uses_human_included_and_keeps_pdf(self):
        pdf = SimpleUploadedFile('included.pdf', b'%PDF-1.4\n%%EOF', content_type='application/pdf')
        data_file = DataFile.objects.create(
            project=self.project,
            filename='included.pdf',
            file=pdf,
            created_by=self.user,
        )
        included = RescreenReference.objects.create(
            project=self.project,
            title='Included after rescreen',
            first_author='Wang',
            year=2024,
            journal='Evidence Journal',
            doi='10.1000/included',
            human_decision='included',
            fulltext_status='bound',
            fulltext_file=data_file,
        )
        RescreenReference.objects.create(
            project=self.project,
            title='Excluded after rescreen',
            human_decision='excluded',
        )

        from core.quality.services.reference_service import rebuild_from_screening
        result = rebuild_from_screening(self.project, 'SCREEN_2')

        self.assertEqual(result['imported'], 1)
        self.assertEqual(result['skipped'], 1)
        self.assertEqual(result['source_stage'], 'SCREEN_2')
        qa_ref = QAReference.objects.get(project=self.project)
        self.assertEqual(qa_ref.title, included.title)
        self.assertEqual(qa_ref.source_type, 'screening_import')
        self.assertEqual(qa_ref.source_screening_decision, 'included')
        self.assertEqual(qa_ref.fulltext_file_id, data_file.id)
        self.assertEqual(qa_ref.fulltext_status, 'available')

    def test_batch_include_only_ai_consistent_included(self):
        eligible = RescreenReference.objects.create(
            project=self.project,
            title='可一键纳入',
            fulltext_status='bound',
            ai_status='completed',
            ai_decision='included',
            consensus_status='consistent',
        )
        RescreenReference.objects.create(
            project=self.project,
            title='AI 排除',
            fulltext_status='bound',
            ai_status='completed',
            ai_decision='excluded',
            consensus_status='consistent',
        )
        RescreenReference.objects.create(
            project=self.project,
            title='存在分歧',
            fulltext_status='bound',
            ai_status='completed',
            ai_decision='included',
            consensus_status='divergent',
        )

        response = self.client.post(
            '/api/rescreening/review/batch-include/',
            {'project_id': self.project.id},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['updated'], 1)
        eligible.refresh_from_db()
        self.assertEqual(eligible.human_decision, 'included')
        self.assertEqual(RescreenReference.objects.filter(project=self.project, human_decision='').count(), 2)
