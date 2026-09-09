"""AI model catalog compatibility tests."""

from django.test import SimpleTestCase

from core.services.ai_models_config import get_model_config, get_models_for_frontend


class AIModelCatalogTests(SimpleTestCase):
    def test_deepseek_v4_flash_is_the_default_model(self):
        providers = {item['id']: item for item in get_models_for_frontend()}
        defaults = [
            item['id']
            for item in providers['deepseek']['sub_models']
            if item['is_default']
        ]

        self.assertEqual(defaults, ['deepseek-v4-flash'])

    def test_frontend_exposes_qwen37_models(self):
        providers = {item['id']: item for item in get_models_for_frontend()}
        model_ids = [item['id'] for item in providers['qwen']['sub_models']]

        self.assertEqual(
            model_ids,
            ['qwen3-7-flash', 'qwen3-7-plus', 'qwen3-7-max'],
        )
        self.assertFalse(any(model_id.startswith('qwen3-6-') for model_id in model_ids))

    def test_legacy_qwen36_ids_route_to_corresponding_qwen37_models(self):
        expected = {
            'qwen3-6-flash': ('qwen3-7-flash', 'qwen3.7-flash'),
            'qwen3-6-plus': ('qwen3-7-plus', 'qwen3.7-plus'),
            'qwen3-6-max-preview': ('qwen3-7-max', 'qwen3.7-max'),
        }

        for legacy_id, (config_id, api_model) in expected.items():
            with self.subTest(legacy_id=legacy_id):
                config = get_model_config(legacy_id)
                self.assertEqual(config['id'], config_id)
                self.assertEqual(config['model'], api_model)

    def test_all_frontend_models_expose_thinking_control(self):
        for provider in get_models_for_frontend():
            for model in provider['sub_models']:
                with self.subTest(model_id=model['id']):
                    self.assertTrue(get_model_config(model['id'])['is_reasoning'])

    def test_frontend_exposes_latest_low_cost_doubao_model(self):
        providers = {item['id']: item for item in get_models_for_frontend()}
        models = providers['doubao']['sub_models']

        self.assertEqual(
            [item['id'] for item in models],
            ['doubao-seed-2-1-turbo'],
        )
        self.assertEqual(
            [item['id'] for item in models if item['is_default']],
            ['doubao-seed-2-1-turbo'],
        )
        self.assertFalse(any(item['id'].startswith('seedance-') for item in models))

    def test_legacy_doubao_ids_route_to_current_low_cost_models(self):
        expected = {
            'doubao-seed-1.8': 'doubao-seed-2-1-turbo-260628',
            'doubao-seed-2.0-lite': 'doubao-seed-2-1-turbo-260628',
            'seedance-1.6-flash': 'doubao-seed-2-1-turbo-260628',
            'seedance-2.0-mini': 'doubao-seed-2-1-turbo-260628',
        }

        for legacy_id, api_model in expected.items():
            with self.subTest(legacy_id=legacy_id):
                self.assertEqual(get_model_config(legacy_id)['model'], api_model)
