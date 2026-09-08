"""质量评价模块自己的轻量 Celery 任务。"""

import logging

from celery import shared_task


logger = logging.getLogger(__name__)


@shared_task
def parse_qa_pdf_meta(ref_id):
    """异步解析单篇 QA PDF 元数据；失败不影响用户后续手工编辑。"""
    try:
        from core.quality.executors.qa_eval import extract_pdf_meta

        extract_pdf_meta(ref_id)
    except Exception as exc:
        logger.warning(f'parse_qa_pdf_meta ref_id={ref_id} 失败（非致命）: {exc}')
