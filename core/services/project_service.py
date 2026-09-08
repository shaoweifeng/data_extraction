"""
项目业务服务层

职责：
- 封装项目创建时的阶段/步骤初始化逻辑
- 封装项目删除时的权限校验、文件清理
- 统一项目级权限检查（project.create / project.delete_own）

调用方（project_views.py）只需调用 create_project / delete_project，
不再在 ViewSet 里内联 50+ 行的业务规则。
"""

import logging
import os
import shutil

from django.conf import settings

from core.models import ActivityLog, Project, ProjectStage, StageStep
from core.workflow.domain.statuses import ProjectStageStatus, StageStepStatus

logger = logging.getLogger(__name__)

# 项目初始化时要创建的阶段列表（顺序即 UI 显示顺序）
PROJECT_STAGE_KEYS = ['SEARCH', 'SCREEN_1', 'SCREEN_2', 'QUALITY', 'EXTRACT', 'META']


# ============================================================================
# 权限检查
# ============================================================================

def _check_permission(user, permission_code: str) -> bool:
    """复用 core.api.common.check_permission 的统一逻辑（role 分级 + 旧 RBAC 兜底）。"""
    from core.api.common import check_permission
    return check_permission(user, permission_code)


# ============================================================================
# 创建项目（含阶段/步骤初始化）
# ============================================================================

def initialize_project(project: Project, user) -> None:
    """
    为新建项目初始化所有阶段和步骤。

    权限校验、配额校验由 ViewSet 的 perform_create 在 serializer.save() 前完成；
    本函数只负责在项目对象已存在后初始化结构。

    Args:
        project: 已保存到 DB 的 Project 对象
        user: 创建用户（保留用于未来 ActivityLog）
    """
    from core.step_config import get_stage_definition

    for stage_key in PROJECT_STAGE_KEYS:
        stage_def = get_stage_definition(stage_key)

        stage = ProjectStage.objects.create(
            project=project,
            stage_key=stage_key,
            name=stage_def.get("name", stage_key),
            order=stage_def.get("order", 100),
            status=ProjectStageStatus.PENDING,
        )

        for step_def in stage_def.get("steps", []):
            StageStep.objects.create(
                stage=stage,
                step_key=step_def["step_key"],
                name=step_def.get("name", step_def["step_key"]),
                order=step_def.get("order", 100),
                can_skip=step_def.get("can_skip", True),
                status=StageStepStatus.PENDING,
            )


def check_create_permission(user) -> None:
    """
    检查用户是否有创建项目的权限和配额。

    Raises:
        PermissionError: 缺少权限或超出配额
    """
    if not _check_permission(user, 'project.create'):
        raise PermissionError("缺少权限：project.create")

    if not user.is_superuser and hasattr(user, 'profile'):
        quota = user.profile.quota_projects
        if quota >= 0:
            current_count = Project.objects.filter(owner=user).count()
            if current_count >= quota:
                raise PermissionError(f"已达项目配额上限({quota}个)")


# ============================================================================
# 删除项目（文件清理 + 数据清理）
# ============================================================================

def check_delete_permission(instance: Project, user) -> None:
    """
    检查用户是否有删除该项目的权限。

    Raises:
        PermissionError: 缺少权限或非项目所有者
    """
    if not _check_permission(user, 'project.delete_own'):
        raise PermissionError("缺少权限：project.delete_own")

    profile = getattr(user, 'profile', None)
    is_platform_admin = user.is_superuser or (profile and profile.role == 'admin')
    if instance.owner != user and not is_platform_admin:
        raise PermissionError("无权删除该项目")


def cleanup_project_files(instance: Project) -> None:
    """
    删除项目关联的所有物理文件和目录。

    包括：
    - DataFile 对应的 media 文件
    - media/projects/project_{id}/ 目录
    - workspaces/project_{id}/ 目录
    """
    # 1. 清理 DataFile 对应的文件
    try:
        for data_file in instance.files.all():
            if data_file.file:
                try:
                    path = data_file.file.path
                    if os.path.exists(path):
                        os.remove(path)
                except Exception as e:
                    logger.warning(f"[project_service] 删除文件失败: {e}")
    except Exception as e:
        logger.warning(f"[project_service] 清理 DataFile 时出错: {e}")

    # 2. 清理 media 目录
    media_dir = os.path.join(settings.MEDIA_ROOT, 'projects', f'project_{instance.id}')
    try:
        if os.path.exists(media_dir):
            shutil.rmtree(media_dir)
    except Exception as e:
        logger.warning(f"[project_service] 删除 media 目录失败: {e}")

    # 3. 清理 workspace 目录
    workspace_dir = os.path.join(settings.BASE_DIR, 'workspaces', f'project_{instance.id}')
    try:
        if os.path.exists(workspace_dir):
            shutil.rmtree(workspace_dir)
    except Exception as e:
        logger.warning(f"[project_service] 删除 workspace 目录失败: {e}")


def delete_project(instance: Project, user) -> None:
    """
    删除项目的完整流程：权限校验 → 文件清理 → 删除 DB 记录。

    Args:
        instance: 要删除的 Project 对象
        user: 操作用户

    Raises:
        PermissionError: 权限不足
    """
    check_delete_permission(instance, user)
    cleanup_project_files(instance)
    instance.delete()
