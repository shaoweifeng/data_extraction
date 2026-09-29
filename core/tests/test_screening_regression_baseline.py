"""Regression contract backed by the real samples under meta_project/."""

import json
import unittest
from pathlib import Path

from django.test import SimpleTestCase

from core.screening.parsers.common import REFERENCE_RECORD_FIELDS
from core.screening.regression_baseline import build_regression_baseline


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_ROOT = REPOSITORY_ROOT / 'meta_project'
BASELINE_PATH = Path(__file__).parent / 'fixtures/regression/meta_project_baseline.json'


class ScreeningRegressionBaselineTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not (SAMPLE_ROOT / 'Screen_input').is_dir() or not (SAMPLE_ROOT / 'QA_input').is_dir():
            raise unittest.SkipTest('meta_project 回归样本未安装')
        cls.actual = build_regression_baseline(SAMPLE_ROOT)
        cls.expected = json.loads(BASELINE_PATH.read_text(encoding='utf-8'))

    def test_real_samples_match_checked_in_baseline(self):
        self.assertEqual(self.actual, self.expected)

    def test_parser_output_fields_are_declared_in_reference_contract(self):
        observed = {
            field
            for item in self.actual['screening']
            for field in item['populated_fields']
        }
        self.assertEqual(observed - REFERENCE_RECORD_FIELDS, set())

    def test_baseline_covers_parse_diagnostics_and_deduplication(self):
        aggregate = self.actual['aggregate']
        self.assertGreater(aggregate['parsed_entries'], 0)
        self.assertGreater(aggregate['duplicate_groups'], 0)
        self.assertTrue(any(item['issue_codes'] for item in self.actual['screening']))
