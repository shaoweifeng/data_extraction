from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ..models import ActivityLog, Project, ProjectStage, StageStep
from ..serializers import ProjectSerializer, ProjectStageSerializer


class ProjectViewSet(viewsets.ModelViewSet):
    serializer_class = ProjectSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Project.objects.for_user(self.request.user)

    def perform_create(self, serializer):
        from ..services import check_create_permission, initialize_project

        user = self.request.user

        try:
            check_create_permission(user)
        except PermissionError as e:
            raise PermissionDenied(str(e))

        project = serializer.save(owner=user)
        initialize_project(project, user)

    def perform_destroy(self, instance):
        from ..services import delete_project

        try:
            delete_project(instance, self.request.user)
        except PermissionError as e:
            raise PermissionDenied(str(e))

    @action(detail=True, methods=['get'])
    def stages(self, request, pk=None):
        project = self.get_object()
        stages = project.stages.all().prefetch_related('steps')
        return Response(ProjectStageSerializer(stages, many=True).data)

    @action(detail=True, methods=['post'])
    def clear_ai_screen_results(self, request, pk=None):
        from ..services import clear_ai_screen_outputs

        project = self.get_object()
        result = clear_ai_screen_outputs(project, request.user)
        return Response({'message': result['message']})

    @action(detail=True, methods=['get'])
    def ai_screen_stats(self, request, pk=None):
        from ..services import get_ai_screen_stats

        project = self.get_object()
        return Response(get_ai_screen_stats(project))

    @action(detail=True, methods=['get'])
    def get_prompt(self, request, pk=None):
        from ..services import get_prompt

        project = self.get_object()
        return Response(get_prompt(project))

    @action(detail=True, methods=['post'])
    def log_model_select(self, request, pk=None):
        project = self.get_object()
        model_id = request.data.get('model_id', '')
        model_name = request.data.get('model_name', model_id)
        ActivityLog.objects.create(
            project=project,
            operation_type='model_select',
            operation_detail={'model_id': model_id, 'model_name': model_name},
            created_by=request.user,
        )
        return Response({'ok': True})

    @action(detail=True, methods=['get'])
    def extraction_fields(self, request, pk=None):
        project = self.get_object()
        try:
            stage = ProjectStage.objects.get(project=project, stage_key='SCREEN_1')
            step = StageStep.objects.get(stage=stage, step_key='field_extraction')
            fields = (step.metadata or {}).get('fields', [])
            return Response({'fields': fields})
        except (ProjectStage.DoesNotExist, StageStep.DoesNotExist):
            return Response({'fields': []})

    @action(detail=True, methods=['post'])
    def save_prompt(self, request, pk=None):
        from ..services import save_prompt

        project = self.get_object()
        custom_prompt = request.data.get('custom_prompt', '').strip()
        use_custom = request.data.get('use_custom_prompt', True)

        try:
            result = save_prompt(project, custom_prompt, use_custom, request.user)
            return Response(result)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def reset_prompt(self, request, pk=None):
        from ..services import reset_prompt

        project = self.get_object()
        return Response(reset_prompt(project, request.user))

