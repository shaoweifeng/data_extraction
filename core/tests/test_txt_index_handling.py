"""TXT/ENW 索引解析与原始文件下载回归测试。"""

import hashlib
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from core.models import DataFile, Project
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
