"""统一的步骤任务创建与派发边界。"""

from django.db import transaction
from django.utils import timezone

from core.models import Project, Task
from core.workflow.domain.statuses import TaskStatus
from core.workflow.services.lifecycle import transition_task


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
