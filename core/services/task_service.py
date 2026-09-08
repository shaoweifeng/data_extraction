"""
任务业务服务层

职责：
- 封装任务启动/停止/恢复时的 ActivityLog 写入
- 统一 task_type → 中文名称 映射
- 提供权限校验辅助（避免在 ViewSet 中内联权限逻辑）
- 为后续 handler 注册机制（批次 C）提供过渡接口

注意：
- 任务真正的创建、执行、停止、恢复仍由 TaskScheduler 负责；
  本层只封装"调用 scheduler 前后"的业务附加逻辑。
- 批次 C 完成后，任务创建逻辑将进一步下沉到 handler 注册表。
"""

import logging
from typing import Optional

from core.models import ActivityLog, Task

logger = logging.getLogger(__name__)

# ============================================================================
# 常量：task_type → 中文名
# ============================================================================

TASK_TYPE_DISPLAY: dict = {
    'parse': '文献解析',
    'dedup': '文献去重',
    'ai_screen': 'AI初筛',
    'export': '结果归纳',
    'field_extraction': '提取字段',
    'criteria': '纳排标准',
    # QA 步骤
    'qa_upload': '上传文献',
    'qa_method': '方法选择',
    'qa_eval': 'AI质量评价',
    'qa_review': '结果审核',
    'qa_chart': '结果可视化',
    'qa_export': '导出报告',
}

def get_display_name(step_key: str) -> str:
    """获取步骤的中文名称，未知步骤直接返回 step_key。"""
    return TASK_TYPE_DISPLAY.get(step_key, step_key)


# ============================================================================
# 权限校验
# ============================================================================

def check_task_permission(user, permission_code: str) -> bool:
    """
    检查用户是否拥有指定任务权限。
    复用 core.api.common.check_permission 的统一逻辑（role 分级 + 旧 RBAC 兜底）。
    """
    from core.api.common import check_permission
    return check_permission(user, permission_code)


# ============================================================================
# 任务生命周期：ActivityLog 写入
# ============================================================================

def log_task_start(project_id: int, step_key: str, task_id: int, user) -> None:
    """记录任务启动操作日志。"""
    try:
        ActivityLog.objects.create(
            project_id=project_id,
            operation_type=f'task_start_{step_key}',
            operation_detail={
                'task_type': get_display_name(step_key),
                'task_id': task_id,
            },
            created_by=user,
        )
    except Exception as e:
        logger.warning(f"[task_service] 写入 ActivityLog(task_start) 失败: {e}")


def log_task_stop(task: Task, user) -> None:
    """记录任务停止操作日志。"""
    try:
        ActivityLog.objects.create(
            project=task.project,
            operation_type='task_stop',
            operation_detail={
                'task_type': get_display_name(task.task_type),
                'task_id': task.id,
            },
            created_by=user,
        )
    except Exception as e:
        logger.warning(f"[task_service] 写入 ActivityLog(task_stop) 失败: {e}")


def log_task_resume(task: Task, new_task_id: int, user) -> None:
    """记录任务恢复操作日志。"""
    try:
        ActivityLog.objects.create(
            project=task.project,
            operation_type='task_resume',
            operation_detail={
                'task_type': get_display_name(task.task_type),
                'task_id': new_task_id,
                'from_task_id': task.id,
            },
            created_by=user,
        )
    except Exception as e:
        logger.warning(f"[task_service] 写入 ActivityLog(task_resume) 失败: {e}")


# ============================================================================
# 任务启动入口（供 TaskViewSet.perform_create 调用）
# ============================================================================

def start_task(project_id: int, task_type: str, config: dict, user) -> Task:
    """
    启动任务的统一入口。

    流程：
    1. 权限校验
    2. 使用 task_type 作为规范 step_key
    3. 调用 TaskScheduler.start_step
    4. 写入 ActivityLog

    Args:
        project_id: 项目 ID
        task_type: 前端传入的规范步骤 key
        config: 任务配置（ai_model、criteria 等）
        user: 操作用户

    Returns:
        创建的 Task 对象

    Raises:
        PermissionError: 缺少 task.start 权限
        ValueError: 调度器抛出的业务错误
    """
    if not check_task_permission(user, 'task.start'):
        raise PermissionError("缺少权限：task.start，请联系管理员")

    step_key = task_type

    from core.scheduler import TaskScheduler
    from core.services.access_policy import ProjectAccessPolicy

    if ProjectAccessPolicy.get_project(user, project_id) is None:
        raise PermissionError("无权访问该项目或项目不存在")
    scheduler = TaskScheduler(project_id)
    task = scheduler.start_step(step_key, user.id, **config)

    log_task_start(project_id, step_key, task.id, user)

    return task


def stop_task(task: Task, user) -> bool:
    """
    停止任务的统一入口。

    Args:
        task: 要停止的 Task 对象
        user: 操作用户

    Returns:
        True 表示停止成功
    """
    from core.scheduler import TaskScheduler
    scheduler = TaskScheduler(task.project.id)
    success = scheduler.stop_task(task.id)

    if success:
        log_task_stop(task, user)

    return success


def resume_task(task: Task, user) -> Task:
    """
    恢复任务的统一入口。

    Args:
        task: 要恢复的 Task 对象（status == 'stopped'）
        user: 操作用户

    Returns:
        新创建的 Task 对象

    Raises:
        ValueError: 任务状态不允许恢复
        Exception: 调度器抛出的其他错误
    """
    from core.scheduler import TaskScheduler
    scheduler = TaskScheduler(task.project.id)
    new_task = scheduler.resume_task(task.id)

    log_task_resume(task, new_task.id, user)

    return new_task
