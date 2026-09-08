"""项目级对象访问策略。

当前产品没有项目协作者：
- superuser / role=admin 可访问和管理全部项目；
- 普通用户只能访问和管理自己创建的项目。

所有项目下级资源必须通过 ``visible_projects`` 反向过滤，避免按裸主键
查询后遗漏对象级权限校验。
"""

from django.core.exceptions import PermissionDenied

from core.models import Project


class ProjectAccessPolicy:
    """项目访问的单一事实来源。"""

    @staticmethod
    def is_platform_admin(user) -> bool:
        if not user or not user.is_authenticated:
            return False
        profile = getattr(user, 'profile', None)
        return bool(user.is_superuser or (profile and profile.role == 'admin'))

    @classmethod
    def visible_projects(cls, user):
        if not user or not user.is_authenticated:
            return Project.objects.none()
        return Project.objects.for_user(user)

    @classmethod
    def get_project(cls, user, project_id):
        """返回用户可访问的项目；不可访问和不存在统一返回 None。"""
        if not project_id:
            return None
        return cls.visible_projects(user).filter(pk=project_id).first()

    @classmethod
    def require_project(cls, user, project_or_id):
        project_id = getattr(project_or_id, 'pk', project_or_id)
        project = cls.get_project(user, project_id)
        if project is None:
            raise PermissionDenied('无权访问该项目或项目不存在')
        return project

    @classmethod
    def can_access_project(cls, user, project) -> bool:
        if project is None:
            return False
        return cls.visible_projects(user).filter(pk=project.pk).exists()
