import hashlib
import json

from django.test import SimpleTestCase

from core.quality.services.fulltext_chunks import (
    CHUNKING_VERSION,
    EVIDENCE_SPAN_MAX_CHARS,
    PageText,
    build_chunks,
    serialize_chunks,
)


class QAFulltextChunkTests(SimpleTestCase):
    def test_chunks_preserve_pages_sections_and_are_deterministic(self):
        pages = [
            PageText(1, 'Abstract\n\nA concise abstract.\n\nIntroduction\n\nBackground text.'),
            PageText(2, 'Methods\n\nConsecutive patients were enrolled. ' * 8),
            PageText(3, 'Results\n\nThe primary result was reported. ' * 8),
        ]
        first = build_chunks(pages, target_tokens=40, overlap_tokens=5)
        second = build_chunks(pages, target_tokens=40, overlap_tokens=5)

        self.assertEqual(first, second)
        self.assertTrue(first)
        self.assertTrue(all(1 <= item['page_start'] <= item['page_end'] <= 3 for item in first))
        self.assertIn('methods', {item['section'] for item in first})
        self.assertIn('results', {item['section'] for item in first})
        self.assertEqual(
            hashlib.sha256(serialize_chunks(first)).hexdigest(),
            hashlib.sha256(serialize_chunks(second)).hexdigest(),
        )

    def test_serialized_chunks_are_json_lines(self):
        chunks = build_chunks(
            [PageText(21, 'Methods\n\nA method found after page twenty.')],
            target_tokens=100,
            overlap_tokens=10,
        )
        payload = serialize_chunks(chunks).decode('utf-8')
        decoded = [json.loads(line) for line in payload.splitlines()]

        self.assertEqual(decoded[0]['page_start'], 21)
        self.assertEqual(decoded[0]['section'], 'methods')
        self.assertIn('after page twenty', decoded[0]['text'])

    def test_invalid_overlap_is_rejected(self):
        with self.assertRaises(ValueError):
            build_chunks([PageText(1, 'text')], target_tokens=10, overlap_tokens=10)

    def test_v2_spans_are_deterministic_page_bound_and_exact(self):
        pages = [
            PageText(3, 'Methods\n\n' + ('连续纳入符合标准的患者，并记录检测结果。' * 35)),
            PageText(4, 'Results\n\n' + ('All participants received the reference standard. ' * 20)),
        ]
        first = build_chunks(pages, target_tokens=120, overlap_tokens=20)
        second = build_chunks(pages, target_tokens=120, overlap_tokens=20)

        self.assertEqual(CHUNKING_VERSION, 'qa-chunks-v2-spans')
        self.assertEqual(first, second)
        span_fingerprints = {}
        for chunk in first:
            self.assertIn('evidence_spans', chunk)
            for span in chunk['evidence_spans']:
                self.assertGreater(len(span['text']), 0)
                self.assertLessEqual(len(span['text']), EVIDENCE_SPAN_MAX_CHARS)
                self.assertGreaterEqual(span['page_number'], chunk['page_start'])
                self.assertLessEqual(span['page_number'], chunk['page_end'])
                self.assertIn(span['text'], chunk['text'])
                self.assertEqual(
                    hashlib.sha256(span['text'].encode('utf-8')).hexdigest(),
                    span['sha256'],
                )
                fingerprint = (
                    span['page_number'], span['section'], span['sha256'], span['text'],
                )
                self.assertIn(fingerprint, {span_fingerprints.setdefault(span['span_id'], fingerprint)})

        self.assertTrue(span_fingerprints)
        self.assertTrue(all(
            span_id.startswith(f'p{fingerprint[0]:04d}-s')
            for span_id, fingerprint in span_fingerprints.items()
        ))
