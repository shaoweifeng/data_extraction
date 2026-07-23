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
            qs = ActivityLog.objects.filter(project__owner=user)

        project_id = self.request.query_params.get('project')
        if project_id:
            qs = qs.filter(project_id=project_id)
        operation_type = self.request.query_params.get('operation_type')
        if operation_type:
            qs = qs.filter(operation_type=operation_type)
        return qs.order_by('-created_at')

