"""RIS 和内部 XML 文献文件的解析契约。"""

import tempfile
from pathlib import Path

from django.test import TestCase

from core.screening.parsers import (
    convert_to_xml,
    iter_directory,
    parse_file,
    supported_extensions,
    write_xml_stream,
)
from core.screening.parsers.registry import get_parser
from core.screening.executors.parse_handler import ParseHandler


FIXTURES = Path(__file__).parent / 'fixtures'


class ParserFixtureTests(TestCase):
    def test_registry_exposes_all_supported_extensions(self):
        self.assertEqual(
            supported_extensions(),
            ['.bib', '.bibtex', '.ciw', '.doc', '.docx', '.enw', '.medline', '.nbib', '.ris', '.txt', '.xml'],
        )
        self.assertEqual(get_parser('example.ris').__module__, 'core.screening.parsers.ris')
        self.assertEqual(get_parser('example.xml').__module__, 'core.screening.parsers.xml')

    def test_registry_rejects_unsupported_extension(self):
        with self.assertRaisesMessage(ValueError, '不支持的文件格式: .pdf'):
            get_parser('example.pdf')

    def test_ris_fixture_normalizes_core_fields(self):
        result = parse_file(str(FIXTURES / 'references' / 'sample.ris'))
        self.assertEqual(len(result), 1)
        self.assertEqual(
            {key: result[0][key] for key in ('title', 'authors', 'journal', 'year', 'page', 'doi', 'url', 'source_type')},
            {
                'title': 'Diagnostic accuracy of Example Test',
                'authors': ['Zhang, San', 'Li, Si'],
                'journal': 'Journal of Evidence',
                'year': '2024',
                'page': '101-109',
                'doi': '10.1000/example.1',
                'url': 'https://example.org/article',
                'source_type': 'RIS',
            },
        )

    def test_internal_xml_fixture_normalizes_core_fields(self):
        result = parse_file(str(FIXTURES / 'references' / 'sample.xml'))
        self.assertEqual(len(result), 1)
        self.assertEqual(
            {key: result[0][key] for key in ('title', 'authors', 'journal', 'year', 'doi', 'url', 'type')},
            {
                'title': 'Internal XML Example',
                'authors': ['Wang, Wu', 'Zhao, Liu'],
                'journal': 'Clinical Evidence',
                'year': '2023',
                'doi': '10.1000/example.2',
                'url': 'https://example.org/xml',
                'type': 'XML',
            },
        )

    def test_generated_xml_is_single_pass_and_can_be_parsed_again(self):
        def entries():
            yield {
                'title': 'Round trip',
                'authors': ['Zhang, San', 'Li, Si'],
                'year': '2025',
                'doi': '10.1000/round-trip',
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / 'round-trip.xml'
            convert_to_xml(entries(), str(output_path))
            parsed = parse_file(str(output_path))

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]['title'], 'Round trip')
        self.assertEqual(parsed[0]['authors'], ['Zhang, San', 'Li, Si'])
        self.assertEqual(parsed[0]['doi'], '10.1000/round-trip')

    def test_nbib_is_parsed_in_one_pass_without_losing_record_boundaries(self):
        content = """PMID- 1001
TI  - First title
FAU - Zhang, San
FAU - Li, Si
AB  - First abstract
      continued text
DP  - 2025 Jan

PMID- 1002
TI  - Second title
AU  - Wang W
DP  - 2024
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'sample.nbib'
            path.write_text(content, encoding='utf-8')
            parsed = parse_file(str(path))

        self.assertEqual([item['title'] for item in parsed], ['First title', 'Second title'])
        self.assertEqual(parsed[0]['authors'], ['Zhang, San', 'Li, Si'])
        self.assertEqual(parsed[0]['abstract'], 'First abstract continued text')
        self.assertEqual(parsed[0]['year'], '2025')
        self.assertEqual(parsed[1]['url'], 'https://pubmed.ncbi.nlm.nih.gov/1002')

    def test_ciw_normalizes_records_as_the_stream_is_consumed(self):
        content = """PT J
AU Zhang S
TI First title
AB First line
  continued text
PY 2025
ER

