from django.db import models as db_models
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from ..models import ActivityLog
from ..serializers import ActivityLogSerializer


class ActivityLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ActivityLogSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            qs = ActivityLog.objects.all()
        else:
            # admin 角色也可查看所有日志
            from core.models import UserProfile
            profile = getattr(user, 'profile', None)
            if profile and profile.role in ('admin',):
                qs = ActivityLog.objects.all()
            else:
                # 自己创建的项目 + 被授权的项目
                from core.models import UserPermission
                permitted_ids = list(UserPermission.objects.filter(
                    user=user
                ).values_list('project_id', flat=True))
                qs = ActivityLog.objects.filter(
                    db_models.Q(project__owner=user) |
                    db_models.Q(project_id__in=permitted_ids)
                )

        project_id = self.request.query_params.get('project')
        if project_id:
            qs = qs.filter(project_id=project_id)
        operation_type = self.request.query_params.get('operation_type')
        if operation_type:
            qs = qs.filter(operation_type=operation_type)

        limit = self.request.query_params.get('limit')
        if limit:
            try:
                qs = qs.order_by('-created_at')[:int(limit)]
                return qs
            except (ValueError, TypeError):
                pass

        return qs.order_by('-created_at')
