from functools import wraps

from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response

from ..models import UserPermission


# 普通 user 角色默认拥有的权限码（与 project_service._check_permission 保持一致）
USER_DEFAULT_PERMISSIONS = {
    'project.create', 'project.view', 'project.view_own', 'project.edit', 'project.edit_own',
    'project.delete_own',
    'stage.view', 'stage.start', 'stage.stop',
    'step.view', 'step.start', 'step.stop', 'step.complete', 'step.skip',
    'file.upload', 'file.download', 'file.delete',
    'task.view', 'task.create', 'task.start', 'task.stop',
}


def check_permission(user, permission_code: str) -> bool:
    """
    统一权限检查（新 role 分级 + 旧 RBAC 兜底）。

    优先级：
      1. is_superuser → 通过
      2. profile.role == 'admin' → 通过（全权限）
      3. profile.role == 'user' + permission_code 在 USER_DEFAULT_PERMISSIONS → 通过
      4. 旧 plat_userpermission 表有对应记录 → 通过（历史数据兼容）
    """
    if user.is_superuser:
        return True

    profile = getattr(user, 'profile', None)
    if profile and profile.role == 'admin':
        return True

    if profile and profile.role == 'user' and permission_code in USER_DEFAULT_PERMISSIONS:
        return True

    # 兜底：旧 RBAC 表
    return UserPermission.objects.filter(
        user=user,
        permission__code=permission_code,
    ).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
    ).exists()


def require_permission(permission_code):
    """装饰器：检查 permission_code，不通过返回 403。"""
    def decorator(func):
        @wraps(func)
        def wrapper(self, request, *args, **kwargs):
            if not check_permission(request.user, permission_code):
                return Response(
                    {"error": f"缺少权限：{permission_code}"},
                    status=status.HTTP_403_FORBIDDEN,
                )
            return func(self, request, *args, **kwargs)
        return wrapper
    return decorator
