"""Long-term contracts for screening module ownership and storage boundaries."""

from pathlib import Path

from django.test import SimpleTestCase

from core.screening.executors.ai_screen_handler import AIScreenHandler
from core.screening.executors.export_handler import ExportHandler
from core.step_config import STEP_CONFIGURATIONS


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

    def test_file_backed_screening_adapters_are_removed(self):
        repository_root = Path(__file__).resolve().parents[2]
        for relative_path in (
            'core/screening/services/input_selector.py',
            'core/screening/services/result_repository.py',
            'core/screening/parsers/output.py',
        ):
            with self.subTest(path=relative_path):
                self.assertFalse((repository_root / relative_path).exists())

    def test_step_configuration_does_not_restore_legacy_screening_files(self):
        serialized = repr({
            key: STEP_CONFIGURATIONS[key]
            for key in ('parse', 'dedup', 'ai_screen', 'review', 'export')
        })
        for legacy_path in (
            'references.xml', 'split_xmls', 'dedup_xmls', 'results/*/*.json',
        ):
            with self.subTest(path=legacy_path):
                self.assertNotIn(legacy_path, serialized)
