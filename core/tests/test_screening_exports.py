"""初筛结果的 RIS 和 Excel 导出契约。"""

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import openpyxl
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

    def test_excel_rows_match_semantic_golden(self):
        results = [
            {
                'source_xml': 'excluded.xml',
                'title': 'Excluded Study',
                'include_or_not': 'yes',
            },
            {
                'source_xml': 'included.xml',
                'title': 'Included Study',
                'decision': 'included',
                'exclusion_reason': 'must be cleared',
                'number_exclusion_reason': '9',
            },
        ]
        manual_reviews = {
            'excluded.xml': SimpleNamespace(
                decision='excluded',
                reason='Wrong population',
                is_override=True,
            )
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            handler = self.make_handler(temp_dir)
            with patch.object(handler, '_load_xml_fields', return_value={}), patch.object(
                handler, '_load_extraction_field_names', return_value=[]
            ):
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
