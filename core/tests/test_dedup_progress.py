"""Deduplication progress reporting contracts."""

from django.test import SimpleTestCase

from core.screening.executors.dedup_handler import phase_percentage


class DedupProgressTests(SimpleTestCase):
    def test_each_phase_maps_into_its_overall_progress_range(self):
        self.assertEqual(phase_percentage(0, 4739, 0, 15), 0)
        self.assertEqual(phase_percentage(4739, 4739, 0, 15), 15)
        self.assertEqual(phase_percentage(50, 100, 15, 55), 35)
        self.assertEqual(phase_percentage(100, 100, 55, 70), 70)
        self.assertEqual(phase_percentage(100, 100, 70, 99), 99)
        self.assertEqual(phase_percentage(1, 1, 99, 100), 100)

    def test_empty_phase_is_treated_as_complete(self):
        self.assertEqual(phase_percentage(0, 0, 55, 70), 70)
