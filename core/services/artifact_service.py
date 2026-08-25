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

from core.models import ActivityLog, DataFile, StageStep


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
    ).first()

    if not ai_step:
        return {'included': 0, 'excluded': 0, 'conflict': 0, 'pending': 0, 'total': 0}

    qs = DataFile.objects.filter(project=project, step=ai_step, data_category='output')
    total    = qs.count()
    included = qs.filter(metadata__decision='included').count()
    excluded = qs.filter(metadata__decision='excluded').count()
    conflict = qs.filter(metadata__consensus='conflict').count()
    pending  = total - included - excluded - conflict

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
    ).delete()

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
        if step.status in ('completed', 'in_progress', 'failed'):
            step.status = 'pending'
            step.metadata = {}
            step.save()


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
