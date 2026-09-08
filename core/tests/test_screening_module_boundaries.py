"""Long-term contracts for screening module ownership and bulk XML loading."""

import tempfile
from pathlib import Path

from django.test import SimpleTestCase, override_settings

from core.screening.executors.ai_screen_handler import AIScreenHandler
from core.screening.executors.export_handler import ExportHandler
from core.screening.selectors import load_xml_fields_bulk


class ScreeningModuleBoundaryTests(SimpleTestCase):
    LEGACY_SOURCE_PATHS = (
        'core/api/qa_views.py',
        'core/api/review_views.py',
        'core/api/qa_serializers.py',
        'core/api/review_serializers.py',
        'core/executors/handlers/__init__.py',
        'core/executors/parsers/parser.py',
        'core/quality/api/views.py',
        'core/tasks.py',
        'core/views.py',
        'platform_backend/ai_models_config.py',
    )

    def test_legacy_python_entry_points_are_removed(self):
        repository_root = Path(__file__).resolve().parents[2]
        for relative_path in self.LEGACY_SOURCE_PATHS:
            with self.subTest(path=relative_path):
                self.assertFalse((repository_root / relative_path).exists())

    def test_handlers_are_owned_by_screening_module(self):
        self.assertEqual(AIScreenHandler.__module__, 'core.screening.executors.ai_screen_handler')
        self.assertEqual(ExportHandler.__module__, 'core.screening.executors.export_handler')

    def test_bulk_xml_loader_resolves_multiple_records(self):
        xml_template = (
            '<Reference><Title>{title}</Title><Abstract>{abstract}</Abstract>'
            '<Doi>{doi}</Doi><Url>{url}</Url></Reference>'
        )
        with tempfile.TemporaryDirectory() as media_root:
            data_dir = Path(media_root) / 'projects' / 'project_7' / 'parse_1' / 'split_xmls'
            data_dir.mkdir(parents=True)
            (data_dir / '00001_alpha.xml').write_text(
                xml_template.format(title='A', abstract='Abstract A', doi='doi-a', url='url-a'),
                encoding='utf-8',
            )
            (data_dir / '00002_beta.xml').write_text(
                xml_template.format(title='B', abstract='Abstract B', doi='doi-b', url='url-b'),
                encoding='utf-8',
            )
            with override_settings(MEDIA_ROOT=media_root):
                result = load_xml_fields_bulk(
                    ['00001_different_suffix.xml', '00002_beta.xml'], 7,
                )

        self.assertEqual(result['00001_different_suffix.xml']['abstract'], 'Abstract A')
        self.assertEqual(result['00002_beta.xml']['doi'], 'doi-b')
