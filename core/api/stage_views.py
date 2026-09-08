from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from django.db import transaction
from django.utils import timezone

from ..models import ProjectStage, Task
from ..serializers import ProjectStageSerializer, TaskSerializer
from .common import require_permission
from ..services.access_policy import ProjectAccessPolicy
from ..workflow.domain.statuses import ProjectStageStatus, StageStepStatus, TaskStatus
from ..workflow.services.lifecycle import InvalidStateTransition, transition_stage, transition_step


class ProjectStageViewSet(viewsets.ModelViewSet):
    serializer_class = ProjectStageSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return ProjectStage.objects.filter(
            project__in=ProjectAccessPolicy.visible_projects(self.request.user)
        )

    @action(detail=True, methods=['post'])
    @require_permission('stage.start')
    def start(self, request, pk=None):
        from ..scheduler import TaskScheduler

        stage = self.get_object()
        project = stage.project

        if not ProjectAccessPolicy.can_access_project(request.user, project):
            return Response({"error": "无权操作该项目"}, status=status.HTTP_403_FORBIDDEN)

        config = request.data.get('config', {})
        scheduler = TaskScheduler(project.id)

        try:
            task = scheduler.start_stage(stage.stage_key, request.user.id, **config)
            stage.refresh_from_db()
            if stage.status in (
                ProjectStageStatus.PENDING,
                ProjectStageStatus.STOPPED,
                ProjectStageStatus.FAILED,
            ):
                transition_stage(
                    stage,
                    ProjectStageStatus.IN_PROGRESS,
                    updates={'started_at': timezone.now(), 'completed_at': None},
                )
            return Response({"message": f"阶段 {stage.name} 已启动", "task": TaskSerializer(task).data})
        except InvalidStateTransition as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": f"启动失败: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        from ..scheduler import TaskScheduler

        stage = self.get_object()
        project = stage.project

        if not ProjectAccessPolicy.can_access_project(request.user, project):
            return Response({"error": "无权操作该项目"}, status=status.HTTP_403_FORBIDDEN)

        running_task = Task.objects.filter(
            project=project,
            task_type=stage.stage_key,
            status__in=(TaskStatus.QUEUING, TaskStatus.PENDING, TaskStatus.RUNNING),
        ).order_by('-created_at').first()

        if not running_task:
            return Response({"error": "没有正在运行的任务"}, status=status.HTTP_400_BAD_REQUEST)

        scheduler = TaskScheduler(project.id)
        success = scheduler.stop_task(running_task.id)

        if success:
            transition_stage(
                stage,
                ProjectStageStatus.STOPPED,
                updates={'completed_at': timezone.now()},
            )
            return Response({"message": "阶段已停止"})
        return Response({"error": "停止失败"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    def skip(self, request, pk=None):
        stage = self.get_object()

        from ..step_config import get_step_config

        config = get_step_config(stage.stage_key)

        if not config.get("can_skip", False):
            return Response({"error": "该阶段不允许跳过"}, status=status.HTTP_400_BAD_REQUEST)

        now = timezone.now()
        try:
            with transaction.atomic():
                transition_stage(
                    stage,
                    ProjectStageStatus.SKIPPED,
                    updates={'completed_at': now},
                )
                for step in stage.steps.all():
                    transition_step(
                        step,
                        StageStepStatus.SKIPPED,
                        updates={'completed_at': now},
                    )
        except InvalidStateTransition as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(ProjectStageSerializer(stage).data)
