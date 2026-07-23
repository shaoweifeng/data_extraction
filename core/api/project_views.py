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
        project = self.get_object()

        ai_step = StageStep.objects.filter(
            stage__project=project,
            step_key='ai_screen',
        ).first()

        if ai_step:
            deleted_count, _ = DataFile.objects.filter(
                project=project,
                step=ai_step,
                data_category='output',
            ).delete()

            ActivityLog.objects.create(
                project=project,
                operation_type='task_abandon',
                operation_detail={
                    'task_type': 'AI初筛',
                    'action': 'clear_results',
                    'deleted_count': deleted_count,
                },
                created_by=request.user,
            )
            return Response({'message': f'已清除 {deleted_count} 条筛选结果记录'})

        return Response({'message': '未找到 ai_screen 步骤，无需清除'})

    @action(detail=True, methods=['get'])
    def ai_screen_stats(self, request, pk=None):
        project = self.get_object()
        ai_step = StageStep.objects.filter(
            stage__project=project,
            step_key='ai_screen',
        ).first()
        if not ai_step:
            return Response({'included': 0, 'excluded': 0, 'total': 0})

        qs = DataFile.objects.filter(project=project, step=ai_step, data_category='output')
        total = qs.count()
        included = qs.filter(metadata__decision='included').count()
        excluded = qs.filter(metadata__decision='excluded').count()
        return Response({'included': included, 'excluded': excluded, 'total': total})

    @action(detail=True, methods=['get'])
    def get_prompt(self, request, pk=None):
        from pathlib import Path
        from django.conf import settings

        project = self.get_object()
        custom_prompt = (project.metadata or {}).get('custom_prompt', '')
        use_custom = (project.metadata or {}).get('use_custom_prompt', False)

        prompt_path = Path(settings.BASE_DIR) / "structural_screening/02_screening_ai/prompts/prompt1.txt"
        default_prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ''

        return Response(
            {
                'custom_prompt': custom_prompt,
                'use_custom_prompt': use_custom,
                'default_prompt': default_prompt,
            }
        )

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
        project = self.get_object()
        custom_prompt = request.data.get('custom_prompt', '').strip()
        use_custom = request.data.get('use_custom_prompt', True)

        if use_custom and '{screening_criteria}' not in custom_prompt:
            return Response(
                {'error': 'Prompt 必须包含 {screening_criteria} 占位符'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        project.metadata = project.metadata or {}
        project.metadata['custom_prompt'] = custom_prompt
        project.metadata['use_custom_prompt'] = use_custom
        project.save(update_fields=['metadata'])

        ActivityLog.objects.create(
            project=project,
            operation_type='prompt_set',
            operation_detail={
                'use_custom': use_custom,
                'prompt_length': len(custom_prompt),
                'prompt_preview': custom_prompt[:100] if custom_prompt else '',
            },
            created_by=request.user,
        )

        return Response({'message': '已保存', 'use_custom_prompt': use_custom})

    @action(detail=True, methods=['post'])
    def reset_prompt(self, request, pk=None):
        project = self.get_object()
        project.metadata = project.metadata or {}
        project.metadata['custom_prompt'] = ''
        project.metadata['use_custom_prompt'] = False
        project.save(update_fields=['metadata'])

        ActivityLog.objects.create(
            project=project,
            operation_type='prompt_reset',
            operation_detail={},
            created_by=request.user,
        )

        return Response({'message': '已重置为默认 Prompt'})

