from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase

from core.quality.domain.methods import (
    ai_supported_method_keys,
    get_all_methods_meta,
    get_method_config,
    method_supports_ai,
    validate_method_config,
)
from core.quality.domain.methods.schema import MethodConfigError, aggregate_judgments
from core.quality.api.serializers import QABatchMethodInputSerializer, QARefUpdateInputSerializer


class QualityMethodConfigContractTests(SimpleTestCase):
    def test_all_registered_configs_are_valid_and_metadata_explains_ai_state(self):
        metadata = get_all_methods_meta()
        self.assertEqual({item['key'] for item in metadata}, {
            'QUADAS2', 'NOS', 'ROB2', 'AMSTAR2', 'ROBINS_I',
        })
        for item in metadata:
            self.assertTrue(item['config_version'])
            self.assertTrue(item['evaluation_strategy'])
            if not item['ai_supported']:
                self.assertTrue(item['ai_unavailable_reason'])

    def test_ai_supported_keys_are_derived_from_validated_configs(self):
        self.assertEqual(ai_supported_method_keys(), frozenset({'QUADAS2', 'NOS'}))
        self.assertTrue(method_supports_ai('QUADAS2'))
        self.assertFalse(method_supports_ai('ROB2'))
        self.assertFalse(method_supports_ai('UNKNOWN'))

    def test_quadas2_retrieval_contract_is_complete(self):
        config = get_method_config('QUADAS2')
        self.assertEqual(config['aggregation_policy'], 'quadas2_v1')
        for item in config['signal_items']:
            self.assertTrue(item['retrieval']['queries'])
            self.assertTrue(item['retrieval']['preferred_sections'])
            self.assertGreater(item['retrieval']['max_chunks'], 0)
            self.assertTrue(item['evidence_required'])

    def test_nos_variants_select_distinct_domains_and_questions(self):
        cohort = get_method_config('NOS', 'cohort')
        case_control = get_method_config('NOS', 'case_control')
        self.assertEqual(cohort['variant_name'], '队列研究')
        self.assertEqual(case_control['variant_name'], '病例对照研究')
        self.assertEqual(cohort['domains'][-1]['key'], 'outcome')
        self.assertEqual(case_control['domains'][-1]['key'], 'exposure')
        self.assertTrue(all(item['signal_key'].startswith('cohort_') for item in cohort['signal_items']))
        self.assertTrue(all(item['signal_key'].startswith('cc_') for item in case_control['signal_items']))
        self.assertEqual(get_method_config('NOS')['variant_key'], 'cohort')

    def test_unknown_nos_variant_is_rejected(self):
        with self.assertRaisesRegex(ValueError, '未知的 NOS 研究设计'):
            get_method_config('NOS', 'cross_sectional')

    def test_validator_rejects_duplicate_signal_key(self):
        invalid = get_method_config('QUADAS2')
        invalid['signal_items'][1]['signal_key'] = invalid['signal_items'][0]['signal_key']
        with self.assertRaisesRegex(MethodConfigError, '重复信号问题 key'):
            validate_method_config(invalid, registry_key='QUADAS2')

    def test_validator_rejects_invalid_domain_empty_options_and_missing_retrieval(self):
        cases = []
        invalid_domain = get_method_config('QUADAS2')
        invalid_domain['signal_items'][0]['domain'] = 'missing'
        cases.append((invalid_domain, '未知领域'))
        empty_options = get_method_config('QUADAS2')
        empty_options['signal_items'][0]['options'] = []
        cases.append((empty_options, 'options'))
        no_retrieval = get_method_config('QUADAS2')
        no_retrieval['signal_items'][0].pop('retrieval')
        cases.append((no_retrieval, 'retrieval'))
        for config, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(MethodConfigError, message):
                    validate_method_config(config, registry_key='QUADAS2')

    def test_aggregation_policies_have_fixed_examples(self):
        self.assertEqual(aggregate_judgments('quadas2_v1', 'bias_risk', ['是', '否']), 'high')
        self.assertEqual(aggregate_judgments('quadas2_v1', 'applicability', ['低', '高']), 'high')
        self.assertEqual(aggregate_judgments('nos_v1', 'bias_risk', ['★ 是', '✗ 否']), 'high')
        self.assertEqual(aggregate_judgments('nos_v1', 'bias_risk', ['★ 是']), 'low')

    def test_management_command_reports_success(self):
        output = StringIO()
        call_command('check_qa_method_configs', stdout=output)
        self.assertIn('全部 5 种方法配置校验通过', output.getvalue())

    def test_api_contract_accepts_nos_variant_and_rejects_unknown_variant(self):
        valid = QABatchMethodInputSerializer(data={
            'ref_ids': [1, 2],
            'quality_method': 'NOS',
            'quality_method_variant': 'case_control',
        })
        self.assertTrue(valid.is_valid(), valid.errors)

        invalid = QARefUpdateInputSerializer(data={
            'quality_method': 'NOS',
            'quality_method_variant': 'cross_sectional',
        })
        self.assertFalse(invalid.is_valid())
        self.assertIn('quality_method_variant', invalid.errors)
