from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from django.db.models import Q
from django.utils import timezone

from ..models import ActivityLog, DataFile, ProjectStage, StageStep, UserPermission
from ..serializers import DataFileSerializer


class DataFileViewSet(viewsets.ModelViewSet):
    serializer_class = DataFileSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            qs = DataFile.objects.all()
        else:
            qs = DataFile.objects.filter(project__owner=user)

        qp = self.request.query_params
        project_id = qp.get('project')
        if project_id:
            qs = qs.filter(project_id=project_id)

        stage_id = qp.get('stage')
        if stage_id:
            qs = qs.filter(stage_id=stage_id)

        step_id = qp.get('step')
        if step_id:
            qs = qs.filter(step_id=step_id)

        data_category = qp.get('data_category')
        if data_category:
            qs = qs.filter(data_category=data_category)

        return qs.select_related('stage', 'step', 'created_by').prefetch_related('versions')

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        total = qs.count()
        qp = request.query_params
        try:
            limit = int(qp.get('limit', 200))
            offset = int(qp.get('offset', 0))
        except (TypeError, ValueError):
            limit = 200
            offset = 0
        qs = qs[offset : offset + limit]
        serializer = self.get_serializer(qs, many=True)
        return Response({'total': total, 'results': serializer.data})

    def perform_create(self, serializer):
        user = self.request.user
        permission_code = 'file.upload'

        if not user.is_superuser:
            has_perm = UserPermission.objects.filter(
                user=user,
                permission__code=permission_code,
            ).filter(
                Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
            ).exists()

            if not has_perm:
                raise PermissionDenied(f"缺少权限：{permission_code}")

        uploaded_file = self.request.FILES.get('file')
        if uploaded_file and not serializer.validated_data.get('filename'):
            serializer.validated_data['filename'] = uploaded_file.name

        project = serializer.validated_data.get('project')
        if project:
            project_id = project.id
            data_category = serializer.validated_data.get('data_category', 'input')

            if data_category == 'input' and not serializer.validated_data.get('stage'):
                try:
                    screen1_stage = ProjectStage.objects.get(project_id=project_id, stage_key='SCREEN_1')
                    serializer.validated_data['stage'] = screen1_stage
                    try:
                        parse_step = StageStep.objects.get(stage=screen1_stage, step_key='parse')
                        serializer.validated_data['step'] = parse_step
                    except StageStep.DoesNotExist:
                        pass
                except ProjectStage.DoesNotExist:
                    pass

        if uploaded_file and not serializer.validated_data.get('file_size'):
            serializer.validated_data['file_size'] = uploaded_file.size

        if uploaded_file and not serializer.validated_data.get('file_type'):
            import mimetypes

            file_type, _ = mimetypes.guess_type(uploaded_file.name)
            if file_type:
                serializer.validated_data['file_type'] = file_type

        _filename = uploaded_file.name if uploaded_file else serializer.validated_data.get('filename', '')
        _project = serializer.validated_data.get('project')

        serializer.save(created_by=user)

        if _project:
            ActivityLog.objects.create(
                project=_project,
                operation_type='file_add',
                operation_detail={'filename': _filename},
                created_by=user,
            )

    def perform_destroy(self, instance):
        from ..services import reset_downstream_on_input_delete

        if instance.data_category == 'input' and instance.project:
            reset_downstream_on_input_delete(instance.project, self.request.user)

        ActivityLog.objects.create(
            project=instance.project,
            operation_type='file_delete',
            operation_detail={'filename': instance.filename},
            created_by=self.request.user,
        )
        instance.delete()

