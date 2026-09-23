"""RIS 和内部 XML 文献文件的解析契约。"""

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from django.test import TestCase

from core.screening.parsers import (
    convert_to_xml,
    iter_directory,
    parse_file,
    supported_extensions,
    write_xml_stream,
)
from core.screening.parsers.registry import get_parser
from core.screening.parsers.diagnostics import build_parse_report
from core.screening.executors.dedup_handler import DedupHandler
from core.screening.executors.parse_handler import ParseHandler


FIXTURES = Path(__file__).parent / 'fixtures'


class ParserFixtureTests(TestCase):
    def test_bibtex_diagnostics_report_silently_skipped_invalid_key(self):
        content = """@article{ValidKey,
title = {Valid title},
abstract = {Present},
}
@article{Invalid Key,
title = {Silently skipped title},
abstract = {Present},
}
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'sample.bib'
            path.write_text(content, encoding='utf-8')
            parsed = parse_file(str(path))
            report = build_parse_report(str(path), parsed)

        self.assertEqual(len(parsed), 1)
        self.assertEqual(report['detected_entries'], 2)
        self.assertEqual(report['parsed_entries'], 1)
        self.assertEqual(report['skipped_entries'], 1)
        self.assertEqual(report['status'], 'partial')
        issue = next(item for item in report['issues'] if item['code'] == 'invalid_citation_key')
        self.assertEqual(issue['position'], 2)
        self.assertEqual(issue['line'], 5)
        self.assertEqual(issue['identifier'], 'Invalid Key')

    def test_diagnostics_count_missing_abstract_without_marking_record_skipped(self):
        content = """TY  - JOUR
TI  - Has abstract
AB  - Abstract text
ER  -
TY  - JOUR
TI  - Missing abstract
ER  -
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'sample.ris'
            path.write_text(content, encoding='utf-8')
            parsed = parse_file(str(path))
            report = build_parse_report(str(path), parsed)

        self.assertEqual(report['detected_entries'], 2)
        self.assertEqual(report['parsed_entries'], 2)
        self.assertEqual(report['skipped_entries'], 0)
        self.assertEqual(report['missing_abstract_entries'], 1)
        self.assertEqual(report['status'], 'warning')
        missing = [item for item in report['issues'] if item['code'] == 'missing_abstract']
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]['position'], 2)

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

    def test_ris_addresses_survive_xml_conversion(self):
        content = """TY  - JOUR
TI  - RIS address example
AD  - Department A, University X
AD  - Department B, Hospital Y
ER  -
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / 'address.ris'
            output_path = Path(temp_dir) / 'address.xml'
            input_path.write_text(content, encoding='utf-8')
            parsed = parse_file(str(input_path))
            convert_to_xml(parsed, str(output_path))
            round_tripped = parse_file(str(output_path))

        expected = 'Department A, University X; Department B, Hospital Y'
        self.assertEqual(parsed[0]['address'], expected)
        self.assertEqual(round_tripped[0]['address'], expected)

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

    def test_ciw_c1_and_rp_addresses_survive_xml_conversion(self):
        content = """PT J
TI C1 address
C1 Department A, University X
C1 Department B, Hospital Y
ER

