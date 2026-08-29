"""
QA 模块 Celery 任务入口
- run_qa_ai_eval: AI 质量评价任务
- parse_qa_pdf_meta: PDF 元数据解析任务
"""
import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2)
def run_qa_ai_eval(self, project_id, ref_ids, eval_mode, model_ids, user_id=None):
    """
    AI 质量评价主任务

    Args:
        project_id: 项目 ID
        ref_ids: 待评价文献 ID 列表
        eval_mode: 'single' | 'dual'
        model_ids: 选择的模型 ID 列表
        user_id: 发起人 ID（用于扣积分）
    """
    try:
        from core.executors.handlers.qa_handler import QAEvalHandler
        handler = QAEvalHandler(
            project_id=project_id,
            ref_ids=ref_ids,
            eval_mode=eval_mode,
            model_ids=model_ids,
            user_id=user_id,
        )
        handler.execute()
    except Exception as exc:
        logger.exception(f'run_qa_ai_eval 失败 project_id={project_id}: {exc}')
        try:
            self.retry(exc=exc, countdown=30)
        except self.MaxRetriesExceededError:
            # 超出重试，将所有 running 文献标记为 failed
            from core.models import QAReference
            QAReference.objects.filter(pk__in=ref_ids, ai_eval_status='running').update(ai_eval_status='failed')


@shared_task
def parse_qa_pdf_meta(ref_id):
    """
    解析 PDF 提取文献元数据（标题、作者、年份、摘要）

    Args:
        ref_id: QAReference.id
    """
    try:
        from core.executors.handlers.qa_handler import extract_pdf_meta
        extract_pdf_meta(ref_id)
    except Exception as exc:
        logger.warning(f'parse_qa_pdf_meta ref_id={ref_id} 失败（非致命）: {exc}')
