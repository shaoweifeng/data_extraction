"""Access-control and response contracts for QA evidence context and audit APIs."""

import tempfile
from unittest.mock import patch

import fitz
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings

from core.models import Project, QAReference, QASignalItem
from core.quality.services.evidence_retrieval import load_verified_chunks
from core.quality.services.fulltext import process_fulltext_asset


User = get_user_model()


def evidence_pdf():
    document = fitz.open()
    texts = [
        'Introduction and background information. ' * 30,
        'Participants were enrolled as a consecutive series at the study hospital. ' * 30,
        'Results and discussion of diagnostic accuracy. ' * 30,
    ]
    for index, text in enumerate(texts, 1):
        page = document.new_page()
        page.insert_textbox((50, 50, 540, 780), f'PAGE {index}\n{text}', fontsize=9)
    payload = document.tobytes()
    document.close()
    return payload


class QAEvidenceContextApiTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings = override_settings(
            QA_FULLTEXT_UPLOAD_ROOT=self.temp_dir.name,
            QA_FULLTEXT_MAX_FILE_BYTES=5 * 1024 * 1024,
            QA_FULLTEXT_MAX_TOTAL_BYTES=5 * 1024 * 1024,
            QA_FULLTEXT_MAX_PAGES=10,
            QA_PDF_TEXT_MAX_CHARS=100000,
            QA_CHUNK_TARGET_TOKENS=100,
            QA_CHUNK_OVERLAP_TOKENS=10,
            QA_FULLTEXT_REQUIRE_CLEAN_SCAN=False,
        )
        self.settings.enable()
        self.user = User.objects.create_user('evidence-owner', password='pw')
        self.outsider = User.objects.create_user('evidence-outsider', password='pw')
        self.admin = User.objects.create_user('evidence-admin', password='pw')
        self.admin.profile.role = 'admin'
        self.admin.profile.save(update_fields=['role'])
        self.project = Project.objects.create(name='Evidence context', owner=self.user)
        self.client = Client()
        self.client.force_login(self.user)
        with patch('core.quality.tasks.parse_qa_pdf_meta.delay'):
            upload = self.client.post('/api/qa/refs/upload/', {
                'project_id': self.project.id,
                'files': [SimpleUploadedFile('evidence.pdf', evidence_pdf(), content_type='application/pdf')],
            })
        self.ref = QAReference.objects.get(pk=upload.json()['data']['refs'][0]['id'])
        self.ref.quality_method = 'QUADAS2'
        self.ref.save(update_fields=['quality_method'])
        process_fulltext_asset(self.ref.fulltext_asset.id)
        self.ref.refresh_from_db()
        chunks = load_verified_chunks(self.ref.fulltext_asset)
        self.cited = chunks[len(chunks) // 2]
        self.other = next(chunk for chunk in chunks if chunk['chunk_id'] != self.cited['chunk_id'])
        self.item = QASignalItem.objects.create(
            qa_ref=self.ref,
            quality_method='QUADAS2',
            domain='patient_selection',
            result_type='bias_risk',
            signal_key='ps_consecutive',
            signal_question='Was a consecutive sample enrolled?',
            options=['是', '否', '不清楚'],
            ai_judgment='是',
            ai_evidence='Participants were enrolled as a consecutive series',
            ai_evidence_page=f"第{self.cited['page_start']}页",
            model_results=[{
                'model_id': 'model-a',
                'model_name': 'Model A',
                'judgment': '是',
                'reason': 'Reported directly.',
                'evidence': 'Participants were enrolled as a consecutive series',
                'evidence_page': f"第{self.cited['page_start']}页",
                'evidence_chunk_id': self.cited['chunk_id'],
                'evidence_page_start': self.cited['page_start'],
                'evidence_page_end': self.cited['page_end'],
                'evidence_section': self.cited['section'],
                'evidence_sha256': self.cited['sha256'],
                'prompt_version': 'qa-evidence-prompt-v1',
                'retrieval_version': 'qa-evidence-lexical-v1',
                'method_config_version': 'test-v1',
                'evidence_snapshot_sha256': 'a' * 64,
                'validation_status': 'verified',
                'validation_errors': [],
            }],
        )

    def tearDown(self):
        self.settings.disable()
        self.temp_dir.cleanup()

    def context_url(self, chunk_id=None):
        return f'/api/qa/signal-items/{self.item.id}/evidence-context/?chunk_id={chunk_id or self.cited["chunk_id"]}&model_id=model-a'

    def test_owner_reads_only_bounded_cited_context(self):
        response = self.client.get(self.context_url())
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertLessEqual(len(data['chunks']), 3)
        self.assertEqual(sum(chunk['is_cited'] for chunk in data['chunks']), 1)
        self.assertTrue(all(len(chunk['text']) <= 2400 for chunk in data['chunks']))

    def test_arbitrary_chunk_and_other_project_user_are_hidden(self):
        self.assertEqual(self.client.get(self.context_url(self.other['chunk_id'])).status_code, 404)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.context_url()).status_code, 404)

    def test_regular_response_hides_audit_hashes_but_admin_receives_them(self):
        regular = self.client.get('/api/qa/signal-items/', {'qa_ref_id': self.ref.id})
        result = regular.json()['data'][0]['model_results'][0]
        self.assertNotIn('evidence_sha256', result)
        self.assertNotIn('validation_errors', result)

        self.client.force_login(self.admin)
        admin = self.client.get('/api/qa/signal-items/', {'qa_ref_id': self.ref.id})
        result = admin.json()['data'][0]['model_results'][0]
        self.assertEqual(result['evidence_sha256'], self.cited['sha256'])
        self.assertIn('prompt_version', result)

    def test_audit_is_admin_only_and_reports_asset_versions(self):
        url = f'/api/qa/eval/audit/?qa_ref_id={self.ref.id}'
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.admin)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertEqual(data['asset']['chunk_count'], self.ref.fulltext_asset.chunk_count)
        self.assertEqual(data['evidence_versions'][0]['prompt_version'], 'qa-evidence-prompt-v1')

    def test_deleted_asset_makes_context_unavailable(self):
        self.ref.fulltext_asset.delete()
        self.assertEqual(self.client.get(self.context_url()).status_code, 404)