PT J
TI RP fallback address
RP Corresponding Author, Institute Z
ER
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / 'address.ciw'
            output_path = Path(temp_dir) / 'address.xml'
            input_path.write_text(content, encoding='utf-8')
            parsed = parse_file(str(input_path))
            convert_to_xml(parsed, str(output_path))
            round_tripped = parse_file(str(output_path))

        expected_c1 = 'Department A, University X; Department B, Hospital Y'
        self.assertEqual(parsed[0]['address'], expected_c1)
        self.assertEqual(round_tripped[0]['address'], expected_c1)
        self.assertEqual(parsed[1]['address'], 'Corresponding Author, Institute Z')
        self.assertEqual(round_tripped[1]['address'], 'Corresponding Author, Institute Z')

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

    def test_embase_xml_normalizes_namespaced_fields_and_deduplicates_authors(self):
        path = FIXTURES / 'references' / 'sample_embase.xml'
        parsed = parse_file(str(path))
        report = build_parse_report(str(path), parsed)

        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]['title'], 'Embase diagnostic study')
        self.assertEqual(parsed[0]['authors'], ['Alpha A.', 'Beta B.', 'Gamma C.'])
        self.assertEqual(parsed[0]['journal'], 'Evidence Journal')
        self.assertEqual(parsed[0]['year'], '2026')
        self.assertEqual(parsed[0]['volume'], '12')
        self.assertEqual(parsed[0]['issue'], '3')
        self.assertEqual(parsed[0]['page'], '101')
        self.assertEqual(parsed[0]['date'], '2026-02-08')
        self.assertEqual(parsed[0]['doi'], '10.1000/embase.1')
        self.assertEqual(parsed[0]['source_identifier'], '100001')
        self.assertEqual(parsed[0]['source_type'], 'EMBASE_XML')
        self.assertEqual(parsed[0]['abstract'], 'First abstract paragraph.')
        self.assertEqual(report['detected_entries'], 2)
        self.assertEqual(report['parsed_entries'], 2)
        self.assertEqual(report['skipped_entries'], 0)
        self.assertEqual(report['missing_abstract_entries'], 1)
        self.assertEqual(report['status'], 'warning')
        self.assertEqual(report['issues'][0]['position'], 2)

    def test_parse_handler_generates_outputs_and_matching_diagnostics_for_embase_xml(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_dir = root / 'input'
            output_dir = root / 'output'
            split_dir = root / 'split'
            input_dir.mkdir()
            output_dir.mkdir()
            split_dir.mkdir()
            source = FIXTURES / 'references' / 'sample_embase.xml'
            (input_dir / source.name).write_bytes(source.read_bytes())
            handler = ParseHandler.__new__(ParseHandler)
            handler.logger = MagicMock()
            handler._update_parse_progress = lambda *args, **kwargs: None

            count, merged_path = handler._run_parser(input_dir, output_dir, split_dir)
            split_paths = sorted(split_dir.glob('*.xml'))
            merged = parse_file(str(merged_path))
            dedup_handler = DedupHandler.__new__(DedupHandler)
            dedup_titles = [
                dedup_handler._extract_xml_meta(path)['title'] for path in split_paths
            ]

        self.assertEqual(count, 2)
        self.assertEqual(len(split_paths), 2)
        self.assertEqual([entry['title'] for entry in merged], [
            'Embase diagnostic study',
            'Embase study without abstract',
        ])
        self.assertEqual(dedup_titles, [
            'Embase diagnostic study',
            'Embase study without abstract',
        ])
        self.assertEqual(len(handler._parse_reports), 1)
        self.assertEqual(handler._parse_reports[0]['detected_entries'], 2)
        self.assertEqual(handler._parse_reports[0]['parsed_entries'], 2)

    def test_parse_handler_fails_when_no_usable_records_are_generated(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / 'unsupported.xml'
            source.write_text('<unsupported><entry /></unsupported>', encoding='utf-8')

            handler = ParseHandler.__new__(ParseHandler)
            handler.workspace = root / 'workspace'
            handler.logger = MagicMock()
            handler._get_upload_files = lambda: [SimpleNamespace(
                filename=source.name,
                file=SimpleNamespace(path=str(source)),
            )]
            handler.check_stop_signal = lambda: False
            handler._clear_old_intermediate = MagicMock()
            handler._save_outputs = MagicMock()
            handler._save_parse_reports = MagicMock()
            handler._write_final_stats = MagicMock()
            handler._update_parse_progress = MagicMock()

            success = handler.execute()

        self.assertFalse(success)
        handler._clear_old_intermediate.assert_called_once_with()
        handler._save_outputs.assert_not_called()
        handler._save_parse_reports.assert_called_once()
        self.assertEqual(handler._parse_reports[0]['status'], 'failed')
        self.assertEqual(handler._parse_reports[0]['parsed_entries'], 0)
        self.assertEqual(handler._update_parse_progress.call_args.args[0], 'failed')
        self.assertEqual(handler._write_final_stats.call_args.kwargs['progress_phase'], 'failed')

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
