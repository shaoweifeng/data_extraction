"""Lossless SCREEN_2 source appendix without modifying existing QA result sheets."""
import json
from django.conf import settings


class SourceMetadataExportTooLarge(ValueError):
    pass


def append_source_metadata(workbook, references):
    from core.rescreening.models import QASourceBibliographySnapshot
    sources = QASourceBibliographySnapshot.objects.filter(qa_reference__in=references).order_by('qa_reference_id')
    if not sources.exists():
        return
    sheet, count, number, size = None, 0, 0, 0
    for source in sources.iterator(chunk_size=100):
        data = json.dumps({'schema_version':'metaflow-qa-source-v1', 'qa_reference_id':source.qa_reference_id,
            'bibliography':source.bibliography, 'raw_metadata':source.raw_metadata, 'provenance':source.provenance}, ensure_ascii=False)
        size += len(data.encode('utf-8'))
        if size > min(settings.RESCREEN_EXPORT_MAX_BYTES, 32 * 1024 * 1024):
            raise SourceMetadataExportTooLarge('来源元数据超过单份 QA Excel 的 32 MiB 安全上限，请缩小质量方法范围或使用复筛分批元数据导出。')
        for part, offset in enumerate(range(0, len(data), 15000), 1):
            if sheet is None or count >= 1000000:
                number += 1
                sheet = workbook.create_sheet('复筛来源元数据' if number == 1 else f'复筛来源元数据_{number}')
                sheet.append(['QA文献ID', 'part', '完整来源JSON（按part拼接还原）'])
                count = 1
            sheet.append([source.qa_reference_id, part, data[offset:offset+15000]])
            sheet.cell(sheet.max_row, 3).data_type = 's'
            count += 1
