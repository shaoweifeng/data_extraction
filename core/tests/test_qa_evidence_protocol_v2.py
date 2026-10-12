"""Deterministic contracts for the reference-by-ID QA evidence protocol."""

import hashlib

from django.test import SimpleTestCase

from core.quality.services.evidence_protocol_v2 import (
    NEEDS_REVIEW_REASON,
    build_needs_review_fallback,
    build_v2_prompt,
    validate_v2_results,
)


def package():
    text = 'Consecutive participants were enrolled at the study hospital.'
    span = {
        'span_id': 'p0003-s0001-abcdef12',
        'page_number': 3,
        'section': 'methods',
        'char_count': len(text),
        'sha256': hashlib.sha256(text.encode()).hexdigest(),
        'text': text,
    }
    return {
        'domain': 'patient_selection',
        'domain_name': '患者选择',
        'reference': {'title': 'Study', 'first_author': 'Author', 'year': 2025},
        'signal_items': [{
            'signal_key': 'ps_consecutive',
            'signal_question': '是否连续入组？',
            'signal_description': '判断是否连续或随机抽样。',
            'options': ['是', '否', '不清楚'],
            'result_type': 'bias_risk',
        }, {
            'signal_key': 'ps_applicability',
            'signal_question': '人群是否匹配？',
            'signal_description': '与系统评价目标人群比较。',
            'options': ['低', '高', '不清楚'],
            'result_type': 'applicability',
        }],
        'selected_chunks': [{
            'chunk_id': 'p0003-p0003-c0001',
            'evidence_spans': [span],
        }],
        'signal_coverage': {
            'ps_consecutive': ['p0003-p0003-c0001'],
            'ps_applicability': [],
        },
    }


class QAEvidenceProtocolV2Tests(SimpleTestCase):
    def test_prompt_uses_short_refs_and_does_not_request_quote_or_page(self):
        prompt, snapshot = build_v2_prompt(package(), 'QUADAS-2')
        self.assertIn('[E001]', prompt)
        self.assertIn('evidence_refs', prompt)
        self.assertNotIn('evidence_page', prompt)
        self.assertEqual(snapshot['catalog'][0]['page_number'], 3)

    def test_server_resolves_exact_text_and_page(self):
        current = package()
        _, snapshot = build_v2_prompt(current, 'QUADAS-2')
        parsed = [{
            'signal_key': 'ps_consecutive',
            'judgment': '是',
            'reason': '明确连续入组。',
            'evidence_refs': ['E001'],
        }, {
            'signal_key': 'ps_applicability',
            'judgment': '不清楚',
            'reason': '未提供系统评价上下文。',
            'evidence_refs': [],
        }]
        valid, errors = validate_v2_results(parsed, current, snapshot)
        self.assertEqual(errors, [])
        evidence = valid[0]['resolved_evidence'][0]
        self.assertEqual(evidence['page_number'], 3)
        self.assertEqual(
            evidence['text'], 'Consecutive participants were enrolled at the study hospital.',
        )

    def test_unknown_and_cross_signal_refs_fail_closed(self):
        current = package()
        _, snapshot = build_v2_prompt(current, 'QUADAS-2')
        invalid = [{
            'signal_key': 'ps_applicability',
            'judgment': '低',
            'reason': '猜测匹配。',
            'evidence_refs': ['E001'],
        }]
        valid, errors = validate_v2_results(invalid, current, snapshot)
        self.assertEqual(valid, [])
        error = next(item for item in errors if item['code'] == 'evidence_ref_not_allowed')
        self.assertEqual(error['disallowed_refs'], ['E001'])
        self.assertEqual(error['allowed_refs'], [])

    def test_protocol_error_fallback_is_not_a_valid_ai_judgment(self):
        signal = package()['signal_items'][0]
        fallback = build_needs_review_fallback(signal, [{
            'code': 'evidence_ref_not_allowed',
            'signal_key': signal['signal_key'],
            'returned_refs': ['E999'],
            'allowed_refs': ['E001'],
        }])
        self.assertEqual(fallback['validation_status'], 'needs_review')
        self.assertEqual(fallback['judgment'], '')
        self.assertEqual(fallback['resolved_evidence'], [])
        self.assertEqual(fallback['evidence_refs'], ['E999'])
        self.assertEqual(fallback['reason'], NEEDS_REVIEW_REASON)
        self.assertEqual(
            fallback['validation_errors'][0]['allowed_refs'], ['E001'],
        )
