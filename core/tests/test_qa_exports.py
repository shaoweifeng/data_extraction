"""QA Excel exporter 的长期契约测试。"""

import io

import openpyxl
from django.contrib.auth import get_user_model
from django.test import TestCase

from core.models import Project, QAReference
from core.quality.exporters.excel import export_qa_excel


User = get_user_model()


class QaExcelExporterTests(TestCase):
    def test_exporter_returns_expected_workbook_without_http_request(self):
        user = User.objects.create_user('qa-export-user')
        project = Project.objects.create(name='QA export project', owner=user)
        QAReference.objects.create(
            project=project,
            title='Exported Study',
            quality_method='QUADAS2',
            review_status='confirmed',
        )

        filename, content = export_qa_excel(project, 'QUADAS2')

        self.assertTrue(filename.endswith('.xlsx'))
        workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
        self.assertEqual(
            workbook.sheetnames,
            ['汇总统计', '评价明细', '证据记录', '多模型校验记录'],
        )
        self.assertEqual(workbook['汇总统计']['A2'].value, 'Exported Study')
        workbook.close()
