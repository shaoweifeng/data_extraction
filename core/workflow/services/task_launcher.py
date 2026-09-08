"""统一的步骤任务创建边界。"""

from django.db import transaction

from core.models import Project, Task
from core.workflow.domain.statuses import TaskStatus


ACTIVE_EXECUTION_STATUSES = (
    TaskStatus.QUEUING,
    TaskStatus.PENDING,
    TaskStatus.RUNNING,
    TaskStatus.STOPPING,
)


class ActiveTaskExists(ValueError):
    """同一项目的同一步骤已有未结束任务。"""


def create_step_task(project_id: int, step_key: str, user_id: int, config: dict,
                     *, exclusive: bool = True) -> Task:
    """在项目行锁保护下检查并创建步骤任务。

    锁定 Project 而不是依赖条件唯一索引，以兼容当前服务器使用的数据库。
    所有可执行步骤统一经过这里后，同一项目同一步骤不会同时创建两个活动任务。
    手动步骤可以传 ``exclusive=False``，其重复操作由步骤 action 自身管理。
    """
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
