"""质量评价模块自己的轻量 Celery 任务。"""

import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings


logger = logging.getLogger(__name__)


@shared_task(
    soft_time_limit=settings.QA_PDF_PROCESS_SOFT_TIME_LIMIT,
    time_limit=settings.QA_PDF_PROCESS_HARD_TIME_LIMIT,
)
def parse_qa_pdf_meta(ref_id):
    """异步校验、扫描并解析单篇 QA PDF。"""
    try:
        from core.models import QAFulltextAsset
        from core.quality.services.fulltext import process_fulltext_asset

        asset_id = QAFulltextAsset.objects.only('id').get(qa_reference_id=ref_id).id
        process_fulltext_asset(asset_id)
    except SoftTimeLimitExceeded:
        from core.models import QAFulltextAsset
        from core.quality.services.fulltext import mark_processing_timeout

        asset_id = QAFulltextAsset.objects.filter(
            qa_reference_id=ref_id,
        ).values_list('id', flat=True).first()
        if asset_id:
            mark_processing_timeout(asset_id)
        logger.warning('QA PDF 处理超时 ref_id=%s', ref_id)
        raise
    except QAFulltextAsset.DoesNotExist:
        logger.warning('QA PDF 资产不存在 ref_id=%s', ref_id)
    except Exception as exc:
        logger.warning('QA PDF 处理失败 ref_id=%s error=%s', ref_id, type(exc).__name__)
        raise


@shared_task
def cleanup_qa_fulltext_files():
    from core.quality.services.fulltext import cleanup_expired_fulltext_files

    result = cleanup_expired_fulltext_files()
    logger.info(
        'QA 全文保留策略清理完成 stale_assets=%s raw_files=%s text_files=%s',
        result['stale_assets'], result['raw_files'], result['text_files'],
    )
    return result
