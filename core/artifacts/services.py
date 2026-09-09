"""
产物（DataFile）业务服务层

职责：
- 封装 DataFile 的常用查询和操作
- 统一产物分类约定（data_category / step_key / metadata.artifact_type）
- 收拢"删除输入文件时需要联动清理下游"的业务逻辑

注意：
- Executor 内部的产物写入逻辑（create DataFile）暂不迁移到本层，
  那部分依赖执行上下文，在批次 C（handler 注册）时一并整理。
- 本层专注于 ViewSet 层的产物查询与管理。
"""

from typing import Dict, List

from django.db.models import Count, Q

from core.models import ActivityLog, DataFile, StageStep
from core.artifacts.types import ArtifactType
from core.workflow.domain.statuses import StageStepStatus
from core.workflow.services.lifecycle import transition_step


# ============================================================================
# AI 初筛产物
# ============================================================================

def get_ai_screen_stats(project) -> Dict:
    """
    获取 AI 初筛统计数据（included / excluded / conflict / pending / total）。
    """
    ai_step = StageStep.objects.filter(
        stage__project=project,
        step_key='ai_screen',
    ).order_by('-id').first()

    if not ai_step:
        return {
            'included': 0, 'excluded': 0, 'conflict': 0, 'pending_count': 0,
            'total': 0, 'included_count': 0, 'excluded_count': 0,
            'conflict_count': 0,
        }

    # 新版 AI 初筛在任务完成时已将互斥统计写入步骤元数据。完成后的页面
    # 直接读取这一小段缓存，不再扫描 2.5 万条 DataFile；历史步骤自动回退
    # 到下面的一次数据库聚合。
    metadata = ai_step.metadata or {}
    if (
        ai_step.status == StageStepStatus.COMPLETED
        and metadata.get('stats_version') == 2
    ):
        included = int(metadata.get('included_refs', 0))
        excluded = int(metadata.get('excluded_refs', 0))
        conflict = int(metadata.get('conflict_refs', 0))
        pending = int(metadata.get('pending_refs', 0))
        total = included + excluded + conflict + pending
        return {
            'included': included,
            'excluded': excluded,
            'conflict': conflict,
            'pending_count': pending,
            'total': total,
            'included_count': included,
            'excluded_count': excluded,
            'conflict_count': conflict,
        }

    qs = DataFile.objects.filter(
        project=project,
        step=ai_step,
        data_category='output',
        metadata__artifact_type=ArtifactType.SCREENING_RESULT_JSON,
    )
    # JSONField 没有独立索引。原实现连续 count 四次，会让 MySQL 对同一批
    # 结果反复扫描。一次条件聚合即可得到互斥分类，并避免 conflict 同时被计入
    # included/excluded 后造成 pending 统计失真。
    conflict_filter = (
        Q(metadata__consensus='conflict')
        | (Q(metadata__consensus__isnull=True) & Q(metadata__decision='conflict'))
    )
    not_conflict = ~conflict_filter
    counts = qs.aggregate(
        total=Count('pk'),
        included=Count(
            'pk', filter=Q(metadata__decision='included') & not_conflict,
        ),
        excluded=Count(
            'pk', filter=Q(metadata__decision='excluded') & not_conflict,
        ),
        conflict=Count('pk', filter=conflict_filter),
    )
    total = counts['total']
    included = counts['included']
    excluded = counts['excluded']
    conflict = counts['conflict']
    pending = total - included - excluded - conflict

    if ai_step.status == StageStepStatus.COMPLETED:
        cached_metadata = dict(metadata)
        cached_metadata.update({
            'stats_version': 2,
            'included_refs': included,
            'excluded_refs': excluded,
            'conflict_refs': conflict,
            'pending_refs': max(0, pending),
        })
        StageStep.objects.filter(pk=ai_step.pk).update(metadata=cached_metadata)

    return {
        'included':       included,
        'excluded':       excluded,
        'conflict':       conflict,
        'pending_count':  max(0, pending),
        'total':          total,
        'included_count': included,
        'excluded_count': excluded,
        'conflict_count': conflict,
    }


def clear_ai_screen_outputs(project, user) -> Dict:
    """
    清除 AI 初筛输出产物，并写入操作日志。

    Returns:
        {message, deleted_count}
    """
    ai_step = StageStep.objects.filter(
        stage__project=project,
        step_key='ai_screen',
    ).first()

    if not ai_step:
        return {'message': '未找到 ai_screen 步骤，无需清除', 'deleted_count': 0}

    deleted_count, _ = DataFile.objects.filter(
        project=project,
        step=ai_step,
        data_category='output',
        metadata__artifact_type=ArtifactType.SCREENING_RESULT_JSON,
    ).delete()

    # 删除结果后必须让完成时统计缓存失效，否则新任务真正启动前可能短暂展示旧值。
    metadata = dict(ai_step.metadata or {})
    metadata.pop('stats_version', None)
    ai_step.metadata = metadata
    ai_step.save(update_fields=['metadata'])

    ActivityLog.objects.create(
        project=project,
        operation_type='task_abandon',
        operation_detail={
            'task_type': 'AI初筛',
            'action': 'clear_results',
            'deleted_count': deleted_count,
        },
        created_by=user,
    )

    return {'message': f'已清除 {deleted_count} 条筛选结果记录', 'deleted_count': deleted_count}


# ============================================================================
# 输入文件删除时的联动清理
# ============================================================================

def reset_downstream_on_input_delete(project, user):
    """
    删除输入文件时，联动清理下游中间产物并重置步骤状态。

    业务规则：
    - 删除 input 文件 → 清空 parse / dedup 的 intermediate DataFile
    - 将 parse / dedup 步骤状态重置为 pending

    Args:
        project: 被操作的项目
        user: 操作用户（保留用于将来写 ActivityLog）
    """
    for step_key in ['parse', 'dedup']:
        step = StageStep.objects.filter(
            stage__project=project,
            step_key=step_key,
        ).first()

        if not step:
            continue

        # 清除中间产物
        deleted_qs = DataFile.objects.filter(
            project=project,
            step=step,
            data_category='intermediate',
        )
        if deleted_qs.exists():
            deleted_qs.delete()

        # 重置步骤状态
        if step.status in (
            StageStepStatus.COMPLETED,
            StageStepStatus.IN_PROGRESS,
            StageStepStatus.FAILED,
            StageStepStatus.STOPPED,
            StageStepStatus.SKIPPED,
        ):
            transition_step(
                step,
                StageStepStatus.PENDING,
                updates={
                    'metadata': {},
                    'started_at': None,
                    'completed_at': None,
                },
            )


# ============================================================================
# 通用产物查询
# ============================================================================

def get_step_outputs(project, step_key: str, data_category: str = 'output') -> List[DataFile]:
    """
    获取某步骤的产物列表。

    Args:
        project: 项目对象
        step_key: 步骤标识
        data_category: 产物分类（input / intermediate / output）

    Returns:
        DataFile QuerySet
    """
    return DataFile.objects.filter(
        project=project,
        step__step_key=step_key,
        data_category=data_category,
    ).select_related('step')
