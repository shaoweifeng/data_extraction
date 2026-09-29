from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ..models import ActivityLog, Project
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
    def ai_screen_inputs(self, request, pk=None):
        """Return a bounded, database-backed page of references awaiting screening."""
        from core.screening.models import ScreeningCorpus, ScreeningRun
        from core.screening.services.screening_run_service import (
            _current_dedup_run,
            run_input_references,
        )

        project = self.get_object()
        try:
            limit = min(100, max(1, int(request.query_params.get('limit', 50))))
            offset = max(0, int(request.query_params.get('offset', 0)))
        except (TypeError, ValueError):
            return Response({'error': 'limit 和 offset 必须是整数'}, status=status.HTTP_400_BAD_REQUEST)

        corpus = ScreeningCorpus.objects.filter(project=project).first()
        if corpus is None or corpus.active_reference_count == 0:
            return Response({'total': 0, 'results': []})

        dedup_run = _current_dedup_run(corpus)
        references = run_input_references(corpus, dedup_run)
        run = ScreeningRun.objects.filter(
            project=project,
            corpus_revision=corpus.revision,
            dedup_run=dedup_run,
        ).order_by('-created_at').first()
        if run is not None:
            pending_ids = run.results.exclude(status='completed').values('reference_id')
            references = references.filter(id__in=pending_ids)

        total = references.count()
        page = references.values(
            'id', 'title', 'publication_year', 'journal', 'doi',
        )[offset:offset + limit]
        return Response({
            'total': total,
            'results': [
                {
                    'reference_id': item['id'],
                    'title': item['title'] or f"文献 #{item['id']}",
                    'year': item['publication_year'],
                    'journal': item['journal'],
                    'doi': item['doi'],
                }
                for item in page
            ],
        })

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
        from core.screening.services.configuration_service import ScreeningConfigurationService
        return Response({'fields': ScreeningConfigurationService.extraction_fields(project)})

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
