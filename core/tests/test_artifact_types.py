"""Stable artifact type contracts used across screening and quality modules."""

from django.test import SimpleTestCase

from core.artifacts.types import ArtifactType


class ArtifactTypeTests(SimpleTestCase):
    def test_screening_artifact_types_are_stable_and_unique(self):
        values = [
            ArtifactType.SCREENING_PARSE_REPORT_JSON,
            ArtifactType.SCREENING_DEDUP_REPORT_JSON,
            ArtifactType.SCREENING_EXPORT_XLSX,
            ArtifactType.SCREENING_EXPORT_RIS,
            ArtifactType.SCREENING_EXPORT_XML,
        ]
        self.assertEqual(len(values), len(set(values)))
        self.assertTrue(all(value.startswith('screening_') for value in values))

    def test_single_record_file_artifacts_are_not_part_of_the_runtime_catalog(self):
        self.assertFalse(hasattr(ArtifactType, 'SCREENING_PARSED_REFERENCE_XML'))
        self.assertFalse(hasattr(ArtifactType, 'SCREENING_DEDUP_REFERENCE_XML'))
        self.assertFalse(hasattr(ArtifactType, 'SCREENING_RESULT_JSON'))
