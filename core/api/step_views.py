from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from django.utils import timezone

from ..models import StageStep, Task
from ..serializers import StageStepSerializer, TaskSerializer
from .common import require_permission
from ..services.access_policy import ProjectAccessPolicy
from ..workflow.domain.statuses import StageStepStatus, TaskStatus
from ..workflow.services.lifecycle import InvalidStateTransition, transition_step


class StageStepViewSet(viewsets.ModelViewSet):
    serializer_class = StageStepSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return StageStep.objects.filter(
            stage__project__in=ProjectAccessPolicy.visible_projects(self.request.user)
        )

    @action(detail=True, methods=['post'])
    @require_permission('step.start')
    def start(self, request, pk=None):
        from ..scheduler import TaskScheduler

        step = self.get_object()
        stage = step.stage
        project = stage.project

        if not ProjectAccessPolicy.can_access_project(request.user, project):
            return Response({"error": "无权操作该项目"}, status=status.HTTP_403_FORBIDDEN)

        if step.status == StageStepStatus.IN_PROGRESS:
            return Response({"error": "步骤正在运行中"}, status=status.HTTP_400_BAD_REQUEST)

        if step.status in (StageStepStatus.COMPLETED, StageStepStatus.SKIPPED):
            return Response({"error": "步骤已完成，请勿重复执行"}, status=status.HTTP_400_BAD_REQUEST)

        config = request.data.get('config', {})

        if step.step_key == 'criteria' and 'criteria' in config:
            from core.screening.services.configuration_service import ScreeningConfigurationService
            ScreeningConfigurationService.save_start_criteria(step, config['criteria'])

        scheduler = TaskScheduler(project.id)

        try:
            task = scheduler.start_step(step.step_key, request.user.id, **config)

            step.refresh_from_db()
            # 异步 worker 若已经完成，不允许 API 用过期对象覆盖终态。
            if step.status in (
                StageStepStatus.PENDING,
                StageStepStatus.STOPPED,
                StageStepStatus.FAILED,
            ):
                transition_step(
                    step,
                    StageStepStatus.IN_PROGRESS,
                    updates={'started_at': timezone.now(), 'completed_at': None},
                )

            return Response({"message": f"步骤 {step.name} 已启动", "task": TaskSerializer(task).data})
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": f"启动失败: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        from ..scheduler import TaskScheduler

        step = self.get_object()
        stage = step.stage
        project = stage.project

        if not ProjectAccessPolicy.can_access_project(request.user, project):
            return Response({"error": "无权操作该项目"}, status=status.HTTP_403_FORBIDDEN)

        if step.status != StageStepStatus.IN_PROGRESS:
            return Response({"error": "步骤未在运行"}, status=status.HTTP_400_BAD_REQUEST)

        running_task = Task.objects.filter(
            project=project,
            task_type=step.step_key,
            status__in=(TaskStatus.QUEUING, TaskStatus.PENDING, TaskStatus.RUNNING),
        ).order_by('-created_at').first()

        if not running_task:
            transition_step(
                step,
                StageStepStatus.STOPPED,
                updates={'completed_at': timezone.now()},
            )
            return Response({"message": "步骤已停止"})

        scheduler = TaskScheduler(project.id)
        success = scheduler.stop_task(running_task.id)

        if success:
            transition_step(
                step,
                StageStepStatus.STOPPED,
                updates={'completed_at': timezone.now()},
            )
            return Response({"message": "步骤已停止"})
        return Response({"error": "停止失败"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    @require_permission('step.skip')
    def skip(self, request, pk=None):
        step = self.get_object()

        if not step.can_skip:
            return Response({"error": "该步骤不允许跳过"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            transition_step(
                step,
                StageStepStatus.SKIPPED,
                updates={'completed_at': timezone.now()},
            )
        except InvalidStateTransition as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(StageStepSerializer(step).data)

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        step = self.get_object()
        try:
            transition_step(
                step,
                StageStepStatus.COMPLETED,
                updates={'completed_at': timezone.now()},
            )
        except InvalidStateTransition as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(StageStepSerializer(step).data)

    @action(detail=True, methods=['patch'])
    def update_metadata(self, request, pk=None):
        step = self.get_object()
        metadata = request.data.get('metadata', {})

        if step.step_key in ('criteria', 'field_extraction'):
            from core.screening.services.configuration_service import ScreeningConfigurationService
            ScreeningConfigurationService.update_step_metadata(step, metadata, request.user)
        else:
            step.metadata = step.metadata or {}
            step.metadata.update(metadata)
            step.save(update_fields=['metadata'])
        return Response(StageStepSerializer(step).data)
