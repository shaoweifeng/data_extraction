"""
产物（DataFile）业务服务层

职责：
- 封装 DataFile 的常用查询和操作
- 统一产物分类约定（data_category / step_key / metadata.artifact_type）
- 收拢"删除输入文件时需要联动清理下游"的业务逻辑

执行器生成文件也通过本层持久化，确保分块写入、产物类型与元数据规则一致。
"""

import re
import shutil
from pathlib import Path
from typing import Dict, List

from django.core.files import File
from django.db.models import Count, Q

from core.models import ActivityLog, DataFile, StageStep
from core.artifacts.types import ArtifactType
from core.workflow.domain.statuses import StageStepStatus
from core.workflow.services.lifecycle import transition_step


def persist_generated_artifact(
    *, project, stage, step, creator, file_path: Path, filename: str,
    description: str, category: str = 'output', artifact_type: str | None = None,
    metadata: Dict | None = None,
) -> DataFile:
    """Persist a private generated file without loading it wholly into memory."""
    artifact_metadata = dict(metadata or {})
    if artifact_type:
        artifact_metadata['artifact_type'] = artifact_type
    with Path(file_path).open('rb') as source_file:
        return DataFile.objects.create(
            project=project,
            stage=stage,
            step=step,
            filename=filename,
            file=File(source_file, name=filename),
            data_category=category,
            source='tool_generated',
            description=description,
            metadata=artifact_metadata,
            created_by=creator,
        )


def cleanup_expired_workspaces(root: Path, cutoff_timestamp: float) -> int:
    """Remove expired task workspaces below the configured root only."""
    root = Path(root).resolve()
    if root.name != 'workspaces':
        raise ValueError('工作区清理根目录必须明确指向 workspaces 目录。')
    if not root.exists():
        return 0
    cleaned = 0
    for project_dir in root.iterdir():
        if (
            not project_dir.is_dir()
            or project_dir.is_symlink()
            or not re.fullmatch(r'project_\d+', project_dir.name)
        ):
            continue
        for task_dir in project_dir.iterdir():
            if (
                not task_dir.is_dir()
                or task_dir.is_symlink()
                or not re.search(r'(?:_task_\d+_\d{8}_\d{6}|_\d{14})$', task_dir.name)
            ):
                continue
            try:
                expired = task_dir.stat().st_mtime < cutoff_timestamp
            except OSError:
                continue
            if expired:
                shutil.rmtree(task_dir)
                cleaned += 1
    return cleaned


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
            'total': 0, 'processed_count': 0, 'remaining_count': 0,
            'included_count': 0, 'excluded_count': 0, 'conflict_count': 0,
        }

    # 新版 AI 初筛在任务完成时已将互斥统计写入步骤元数据。完成后的页面
    # 直接读取这一小段缓存，不再扫描 2.5 万条 DataFile；历史步骤自动回退
    # 到下面的一次数据库聚合。
    metadata = ai_step.metadata or {}
    if (
        ai_step.status == StageStepStatus.COMPLETED
        and metadata.get('stats_version') in (2, 3)
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
            'processed_count': total,
            'remaining_count': 0,
            'included_count': included,
            'excluded_count': excluded,
            'conflict_count': conflict,
        }

    from core.screening.services.screening_run_service import current_screening_run

    run = current_screening_run(project.id)
    if run is None:
        return {
            'included': 0, 'excluded': 0, 'conflict': 0, 'pending_count': 0,
            'total': 0, 'processed_count': 0, 'remaining_count': 0,
            'included_count': 0, 'excluded_count': 0, 'conflict_count': 0,
        }
    conflict = run.results.filter(consensus='conflict').count()
    included = run.included_count
    excluded = run.excluded_count
    pending = max(0, run.uncertain_count - conflict + run.failed_count)
    total = run.total_count
    processed = run.processed_count

    return {
        'included':       included,
        'excluded':       excluded,
        'conflict':       conflict,
        'pending_count':  max(0, pending),
        'total':          total,
        'processed_count': processed,
        'remaining_count': max(0, total - processed),
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

    from core.screening.models import ScreeningRun

    database_result_count = ScreeningRun.objects.filter(
        project=project,
    ).aggregate(total=Count('results'))['total'] or 0
    ScreeningRun.objects.filter(project=project).delete()
    deleted_count = database_result_count

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

def reset_downstream_on_input_delete(source_file, user):
    """
    删除输入文件时，联动清理下游中间产物并重置步骤状态。

    业务规则：
    - 删除 input 文件 → 清空 parse / dedup 的 intermediate DataFile
    - 将 parse / dedup 步骤状态重置为 pending
    - 仅删除当前输入文件的解析报告，保留其余输入文件的解析统计

    Args:
        source_file: 被删除的输入 DataFile
        user: 操作用户（保留用于将来写 ActivityLog）
    """
    project = source_file.project

    DataFile.objects.filter(
        project=project,
        data_category='output',
        metadata__artifact_type=ArtifactType.SCREENING_PARSE_REPORT_JSON,
    ).filter(
        Q(metadata__source_file_id=source_file.id)
        | Q(filename=f'parse_report_{source_file.id}.json')
    ).delete()

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
