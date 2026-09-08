"""AI 初筛模型运行器回归测试。"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from core.screening.services.model_runner import ScreeningModelRunner


class _Handler:
    def __init__(self, model_ids):
        self.config = {'ai_models': model_ids}
        self.logger = Mock()

    def _get_prompt_template(self):
        return '{screening_criteria}'

    def _mock_extracted_fields(self):
        return {}


class ScreeningModelRunnerTests(SimpleTestCase):
    entry = {
        'title': 'Example',
        'authors': 'Author',
        'year': '2025',
        'journal': 'Journal',
        'source_xml': '00001_example.xml',
    }

    @patch('core.screening.services.model_runner.time.sleep', return_value=None)
    def test_mock_results_include_a_timestamp(self, _sleep):
        runner = ScreeningModelRunner(_Handler(['missing-model']))

        results = runner._mock_api_call([self.entry], ['criterion'])

        self.assertEqual(len(results), 1)
        datetime.fromisoformat(results[0]['timestamp'])

    @patch('core.ai.providers.provider_is_configured', return_value=True)
    @patch('core.ai.providers.get_provider')
    def test_configured_model_results_include_a_timestamp(self, get_provider, _configured):
        provider = Mock()
        provider.screen_batch.return_value = [SimpleNamespace(
            decision='included',
            exclusion_reason='',
            exclusion_criterion_no='',
            token_usage={'prompt': 3, 'completion': 2, 'total': 5},
            error='',
            extracted_fields={},
        )]
        get_provider.return_value = provider
        runner = ScreeningModelRunner(_Handler(['deepseek']))

        results = runner._call_multi_model_api([self.entry], ['criterion'], concurrency=1)

        self.assertEqual(results[0]['decision'], 'included')
        self.assertEqual(results[0]['token_usage']['total'], 5)
        datetime.fromisoformat(results[0]['timestamp'])
