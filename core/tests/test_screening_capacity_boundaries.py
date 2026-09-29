"""Stage 12 deterministic capacity and hostile-input boundary contracts."""

import io
import json
import zipfile
from dataclasses import replace

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from core.screening.parsers.validation import (
    ReferenceRecordValidationError,
    validate_reference_record,
)
from core.screening.services.import_errors import ScreeningImportError
from core.screening.services.import_limits import (
    ImportLimits,
    validate_projected_reference_count,
)
from core.screening.services.import_validation import validate_uploads


def limits(**overrides):
    base = ImportLimits(
        max_files=100,
        max_file_bytes=50 * 1024 * 1024,
        max_total_bytes=200 * 1024 * 1024,
        warning_references=25000,
        max_references=100000,
        max_title_chars=2000,
        max_abstract_chars=100000,
        max_authors=1000,
        max_record_text_chars=200000,
        max_raw_metadata_bytes=512000,
        max_docx_entries=1000,
        max_docx_uncompressed_bytes=200 * 1024 * 1024,
        max_reported_errors=100,
        allow_partial=False,
        db_batch_size=1000,
        processing_batch_size=1000,
        max_concurrent_per_user=1,
        max_concurrent_per_project=1,
        rate_limit_window_seconds=60,
        rate_limit_requests=10,
        failed_retention_days=7,
    )
    return replace(base, **overrides)


class SizedRis(SimpleUploadedFile):
    """Small in-memory body with a declared size for byte-limit contracts."""

    def __init__(self, name, marker, declared_size):
        body = f'TY  - JOUR\nTI  - {marker}\nER  -\n'.encode()
        super().__init__(name, body, content_type='application/x-research-info-systems')
        self.size = declared_size


class ScreeningCapacityBoundaryTests(SimpleTestCase):
    def test_reference_count_matrix_accepts_limit_and_rejects_limit_plus_one(self):
        cfg = limits()
        for count in (0, 1, 999, 1000, 25000, 50000, 100000):
            with self.subTest(count=count):
                self.assertEqual(validate_projected_reference_count(0, count, cfg), count)
        with self.assertRaises(ScreeningImportError) as caught:
            validate_projected_reference_count(0, 100001, cfg)
        self.assertEqual(caught.exception.code, 'too_many_references')

    def test_file_count_matrix_accepts_100_and_rejects_101(self):
        accepted = [SizedRis(f'{index}.ris', index, 32) for index in range(100)]
        self.assertEqual(len(validate_uploads(accepted, limits())), 100)
        rejected = [SizedRis(f'{index}.ris', index, 32) for index in range(101)]
        with self.assertRaises(ScreeningImportError) as caught:
            validate_uploads(rejected, limits())
        self.assertEqual(caught.exception.code, 'too_many_files')

    def test_file_and_request_byte_limits_reject_one_byte_over(self):
        cfg = limits(max_file_bytes=50, max_total_bytes=200)
        validate_uploads([SizedRis('exact.ris', 'exact', 50)], cfg)
        with self.assertRaises(ScreeningImportError) as caught:
            validate_uploads([SizedRis('over.ris', 'over', 51)], cfg)
        self.assertEqual(caught.exception.code, 'file_too_large')

        files = [SizedRis(f'{index}.ris', index, 50) for index in range(4)]
        self.assertEqual(len(validate_uploads(files, cfg)), 4)
        files[-1] = SizedRis('last.ris', 'last', 51)
        with self.assertRaises(ScreeningImportError) as caught:
            validate_uploads(files, replace(cfg, max_file_bytes=100))
        self.assertEqual(caught.exception.code, 'request_too_large')

    def test_record_field_limits_accept_exact_and_reject_overflow(self):
        cfg = limits(
            max_title_chars=5,
            max_abstract_chars=8,
            max_authors=2,
            max_record_text_chars=100,
            max_raw_metadata_bytes=100,
        )
        base = {'title': '12345', 'abstract': '12345678', 'authors': ['a', 'b']}
        validate_reference_record(base, cfg)
        cases = [
            ({**base, 'title': '123456'}, 'title_too_long'),
            ({**base, 'abstract': '123456789'}, 'abstract_too_long'),
            ({**base, 'authors': ['a', 'b', 'c']}, 'too_many_authors'),
        ]
        for record, code in cases:
            with self.subTest(code=code), self.assertRaises(ReferenceRecordValidationError) as caught:
                validate_reference_record(record, cfg)
            self.assertEqual(caught.exception.code, code)

    def test_xml_dtd_and_docx_path_traversal_are_rejected(self):
        xml = SimpleUploadedFile(
            'unsafe.xml', b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY y "x">]><x>&y;</x>',
        )
        with self.assertRaises(ScreeningImportError) as caught:
            validate_uploads([xml], limits())
        self.assertEqual(caught.exception.code, 'unsafe_xml')

        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('word/document.xml', '<document/>')
            archive.writestr('../escape.txt', 'no')
        docx = SimpleUploadedFile(
            'unsafe.docx', stream.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )
        with self.assertRaises(ScreeningImportError) as caught:
            validate_uploads([docx], limits())
        self.assertEqual(caught.exception.code, 'unsafe_archive_path')


class ScreeningCapacityCommandTests(TestCase):
    def test_benchmark_requires_explicit_execute_flag(self):
        with self.assertRaises(CommandError):
            call_command('benchmark_screening_capacity', references=1)

    def test_small_benchmark_reports_queries_and_cleans_up(self):
        from django.contrib.auth import get_user_model
        from core.models import Project

        output = io.StringIO()
        call_command(
            'benchmark_screening_capacity',
            references=25,
            batch_size=10,
            duplicate_every=10,
            skip_dedup=True,
            execute=True,
            stdout=output,
        )
        report = json.loads(output.getvalue())
        self.assertEqual(report['requested_references'], 25)
        self.assertEqual(report['measurements']['ris_parse']['rows'], 25)
        self.assertEqual(report['measurements']['ai_input_first_page']['status_code'], 200)
        self.assertGreaterEqual(report['measurements']['review_stats']['sql_queries'], 1)
        self.assertEqual(
            report['measurements']['streaming_export']['rows']['all'], 25,
        )
        self.assertFalse(Project.objects.filter(name__startswith='Capacity benchmark').exists())
        self.assertFalse(get_user_model().objects.filter(username__startswith='capacity-').exists())