PT J
AU Wang W
TI Second title
DI 10.1000/example
ER
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'sample.ciw'
            path.write_text(content, encoding='utf-8')
            parsed = parse_file(str(path))

        self.assertEqual([item['title'] for item in parsed], ['First title', 'Second title'])
        self.assertEqual(parsed[0]['abstract'], 'First line continued text')
        self.assertEqual(parsed[0]['source_position'], 1)
        self.assertEqual(parsed[1]['url'], 'https://doi.org/10.1000/example')

    def test_endnote_xml_stream_parser_preserves_nested_fields(self):
        content = """<?xml version="1.0" encoding="UTF-8"?>
<xml><records><record>
  <rec-number>7</rec-number><ref-type name="Journal Article" />
  <contributors><authors><author>Zhang, San</author></authors></contributors>
  <titles><title>EndNote title</title><secondary-title>Example Journal</secondary-title></titles>
  <dates><year>2025</year></dates><electronic-resource-num>doi:10.1000/endnote.</electronic-resource-num>
</record></records></xml>"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'endnote.xml'
            path.write_text(content, encoding='utf-8')
            parsed = parse_file(str(path))

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]['title'], 'EndNote title')
        self.assertEqual(parsed[0]['authors'], ['Zhang, San'])
        self.assertEqual(parsed[0]['year'], '2025')
        self.assertEqual(parsed[0]['doi'], '10.1000/endnote')

    def test_directory_and_output_pipeline_visits_each_record_once(self):
        ris = """TY  - JOUR
TI  - First
ER  -
TY  - JOUR
TI  - Second
ER  -
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir) / 'input'
            input_dir.mkdir()
            (input_dir / 'sample.ris').write_text(ris, encoding='utf-8')
            output_path = Path(temp_dir) / 'merged.xml'
            visited = []

            count = write_xml_stream(
                iter_directory(str(input_dir)),
                str(output_path),
                on_entry=lambda entry, position: visited.append((position, entry['title'])),
            )
            parsed = parse_file(str(output_path))

        self.assertEqual(count, 2)
        self.assertEqual(visited, [(1, 'First'), (2, 'Second')])
        self.assertEqual([entry['title'] for entry in parsed], ['First', 'Second'])

    def test_parse_handler_writes_merged_and_split_outputs_in_one_pass(self):
        ris = """TY  - JOUR
TI  - First
ER  -
TY  - JOUR
TI  - Second
ER  -
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_dir = root / 'input'
            output_dir = root / 'output'
            split_dir = root / 'split'
            input_dir.mkdir()
            output_dir.mkdir()
            split_dir.mkdir()
            (input_dir / 'sample.ris').write_text(ris, encoding='utf-8')
            handler = ParseHandler.__new__(ParseHandler)
            handler._update_parse_progress = lambda *args, **kwargs: None

            count, merged_path = handler._run_parser(input_dir, output_dir, split_dir)
            split_paths = sorted(split_dir.glob('*.xml'))
            merged = parse_file(str(merged_path))

        self.assertEqual(count, 2)
        self.assertEqual(len(split_paths), 2)
        self.assertEqual([entry['title'] for entry in merged], ['First', 'Second'])

    def test_parse_handler_uses_fallback_filename_when_ris_title_is_missing(self):
        ris = """TY  - JOUR
TI  - First
ER  -
TY  - JOUR
JO  - Journal Without Title
ER  -
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_dir = root / 'input'
            output_dir = root / 'output'
            split_dir = root / 'split'
            input_dir.mkdir()
            output_dir.mkdir()
            split_dir.mkdir()
            (input_dir / 'missing-title.ris').write_text(ris, encoding='utf-8')
            handler = ParseHandler.__new__(ParseHandler)
            handler._update_parse_progress = lambda *args, **kwargs: None

            count, merged_path = handler._run_parser(input_dir, output_dir, split_dir)
            split_names = sorted(path.name for path in split_dir.glob('*.xml'))
            merged = parse_file(str(merged_path))

        self.assertEqual(count, 2)
        self.assertEqual(len(split_names), 2)
        self.assertTrue(any(name.startswith('00002_unknown_2_') for name in split_names))
        self.assertEqual([entry['title'] for entry in merged], ['First', ''])
