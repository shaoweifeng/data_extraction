"""TXT/ENW 索引解析与原始文件下载回归测试。"""

import hashlib
import json
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from core.models import DataFile, Project, ProjectStage, StageStep
from core.artifacts.types import ArtifactType
from core.artifacts.services import reset_downstream_on_input_delete
from core.screening.parsers import convert_to_xml, parse_file
from core.screening.parsers.enw import parse_enw


TAGGED_TEXT = """%0 Journal Article
%A 张三
%A 李四

%+ 循证医学中心
%T 糖尿病筛查研究
%J 中华循证医学杂志
%D 2025


%0 Journal Article
%A 王五

%T 高血压干预研究
%J 临床医学
%D 2024
"""


class TaggedTextParserTests(TestCase):
    def _parse_bytes(self, content, suffix='.txt'):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / f'references{suffix}'
            path.write_bytes(content)
            return parse_enw(str(path))

    def test_blank_lines_inside_record_do_not_split_references(self):
        entries = self._parse_bytes(TAGGED_TEXT.encode('utf-8'))

        self.assertEqual(len(entries), 2)
        self.assertEqual(
            [item['title'] for item in entries],
            ['糖尿病筛查研究', '高血压干预研究'],
        )
        self.assertEqual(entries[0]['authors'], ['张三', '李四'])
        self.assertEqual(entries[0]['journal'], '中华循证医学杂志')
        self.assertEqual(entries[0]['address'], '循证医学中心')

    def test_author_address_survives_enw_to_xml_conversion(self):
        content = """%0 Journal Article
%A 张三
%+ 第一附属医院;
%+ 循证医学中心
%C 北京
%T 地址字段测试
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / 'references.enw'
            output_path = Path(temp_dir) / 'references.xml'
            input_path.write_text(content, encoding='utf-8')

            entries = parse_enw(str(input_path))
            convert_to_xml(entries, str(output_path))
            round_tripped = parse_file(str(output_path))

        expected_address = '第一附属医院; 循证医学中心'
        self.assertEqual(entries[0]['address'], expected_address)
        self.assertEqual(round_tripped[0]['address'], expected_address)

    def test_common_chinese_encodings_preserve_characters(self):
        for encoding in ('utf-8-sig', 'utf-16', 'gb18030'):
            with self.subTest(encoding=encoding):
                entries = self._parse_bytes(TAGGED_TEXT.encode(encoding))
                self.assertEqual(entries[0]['title'], '糖尿病筛查研究')
                self.assertEqual(entries[1]['title'], '高血压干预研究')


class OriginalFileDownloadTests(TestCase):
    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory(prefix='txt-download-test-')
        self.settings_override = override_settings(MEDIA_ROOT=self.media_dir.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.addCleanup(self.media_dir.cleanup)

        self.user = get_user_model().objects.create_user(
            username='txt-owner', password='test-pass'
        )
        self.project = Project.objects.create(name='TXT download', owner=self.user)
        self.content = TAGGED_TEXT.encode('utf-8')
        self.data_file = DataFile.objects.create(
            project=self.project,
            filename='中文索引.txt',
            file=SimpleUploadedFile(
                '中文索引.txt', self.content, content_type='text/plain'
            ),
            data_category='input',
            created_by=self.user,
        )

    def test_download_is_attachment_and_preserves_original_bytes(self):
        self.client.force_login(self.user)
        response = self.client.get(f'/api/files/{self.data_file.id}/download/')
        downloaded = b''.join(response.streaming_content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/octet-stream')
        self.assertIn('attachment;', response['Content-Disposition'])
        self.assertEqual(hashlib.sha256(downloaded).digest(), hashlib.sha256(self.content).digest())

    def test_other_user_cannot_download_project_file(self):
        other = get_user_model().objects.create_user(
            username='other-user', password='test-pass'
        )
        self.client.force_login(other)

        response = self.client.get(f'/api/files/{self.data_file.id}/download/')

        self.assertEqual(response.status_code, 404)

    def test_parse_report_endpoint_returns_latest_diagnostics(self):
        payload = {
            'filename': self.data_file.filename,
            'status': 'warning',
            'detected_entries': 2,
            'parsed_entries': 2,
            'missing_abstract_entries': 1,
            'issues': [{'code': 'missing_abstract', 'severity': 'warning'}],
        }
        DataFile.objects.create(
            project=self.project,
            filename=f'parse_report_{self.data_file.id}.json',
            file=SimpleUploadedFile(
                f'parse_report_{self.data_file.id}.json',
                json.dumps(payload).encode('utf-8'),
                content_type='application/json',
            ),
            data_category='output',
            metadata={
                'artifact_type': ArtifactType.SCREENING_PARSE_REPORT_JSON,
                'source_file_id': self.data_file.id,
            },
            created_by=self.user,
        )
        self.client.force_login(self.user)

        response = self.client.get(f'/api/files/{self.data_file.id}/parse-report/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['missing_abstract_entries'], 1)
        self.assertEqual(response.json()['issues'][0]['code'], 'missing_abstract')


class InputDeletionStatisticsTests(TestCase):
    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory(prefix='input-delete-test-')
        self.settings_override = override_settings(MEDIA_ROOT=self.media_dir.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.addCleanup(self.media_dir.cleanup)

        self.user = get_user_model().objects.create_user(
            username='delete-owner', password='test-pass'
        )
        self.project = Project.objects.create(name='Delete statistics', owner=self.user)
        self.stage = ProjectStage.objects.create(
            project=self.project,
            stage_key='SCREEN_1',
            name='文献初筛',
        )
        self.parse_step = StageStep.objects.create(
            stage=self.stage,
            step_key='parse',
            name='文献解析',
            status='completed',
            metadata={'total_entries': 5},
        )
        self.dedup_step = StageStep.objects.create(
            stage=self.stage,
            step_key='dedup',
            name='文献去重',
            status='completed',
            metadata={'unique_count': 5},
        )

    def _file(self, filename, *, category='input', step=None, metadata=None):
        return DataFile.objects.create(
            project=self.project,
            stage=self.stage,
            step=step,
            filename=filename,
            file=SimpleUploadedFile(filename, b'test'),
            data_category=category,
            metadata=metadata or {},
            created_by=self.user,
        )

    def test_deleting_one_input_preserves_other_input_summary_and_report(self):
        removed = self._file(
            'removed.enw',
            metadata={'parse_summary': {'parsed_entries': 2, 'detected_entries': 2}},
        )
        retained = self._file(
            'retained.enw',
            metadata={'parse_summary': {'parsed_entries': 3, 'detected_entries': 3}},
        )
        removed_report = self._file(
            f'parse_report_{removed.id}.json',
            category='output',
            step=self.parse_step,
            metadata={
                'artifact_type': ArtifactType.SCREENING_PARSE_REPORT_JSON,
                'source_file_id': removed.id,
            },
        )
        retained_report = self._file(
            f'parse_report_{retained.id}.json',
            category='output',
            step=self.parse_step,
            metadata={
                'artifact_type': ArtifactType.SCREENING_PARSE_REPORT_JSON,
                'source_file_id': retained.id,
            },
        )
        self._file(
            'parsed.xml',
            category='intermediate',
            step=self.parse_step,
            metadata={'artifact_type': ArtifactType.SCREENING_PARSED_REFERENCE_XML},
        )
        self._file(
            'dedup.xml',
            category='intermediate',
            step=self.dedup_step,
            metadata={'artifact_type': ArtifactType.SCREENING_DEDUP_REFERENCE_XML},
        )

        reset_downstream_on_input_delete(removed, self.user)
        removed.delete()

        retained.refresh_from_db()
        self.parse_step.refresh_from_db()
        self.dedup_step.refresh_from_db()
        self.assertEqual(retained.metadata['parse_summary']['parsed_entries'], 3)
        self.assertFalse(DataFile.objects.filter(id=removed_report.id).exists())
        self.assertTrue(DataFile.objects.filter(id=retained_report.id).exists())
        self.assertFalse(DataFile.objects.filter(data_category='intermediate').exists())
        self.assertEqual(self.parse_step.status, 'pending')
        self.assertEqual(self.parse_step.metadata, {})
        self.assertEqual(self.dedup_step.status, 'pending')
        self.assertEqual(self.dedup_step.metadata, {})
