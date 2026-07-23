from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from django.utils import timezone

from ..models import ProjectStage, Task
from ..serializers import ProjectStageSerializer, TaskSerializer
from .common import require_permission


class ProjectStageViewSet(viewsets.ModelViewSet):
    serializer_class = ProjectStageSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            return ProjectStage.objects.all()
        return ProjectStage.objects.filter(project__owner=user)

    @action(detail=True, methods=['post'])
    @require_permission('stage.start')
    def start(self, request, pk=None):
        from ..scheduler import TaskScheduler

        stage = self.get_object()
        project = stage.project

        if project.owner != request.user and not request.user.is_superuser:
            return Response({"error": "无权操作该项目"}, status=status.HTTP_403_FORBIDDEN)

        config = request.data.get('config', {})
        scheduler = TaskScheduler(project.id)

        try:
            task = scheduler.start_stage(stage.stage_key, request.user.id, **config)
            return Response({"message": f"阶段 {stage.name} 已启动", "task": TaskSerializer(task).data})
        except Exception as e:
            return Response({"error": f"启动失败: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        from ..scheduler import TaskScheduler

        stage = self.get_object()
        project = stage.project

        if project.owner != request.user and not request.user.is_superuser:
            return Response({"error": "无权操作该项目"}, status=status.HTTP_403_FORBIDDEN)

        running_task = Task.objects.filter(project=project, task_type=stage.stage_key, status='running').first()

        if not running_task:
            return Response({"error": "没有正在运行的任务"}, status=status.HTTP_400_BAD_REQUEST)

        scheduler = TaskScheduler(project.id)
        success = scheduler.stop_task(running_task.id)

        if success:
            stage.status = 'stopped'
            stage.save()
            return Response({"message": "阶段已停止"})
        return Response({"error": "停止失败"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    def skip(self, request, pk=None):
        stage = self.get_object()

        from ..step_config import get_step_config

        config = get_step_config(stage.stage_key)

        if not config.get("can_skip", False):
            return Response({"error": "该阶段不允许跳过"}, status=status.HTTP_400_BAD_REQUEST)

        stage.status = 'skipped'
        stage.completed_at = timezone.now()
        stage.save()

        stage.steps.update(status='skipped', completed_at=timezone.now())

        return Response(ProjectStageSerializer(stage).data)

    @action(detail=True, methods=['get'])
    def progress(self, request, pk=None):
        from ..monitoring import ProgressMonitor

        stage = self.get_object()
        monitor = ProgressMonitor(stage.project.id)
        return Response(monitor.get_stage_progress(stage.stage_key))

