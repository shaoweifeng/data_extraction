"""初筛结果的 RIS 和 Excel 导出契约。"""

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import openpyxl
import xml.etree.ElementTree as ET
from django.test import TestCase

from core.screening.executors.export_handler import ExportHandler


FIXTURES = Path(__file__).parent / 'fixtures'


class ScreeningExportGoldenTests(TestCase):
    def make_handler(self, workspace):
        executor = SimpleNamespace(
            logger=MagicMock(),
            workspace=Path(workspace),
            project_obj=MagicMock(),
            task_obj=None,
            step_obj=MagicMock(),
            stage_obj=MagicMock(),
            project_id=1,
            config={},
        )
        return ExportHandler(executor)

    def test_ris_output_matches_golden_file(self):
        result = {
            'title': 'Golden Study',
            'authors': ['Zhang, San', 'Li, Si'],
            'year': '2024',
            'journal': 'Evidence Journal',
            'volume': '12',
            'issue': '3',
            'page': '101-109',
            'doi': '10.1000/golden',
            'abstract': 'Golden abstract',
            'url': 'https://example.org/golden',
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            handler = self.make_handler(temp_dir)
            path = handler._generate_ris([result], 'golden', 'fixed')
            actual = path.read_text(encoding='utf-8')
        expected = (FIXTURES / 'golden' / 'screening_included.ris').read_text(encoding='utf-8')
        self.assertEqual(actual, expected)

    def test_xml_export_escapes_values_and_keeps_decision_semantics(self):
        from core.screening.exporters.xml import ScreeningXmlExporter

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'results.xml'
            with path.open('w', encoding='utf-8') as output:
                ScreeningXmlExporter.write_header(output)
                ScreeningXmlExporter.write_record(
                    output,
                    {
                        'reference_id': 17,
                        '_export_manual_review': SimpleNamespace(is_override=True),
                        'extracted_fields': {'人群': '成人 & 儿童'},
                    },
                    {'Title': 'A < B & C', 'Abstract': '结构化摘要'},
                    'included',
                )
                ScreeningXmlExporter.write_footer(output)

            root = ET.parse(path).getroot()
        reference = root.find('Reference')
        self.assertEqual(reference.attrib, {
            'id': '17', 'decision': 'included', 'manual_override': 'yes',
        })
        self.assertEqual(reference.findtext('Title'), 'A < B & C')
        self.assertEqual(reference.find("./ExtractedFields/Field[@name='人群']").text, '成人 & 儿童')

    def test_excel_rows_match_semantic_golden(self):
        results = [
            {
                'reference_id': 1,
                'title': 'Excluded Study',
                'include_or_not': 'yes',
            },
            {
                'reference_id': 2,
                'title': 'Included Study',
                'decision': 'included',
                'exclusion_reason': 'must be cleared',
                'number_exclusion_reason': '9',
            },
        ]
        manual_reviews = {
            1: SimpleNamespace(
                decision='excluded',
                reason='Wrong population',
                is_override=True,
            )
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            handler = self.make_handler(temp_dir)
            with patch.object(handler, '_load_extraction_field_names', return_value=[]):
                path = handler._generate_excel(
                    results,
                    'all',
                    'golden',
                    'fixed',
                    manual_reviews,
                    ['Adults only', 'Wrong population'],
                )
            workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
            sheet = workbook.active
            rows = sheet.iter_rows(values_only=True)
            headers = list(next(rows))
            selected = []
            keys = ['include_or_not', 'manual_override', 'exclusion_reason_id', 'exclusion_reason', 'Title']
            for row in rows:
                record = dict(zip(headers, row))
                selected.append({key: record[key] for key in keys})
            workbook.close()

        expected = json.loads((FIXTURES / 'golden' / 'screening_excel_rows.json').read_text(encoding='utf-8'))
        self.assertEqual(selected, expected)

    def test_excel_marks_waived_conflict_in_existing_columns(self):
        result = {
            'reference_id': 3,
            'title': 'Conflicting Study',
            'decision': 'excluded',
            'consensus': 'conflict',
            'multi_model_results': [
                {
                    'model_name': 'Model Include',
                    'decision': 'included',
                    'reason': '符合纳入标准',
                },
                {
                    'model_name': 'Model Exclude',
                    'decision': 'excluded',
                    'reason_id': '2',
                    'reason': '研究人群不符',
                },
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            handler = self.make_handler(temp_dir)
            with patch.object(handler, '_load_extraction_field_names', return_value=[]):
                path = handler._generate_excel(
                    [result], 'all', 'golden', 'conflict', {}, [],
                )
            workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
            rows = workbook.active.iter_rows(values_only=True)
            headers = list(next(rows))
            record = dict(zip(headers, next(rows)))
            workbook.close()

        self.assertEqual(record['include_or_not'], 'conflict')
        self.assertIsNone(record['exclusion_reason_id'])
        self.assertIn('AI模型存在分歧', record['exclusion_reason'])
        self.assertIn('已豁免导出', record['exclusion_reason'])
        self.assertIn('Model Include：纳入；理由：符合纳入标准', record['exclusion_reason'])
        self.assertIn('Model Exclude：排除（排除标准 2）；理由：研究人群不符', record['exclusion_reason'])

    def test_ris_marks_waived_conflict_as_note(self):
        result = {
            'title': 'Conflicting RIS Study',
            '_export_final_decision': 'conflict',
            'multi_model_results': [
                {'model_name': 'Model A', 'decision': 'included', 'reason': '符合标准'},
                {'model_name': 'Model B', 'decision': 'excluded', 'reason': '人群不符'},
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            handler = self.make_handler(temp_dir)
            path = handler._generate_ris([result], 'golden', 'conflict')
            content = path.read_text(encoding='utf-8')

        self.assertIn('TI  - Conflicting RIS Study', content)
        self.assertIn('N1  - AI模型存在分歧', content)
        self.assertIn('Model A：纳入；理由：符合标准', content)
        self.assertIn('Model B：排除；理由：人群不符', content)

    def test_ris_only_conflict_is_not_written_to_included_excel(self):
        result = {
            'title': 'RIS Only Conflict',
            'consensus': 'conflict',
            '_export_final_decision': 'conflict',
            '_export_include_excel': False,
            '_export_xml_fields': {},
        }
        callback = MagicMock()
        with tempfile.TemporaryDirectory() as temp_dir:
            handler = self.make_handler(temp_dir)
            with patch.object(handler, '_load_extraction_field_names', return_value=[]):
                path = handler._generate_excel(
                    [result], 'included', 'golden', 'ris-only', {}, [],
                    on_record=callback,
                )
            workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
            rows = list(workbook.active.iter_rows(values_only=True))
            workbook.close()

        self.assertEqual(len(rows), 1)  # 仅表头
        callback.assert_called_once()
