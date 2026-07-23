from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from django.db.models import Q
from django.utils import timezone

from ..models import ActivityLog, DataFile, Project, ProjectStage, StageStep, UserPermission
from ..serializers import ProjectSerializer, ProjectStageSerializer


class ProjectViewSet(viewsets.ModelViewSet):
    serializer_class = ProjectSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Project.objects.for_user(self.request.user)

    def perform_create(self, serializer):
        from ..step_config import get_stage_definition

        user = self.request.user
        permission_code = 'project.create'

        if not user.is_superuser:
            has_perm = UserPermission.objects.filter(
                user=user,
                permission__code=permission_code,
            ).filter(
                Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
            ).exists()

            if not has_perm:
                raise PermissionDenied(f"缺少权限：{permission_code}")

        if not user.is_superuser and hasattr(user, 'profile'):
            quota = user.profile.quota_projects
            if quota >= 0:
                current_count = Project.objects.filter(owner=user).count()
                if current_count >= quota:
                    raise PermissionDenied(f"已达项目配额上限({quota}个)")

        project = serializer.save(owner=user)

        stage_keys = ['SEARCH', 'SCREEN_1', 'SCREEN_2', 'QUALITY', 'EXTRACT', 'META']

        for stage_key in stage_keys:
            stage_def = get_stage_definition(stage_key)

            stage = ProjectStage.objects.create(
                project=project,
                stage_key=stage_key,
                name=stage_def.get("name", stage_key),
                order=stage_def.get("order", 100),
                status="pending",
            )

            for step_def in stage_def.get("steps", []):
                StageStep.objects.create(
                    stage=stage,
                    step_key=step_def["step_key"],
                    name=step_def.get("name", step_def["step_key"]),
                    order=step_def.get("order", 100),
                    can_skip=step_def.get("can_skip", True),
                    status="pending",
                )

    def perform_destroy(self, instance):
        import os
        import shutil

        from django.conf import settings
        from django.db import connection

        user = self.request.user
        permission_code = 'project.delete_own'

        if not user.is_superuser:
            has_perm = UserPermission.objects.filter(
                user=user,
                permission__code=permission_code,
            ).filter(
                Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
            ).exists()

            if not has_perm:
                raise PermissionDenied(f"缺少权限：{permission_code}")

        if instance.owner != user and not user.is_superuser:
            raise PermissionDenied("无权删除该项目")

        try:
            import json

            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO plat_project_history
                        (id, name, slug, description, owner_id, status, metadata, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        name=VALUES(name), slug=VALUES(slug), description=VALUES(description),
                        status=VALUES(status), metadata=VALUES(metadata), updated_at=VALUES(updated_at)
                    """,
                    [
                        instance.id,
                        instance.name,
                        instance.slug,
                        instance.description,
                        instance.owner_id,
                        'deleted',
                        json.dumps(instance.metadata) if instance.metadata else '{}',
                        instance.created_at,
                        instance.updated_at,
                    ],
                )
        except Exception as e:
            print(f"归档项目到历史表失败: {e}")

        try:
            for data_file in instance.files.all():
                if data_file.file:
                    try:
                        path = data_file.file.path
                        if os.path.exists(path):
                            os.remove(path)
                    except Exception as e:
                        print(f"删除文件失败: {e}")
        except Exception as e:
            print(f"清理文件时出错: {e}")

        media_project_dir = os.path.join(settings.MEDIA_ROOT, 'projects', f'project_{instance.id}')
        try:
            if os.path.exists(media_project_dir):
                shutil.rmtree(media_project_dir)
        except Exception as e:
            print(f"删除 media 目录失败: {e}")

        workspace_dir = os.path.join(settings.BASE_DIR, 'workspaces', f'project_{instance.id}')
        try:
            if os.path.exists(workspace_dir):
                shutil.rmtree(workspace_dir)
        except Exception as e:
            print(f"删除 workspace 目录失败: {e}")

        instance.delete()

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

