"""Conservative PDF hints, versioned publication, and immutable historical inputs."""
from io import StringIO
from io import BytesIO
from types import SimpleNamespace
from django.core.management import call_command
from django.test import SimpleTestCase
from core.fulltext.bibliography import extract_bibliography, bibliography_from_asset
from core.rescreening.services.pdf_bibliography import enrich_pdf_references
from core.tests.test_shared_fulltext import SharedFulltextFixture
from core.tests.test_qa_fulltext import make_pdf


CHINESE_HEADER = '2017年\n临床急诊杂志\n18卷4期\n研究题目\n雷娟娟1 冯慧玲1 齐延平2\n摘要: 2015年收集病例'


class PDFBibliographyTests(SimpleTestCase):
    def test_chinese_publication_header_and_author_row(self):
        result = extract_bibliography({'author': 'CNKI', 'creationDate': 'D:20260101'}, CHINESE_HEADER)
        self.assertEqual(result['fields'], {'authors': ['雷娟娟', '冯慧玲', '齐延平'],
                                          'publication_year': '2017', 'journal': '临床急诊杂志'})
        self.assertEqual(result['sources']['journal']['page'], 1)

    def test_fullwidth_text_and_footer_header(self):
        text = '陈若虹\n１，胡敏\n１，任亚萍\n１，段欣欣\n２(单位)\n摘要: 病例\n临床检验杂志２０１６年４月第３４卷第４期'
        fields = extract_bibliography({}, text)['fields']
        self.assertEqual(fields['authors'], ['陈若虹', '胡敏', '任亚萍', '段欣欣'])
        self.assertEqual(fields['publication_year'], '2016')

    def test_publisher_subject_and_author_need_first_page_corroboration(self):
        metadata = {'author': 'Mona Kandil', 'subject': 'Brazilian Journal of Microbiology , Corrected proof. doi:example'}
        text = ('Please\n cite this article in press as: Kandil M, et al. A study. Braz J Microbiol. (2018), https://doi.org/example\n'
                'b r a z i l i a n j o u r n a l o f m i c r o b i o l o g y\nMona\n Kandil\na b s t r a c t')
        fields = extract_bibliography(metadata, text)['fields']
        self.assertEqual(fields['authors'], ['Mona Kandil'])
        self.assertEqual(fields['publication_year'], '2018')
        self.assertEqual(fields['journal'], 'Brazilian Journal of Microbiology')
        self.assertEqual(extract_bibliography(metadata, 'Different article')['fields'], {})

    def test_software_properties_study_dates_and_empty_scan_are_not_bibliography(self):
        for name in ['CNKI', 'Microsoft Administrator', 'Adobe Reader', 'Unknown Author', 'University Hospital']:
            fields = extract_bibliography({'author': name, 'creationDate': 'D:20170101'},
                f'{name}\nAbstract: enrolled patients during 2015. Received 2016. Accepted 2017. ©2018')['fields']
            self.assertEqual(fields, {})
        self.assertEqual(extract_bibliography({}, '')['fields'], {})

    def test_backfill_does_not_treat_later_pages_as_the_first_page(self):
        class TextFile:
            def open(self, mode):
                return BytesIO(('<<<QA_PAGE:3>>>\n' + CHINESE_HEADER).encode())
        self.assertEqual(bibliography_from_asset(SimpleNamespace(metadata={}, extracted_text_file=TextFile()))['fields'], {})


