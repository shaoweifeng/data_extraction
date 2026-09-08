"""Task、StageStep、ProjectStage 的集中状态转换服务。

所有转换都会重新锁定并读取数据库记录，避免调用方使用过期对象覆盖较新的
状态。同状态转换视为幂等操作；不在转换矩阵中的状态变化会被明确拒绝。
"""

from typing import Dict, Iterable, Mapping, Optional, Set

from django.db import transaction

from core.workflow.domain.statuses import ProjectStageStatus, StageStepStatus, TaskStatus


class InvalidStateTransition(ValueError):
    """状态转换不符合生命周期规则。"""

    def __init__(self, entity: str, current: str, target: str):
        self.entity = entity
        self.current = current
        self.target = target
        super().__init__(f'{entity} 状态不能从 {current} 转换为 {target}')


TASK_TRANSITIONS: Mapping[str, Set[str]] = {
    TaskStatus.PENDING: {
        TaskStatus.QUEUING,
        TaskStatus.RUNNING,
        TaskStatus.STOPPING,
        TaskStatus.FAILED,
    },
    TaskStatus.QUEUING: {
        TaskStatus.PENDING,
        TaskStatus.RUNNING,
        TaskStatus.STOPPING,
        TaskStatus.FAILED,
    },
    TaskStatus.RUNNING: {
        # Celery 对可重试异常重新排队同一个 Task。
        TaskStatus.PENDING,
        TaskStatus.WAITING_USER,
        TaskStatus.STOPPING,
        TaskStatus.STOPPED,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
    },
    TaskStatus.WAITING_USER: {
        TaskStatus.RUNNING,
        TaskStatus.STOPPING,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
    },
    TaskStatus.STOPPING: {TaskStatus.STOPPED},
    TaskStatus.STOPPED: {TaskStatus.SUPERSEDED},
    TaskStatus.COMPLETED: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.SUPERSEDED: set(),
}

STEP_TRANSITIONS: Mapping[str, Set[str]] = {
    StageStepStatus.PENDING: {
        StageStepStatus.IN_PROGRESS,
        StageStepStatus.COMPLETED,
        StageStepStatus.SKIPPED,
    },
    StageStepStatus.IN_PROGRESS: {
        StageStepStatus.PENDING,
        StageStepStatus.STOPPED,
        StageStepStatus.COMPLETED,
        StageStepStatus.FAILED,
        StageStepStatus.SKIPPED,
    },
    StageStepStatus.STOPPED: {
        StageStepStatus.PENDING,
        StageStepStatus.IN_PROGRESS,
        StageStepStatus.SKIPPED,
    },
    StageStepStatus.FAILED: {
        StageStepStatus.PENDING,
        StageStepStatus.IN_PROGRESS,
        StageStepStatus.SKIPPED,
    },
    # 删除上游输入时允许显式重置已完成步骤。
    StageStepStatus.COMPLETED: {StageStepStatus.PENDING},
    StageStepStatus.SKIPPED: {StageStepStatus.PENDING},
}

STAGE_TRANSITIONS: Mapping[str, Set[str]] = {
    ProjectStageStatus.PENDING: {
        ProjectStageStatus.IN_PROGRESS,
        ProjectStageStatus.STOPPED,
        ProjectStageStatus.COMPLETED,
        ProjectStageStatus.SKIPPED,
    },
    ProjectStageStatus.IN_PROGRESS: {
        ProjectStageStatus.STOPPED,
        ProjectStageStatus.COMPLETED,
        ProjectStageStatus.FAILED,
        ProjectStageStatus.SKIPPED,
    },
    ProjectStageStatus.STOPPED: {
        ProjectStageStatus.PENDING,
        ProjectStageStatus.IN_PROGRESS,
        ProjectStageStatus.SKIPPED,
    },
    ProjectStageStatus.FAILED: {
        ProjectStageStatus.PENDING,
        ProjectStageStatus.IN_PROGRESS,
        ProjectStageStatus.SKIPPED,
    },
    ProjectStageStatus.COMPLETED: {ProjectStageStatus.PENDING},
    ProjectStageStatus.SKIPPED: {ProjectStageStatus.PENDING},
}


def _can_transition(matrix: Mapping[str, Set[str]], current: str, target: str) -> bool:
    return current in matrix and (current == target or target in matrix[current])


def can_transition_task(current: str, target: str) -> bool:
    return _can_transition(TASK_TRANSITIONS, current, target)


def can_transition_step(current: str, target: str) -> bool:
    return _can_transition(STEP_TRANSITIONS, current, target)


def can_transition_stage(current: str, target: str) -> bool:
    return _can_transition(STAGE_TRANSITIONS, current, target)


def _transition(instance, target: str, *, entity: str, matrix, updates: Optional[Dict] = None,
                expected_from: Optional[Iterable[str]] = None):
    if instance.pk is None:
        raise ValueError(f'{entity} 必须先保存后才能转换状态')

    updates = dict(updates or {})
    if 'status' in updates:
        raise ValueError('updates 不能包含 status')

    model = type(instance)
    with transaction.atomic():
        locked = model.objects.select_for_update().get(pk=instance.pk)
        current = locked.status
        allowed_sources = set(expected_from) if expected_from is not None else None
        if allowed_sources is not None and current not in allowed_sources:
            raise InvalidStateTransition(entity, current, target)
        if not _can_transition(matrix, current, target):
            raise InvalidStateTransition(entity, current, target)

        locked.status = target
        for field, value in updates.items():
            setattr(locked, field, value)

        update_fields = ['status', *updates.keys()]
        if hasattr(locked, 'updated_at'):
            update_fields.append('updated_at')
        locked.save(update_fields=list(dict.fromkeys(update_fields)))

    instance.status = locked.status
    for field in updates:
        setattr(instance, field, getattr(locked, field))
    if hasattr(instance, 'updated_at'):
        instance.updated_at = locked.updated_at
    return instance


def transition_task(task, target: str, *, updates: Optional[Dict] = None,
                    expected_from: Optional[Iterable[str]] = None):
    return _transition(
        task,
        target,
        entity='Task',
        matrix=TASK_TRANSITIONS,
        updates=updates,
        expected_from=expected_from,
    )


def transition_step(step, target: str, *, updates: Optional[Dict] = None,
                    expected_from: Optional[Iterable[str]] = None):
    return _transition(
        step,
        target,
        entity='StageStep',
        matrix=STEP_TRANSITIONS,
        updates=updates,
        expected_from=expected_from,
    )


def transition_stage(stage, target: str, *, updates: Optional[Dict] = None,
                     expected_from: Optional[Iterable[str]] = None):
    return _transition(
        stage,
        target,
        entity='ProjectStage',
        matrix=STAGE_TRANSITIONS,
        updates=updates,
        expected_from=expected_from,
    )
