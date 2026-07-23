from rest_framework import serializers as drf_serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ..models import Task
from ..serializers import TaskSerializer


class TaskViewSet(viewsets.ModelViewSet):
    serializer_class = TaskSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user

        if user.is_superuser:
            queryset = Task.objects.all()
        else:
            queryset = Task.objects.filter(project__owner=user)

        project_id = self.request.query_params.get('project')
        if project_id:
            queryset = queryset.filter(project_id=project_id)

        return queryset

    def perform_create(self, serializer):
        from ..services import start_task

        user = self.request.user
        task_type = serializer.validated_data.get('task_type', '')
        config = serializer.validated_data.get('config', {})
        project = serializer.validated_data.get('project')

        if not project:
            raise drf_serializers.ValidationError("缺少项目ID")

        try:
            task = start_task(project.id, task_type, config, user)
            serializer.instance = task
        except PermissionError as e:
            raise drf_serializers.ValidationError(str(e))
        except ValueError as e:
            raise drf_serializers.ValidationError(str(e))
        except Exception as e:
            raise drf_serializers.ValidationError(f"启动失败: {str(e)}")

    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        from ..services import stop_task

        task = self.get_object()

        if task.status not in ['running', 'pending']:
            return Response({"error": "任务未在运行"}, status=status.HTTP_400_BAD_REQUEST)

        success = stop_task(task, request.user)

        if success:
            return Response({"message": "任务已停止"})

        return Response({"error": "停止失败"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    def resume(self, request, pk=None):
        from ..services import resume_task

        task = self.get_object()

        if task.status != 'stopped':
            return Response({"error": "只能恢复已停止的任务"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            new_task = resume_task(task, request.user)
            return Response({"message": "任务已恢复", "task": TaskSerializer(new_task).data})
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'])
    def progress(self, request, pk=None):
        from ..services import get_task_progress

        task = self.get_object()
        return Response(get_task_progress(task.id))

    @action(detail=True, methods=['get'])
    def logs(self, request, pk=None):
        from ..services import read_task_logs

        task = self.get_object()
        return Response(read_task_logs(task.id, last_n=200))

    @action(detail=True, methods=['get'])
    def tail(self, request, pk=None):
        from ..services import tail_task_logs

        task = self.get_object()
        last_n = int(request.query_params.get('n', 50))
        lines = tail_task_logs(task.id, last_n=last_n)

        return Response({"lines": lines, "log_content": '\n'.join(lines) if lines else '暂无日志'})