class PDFBibliographyPersistenceTests(SharedFulltextFixture):
    def body(self):
        # Latin text avoids depending on an installed CJK font in generated PDFs.
        import fitz
        with fitz.open(stream=make_pdf(text='Mona Kandil\nBrazilian Journal of Microbiology\n'
                'Please cite this article as: A study. Braz J Microbiol. (2018), doi:test'), filetype='pdf') as doc:
            doc.set_metadata({'author': 'Mona Kandil', 'subject': 'Brazilian Journal of Microbiology , Corrected proof'})
            return doc.tobytes()

    def test_processing_fills_only_pdf_references_and_is_idempotent(self):
        asset, refs = self.ready(self.body(), references=True)
        ref = refs[0]
        ref.refresh_from_db()
        self.assertEqual(ref.authors, ['Mona Kandil'])
        self.assertEqual(ref.publication_year, '2018')
        self.assertEqual(ref.journal, 'Brazilian Journal of Microbiology')
        self.assertEqual(ref.title, 'study')
        self.assertEqual(ref.input_version, 2)
        self.assertEqual(ref.raw_metadata_versions.count(), 2)
        self.assertEqual(ref.current_binding.input_version, 2)
        old = ref.raw_metadata_versions.get(input_version=1)
        self.assertNotIn('_pdf_bibliography', old.raw_fields)
        self.assertIn('_pdf_bibliography', ref.raw_metadata_versions.get(input_version=2).raw_fields)
        self.assertEqual(enrich_pdf_references(asset, asset.metadata['bibliography']), [])
        self.assertEqual(enrich_pdf_references(asset, {'version': 'test', 'fields': {'authors': ['Other Person']}}), [])
        # Existing review responses/export readers use the actual persisted fields.
        data = self.client.get(f'/api/rescreening/references/{ref.pk}/review/').data['data']
        self.assertEqual(data['bibliography']['authors'], ['Mona Kandil'])
        self.assertEqual(data['publication_year'], '2018')

    def test_late_creation_from_ready_asset_also_enriches(self):
        body = self.body()
        asset, _ = self.ready(body)
        _, refs = self.upload(body, references=True)
        self.assertEqual(refs[0].publication_year, '2018')
        self.assertEqual(refs[0].current_binding.asset_id, asset.pk)

    def test_backfill_is_preview_by_default_and_preserves_human_history(self):
        from core.rescreening.services.workspace import save_review, workspace_state
        asset, refs = self.ready(references=True)
        ref = refs[0]
        review = save_review(project=self.project, user=self.user, reference_id=ref.pk, input_version=1,
            expected_version=0, criteria_revision_id=None, suggestion_id=None, suggestion_revision=0, decision='included')
        bibliography = extract_bibliography({}, CHINESE_HEADER)
        changes = enrich_pdf_references(asset, bibliography, apply=False)
        self.assertEqual(len(changes), 1)
        ref.refresh_from_db()
        self.assertEqual(ref.authors, [])
        enrich_pdf_references(asset, bibliography)
        ref.refresh_from_db()
        self.assertEqual(ref.current_review_id, review.pk)
        self.assertEqual(ref.current_review.input_version, 1)
        self.assertEqual(ref.input_version, 2)
        self.assertEqual(workspace_state(self.project, self.user)['counts']['needs_reconfirmation'], 1)
        output = StringIO()
        call_command('backfill_rescreen_pdf_bibliography', project_id=self.project.pk, stdout=output)
        self.assertIn('预览', output.getvalue())
        self.assertEqual(bibliography_from_asset(asset)['fields'], {})

    def test_index_bibliography_is_not_enriched_from_pdf_properties(self):
        asset, refs = self.ready(references=True)
        ref = refs[0]
        batch = ref.import_batch
        batch.source_type = 'bibliography'
        batch.save(update_fields=['source_type'])
        self.assertEqual(enrich_pdf_references(asset, extract_bibliography({}, CHINESE_HEADER)), [])
        ref.refresh_from_db()
        self.assertEqual(ref.input_version, 1)
        self.assertEqual(ref.authors, [])

    def test_active_run_blocks_bibliography_changes(self):
        from core.models import Task
        from core.rescreening.errors import RescreenError
        asset, refs = self.ready(references=True)
        Task.objects.create(project=self.project, task_type='rescreen_ai', status='running')
        with self.assertRaisesMessage(RescreenError, '活动任务'):
            enrich_pdf_references(asset, extract_bibliography({}, CHINESE_HEADER))
        refs[0].refresh_from_db()
        self.assertEqual(refs[0].input_version, 1)
