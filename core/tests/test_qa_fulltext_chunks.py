import hashlib
import json

from django.test import SimpleTestCase

from core.quality.services.fulltext_chunks import (
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
