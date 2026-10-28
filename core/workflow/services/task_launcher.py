"""统一的步骤任务创建与派发边界。"""

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.models import Project, Task
from core.workflow.domain.statuses import TaskStatus
from core.workflow.services.lifecycle import transition_task
from core.ai.features import AI_TASK_TYPES


ACTIVE_EXECUTION_STATUSES = (
    TaskStatus.QUEUING,
    TaskStatus.PENDING,
    TaskStatus.RUNNING,
    TaskStatus.STOPPING,
)


class ActiveTaskExists(ValueError):
    """同一项目的同一步骤已有未结束任务。"""


def create_step_task(project_id: int, step_key: str, user_id: int, config: dict,
                     *, exclusive: bool = True, allow_during_maintenance: bool = False) -> Task:
    """在项目行锁保护下检查并创建步骤任务。

    锁定 Project 而不是依赖条件唯一索引，以兼容当前服务器使用的数据库。
    所有可执行步骤统一经过这里后，同一项目同一步骤不会同时创建两个活动任务。
    手动步骤可以传 ``exclusive=False``，其重复操作由步骤 action 自身管理。
    """
    from core.operations.services import assert_accepting_new_work

    config = dict(config or {})
    if step_key in AI_TASK_TYPES:
        from django.contrib.auth import get_user_model
        from core.services.entitlement_service import resolve_user_entitlements

        task_user = get_user_model().objects.select_related('profile').get(pk=user_id)
        entitlements = resolve_user_entitlements(task_user)
        config.setdefault(
            'billing_pricing_version',
            settings.MODEL_WEIGHTED_BILLING_PRICING_VERSION,
        )
        config['entitlement_snapshot'] = entitlements.as_dict()
        if step_key == 'ai_screen':
            requested = int(config.get('concurrency') or entitlements.ai_call_slots)
            config['concurrency'] = max(1, min(requested, entitlements.ai_call_slots))

    if not allow_during_maintenance:
        assert_accepting_new_work()
    with transaction.atomic():
        project = Project.objects.select_for_update().get(pk=project_id)
        if exclusive and Task.objects.filter(
            project=project,
            task_type=step_key,
            status__in=ACTIVE_EXECUTION_STATUSES,
        ).exists():
            raise ActiveTaskExists(f'步骤 {step_key} 已有正在执行或等待执行的任务')

        return Task.objects.create(
            project=project,
            task_type=step_key,
            status=TaskStatus.PENDING,
            created_by_id=user_id,
            config=config,
        )


def dispatch_step_task(task: Task, step_key: str | None = None) -> Task:
    """Dispatch an already committed pending task and persist the broker id."""
    from core.executors.celery_tasks import execute_async_step

    step_key = step_key or task.task_type
    try:
        if step_key == 'rescreen_ai':
            result = execute_async_step.apply_async(args=(task.id, step_key, task.project_id),
                soft_time_limit=settings.RESCREEN_AI_SOFT_TIME_LIMIT, time_limit=settings.RESCREEN_AI_HARD_TIME_LIMIT)
        elif step_key == 'rescreen_export':
            result = execute_async_step.apply_async(args=(task.id, step_key, task.project_id),
                soft_time_limit=settings.RESCREEN_EXPORT_SOFT_TIME_LIMIT, time_limit=settings.RESCREEN_EXPORT_HARD_TIME_LIMIT)
        elif step_key in ('rescreen_pdf', 'rescreen_fetch'):
            soft, hard = ((settings.QA_PDF_PROCESS_SOFT_TIME_LIMIT, settings.QA_PDF_PROCESS_HARD_TIME_LIMIT)
                if step_key == 'rescreen_pdf' else (settings.FULLTEXT_LOOKUP_SOFT_TIME_LIMIT, settings.FULLTEXT_LOOKUP_HARD_TIME_LIMIT))
            result = execute_async_step.apply_async(args=(task.id, step_key, task.project_id),
                soft_time_limit=soft, time_limit=hard)
        else:
            result = execute_async_step.delay(task.id, step_key, task.project_id)
    except Exception as exc:
        transition_task(
            task,
            TaskStatus.FAILED,
            updates={'error_message': f'任务派发失败: {exc}', 'completed_at': timezone.now()},
            expected_from={TaskStatus.PENDING},
        )
        raise

    task.celery_task_id = result.id
    task.save(update_fields=['celery_task_id', 'updated_at'])
    return task
