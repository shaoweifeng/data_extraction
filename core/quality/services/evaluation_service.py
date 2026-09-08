"""QA AI 评价任务的应用服务。"""

from core.models import QAReference
from core.quality.domain.methods import AI_SUPPORTED_METHODS
from core.ai import AIQuotaService
from core.services.task_service import log_task_start


def start_evaluation(project, user, ref_ids, model_ids):
    """校验文献和积分后，通过统一调度器创建 QA 评价任务。"""
    refs = QAReference.objects.filter(project=project)
    if ref_ids:
        if refs.filter(pk__in=ref_ids).count() != len(ref_ids):
            raise ValueError('部分文献不存在或不属于该项目')
        refs = refs.filter(pk__in=ref_ids)
    refs = refs.filter(quality_method__in=AI_SUPPORTED_METHODS).exclude(quality_method='')
    evaluable_count = refs.count()
    if evaluable_count == 0:
        raise ValueError('没有可评价的文献（请先选择支持 AI 评价的方法）')

    estimated = AIQuotaService.preflight(user, evaluable_count, model_ids)

    from core.scheduler import TaskScheduler

    selected_ids = list(refs.values_list('pk', flat=True))
    task = TaskScheduler(project.id).start_step(
        'qa_eval', user.id, ref_ids=selected_ids, model_ids=model_ids
    )
    # 任务入队后立即发布文献级运行状态，避免首次进度查询早于
    # Celery worker 开始而被迫多等一个轮询周期。worker 的同值更新保持幂等。
    eval_mode = 'single' if len(model_ids) <= 1 else 'multi'
    QAReference.objects.filter(pk__in=selected_ids).update(
        ai_eval_status='running',
        eval_mode=eval_mode,
        selected_models=model_ids,
    )
    log_task_start(project.id, 'qa_eval', task.id, user)
    return {
        'task_id': task.id,
        'evaluable_count': evaluable_count,
        'ref_ids': selected_ids,
        'estimated_credits': estimated,
    }
