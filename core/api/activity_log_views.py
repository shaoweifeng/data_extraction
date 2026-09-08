from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from ..models import ActivityLog
from ..serializers import ActivityLogSerializer
from ..services.access_policy import ProjectAccessPolicy


class ActivityLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ActivityLogSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = ActivityLog.objects.filter(
            project__in=ProjectAccessPolicy.visible_projects(self.request.user)
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
