"""Stable artifact type contracts used across screening and quality modules."""

from django.test import SimpleTestCase

from core.artifacts.types import ArtifactType


class ArtifactTypeTests(SimpleTestCase):
    def test_screening_artifact_types_are_stable_and_unique(self):
        values = [
            ArtifactType.SCREENING_PARSED_REFERENCES_XML,
            ArtifactType.SCREENING_PARSED_REFERENCE_XML,
            ArtifactType.SCREENING_DEDUP_REFERENCE_XML,
            ArtifactType.SCREENING_DEDUP_REPORT_JSON,
            ArtifactType.SCREENING_RESULT_JSON,
            ArtifactType.SCREENING_EXPORT_XLSX,
            ArtifactType.SCREENING_EXPORT_RIS,
        ]
        self.assertEqual(len(values), len(set(values)))
        self.assertTrue(all(value.startswith('screening_') for value in values))
