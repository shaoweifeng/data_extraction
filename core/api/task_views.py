from rest_framework import serializers as drf_serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from django.utils import timezone

from ..models import ActivityLog, Task, UserPermission
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
        from ..scheduler import TaskScheduler

        user = self.request.user

        if not user.is_superuser and not user.is_staff:
            permission_code = 'task.start'
            from django.db.models import Q

            has_perm = UserPermission.objects.filter(
                user=user,
                permission__code=permission_code,
            ).filter(
                Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
            ).exists()

            if not has_perm:
                raise drf_serializers.ValidationError(f"缺少权限：{permission_code}，请联系管理员")

        task_type_map = {
            'reference_parsing': 'parse',
            'deduplication': 'dedup',
            'ai_screening': 'ai_screen',
            'result_aggregation': 'export',
        }

        task_type = serializer.validated_data.get('task_type', '')
        step_key = task_type_map.get(task_type, task_type)
        config = serializer.validated_data.get('config', {})

        project_id = serializer.validated_data.get('project').id if 'project' in serializer.validated_data else None

        if not project_id:
            raise drf_serializers.ValidationError("缺少项目ID")

        scheduler = TaskScheduler(project_id)

        try:
            task = scheduler.start_step(step_key, user.id, **config)
            serializer.instance = task

            op_type = f'task_start_{step_key}'
            task_type_display = {
                'parse': '文献解析',
                'dedup': '文献去重',
                'ai_screen': 'AI初筛',
                'export': '结果归纳',
            }.get(step_key, step_key)
            ActivityLog.objects.create(
                project_id=project_id,
                operation_type=op_type,
                operation_detail={'task_type': task_type_display, 'task_id': task.id},
                created_by=user,
            )
        except ValueError as e:
            raise drf_serializers.ValidationError(str(e))
        except Exception as e:
            raise drf_serializers.ValidationError(f"启动失败: {str(e)}")

    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        from ..scheduler import TaskScheduler

        task = self.get_object()

        if task.status not in ['running', 'pending']:
            return Response({"error": "任务未在运行"}, status=status.HTTP_400_BAD_REQUEST)

        scheduler = TaskScheduler(task.project.id)
        success = scheduler.stop_task(task.id)

        if success:
            task_type_display = {
                'parse': '文献解析',
                'dedup': '文献去重',
                'ai_screen': 'AI初筛',
                'export': '结果归纳',
                'field_extraction': '提取字段',
            }.get(task.task_type, task.task_type)
            ActivityLog.objects.create(
                project=task.project,
                operation_type='task_stop',
                operation_detail={'task_type': task_type_display, 'task_id': task.id},
                created_by=request.user,
            )
            return Response({"message": "任务已停止"})

        return Response({"error": "停止失败"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    def resume(self, request, pk=None):
        from ..scheduler import TaskScheduler

        task = self.get_object()

        if task.status != 'stopped':
            return Response({"error": "只能恢复已停止的任务"}, status=status.HTTP_400_BAD_REQUEST)

        scheduler = TaskScheduler(task.project.id)

        try:
            new_task = scheduler.resume_task(task.id)
            task_type_display = {
                'parse': '文献解析',
                'dedup': '文献去重',
                'ai_screen': 'AI初筛',
                'export': '结果归纳',
                'field_extraction': '提取字段',
            }.get(task.task_type, task.task_type)
            ActivityLog.objects.create(
                project=task.project,
                operation_type='task_resume',
                operation_detail={'task_type': task_type_display, 'task_id': new_task.id},
                created_by=request.user,
            )
            return Response({"message": "任务已恢复", "task": TaskSerializer(new_task).data})
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'])
    def progress(self, request, pk=None):
        from ..monitoring import get_task_progress

        task = self.get_object()
        return Response(get_task_progress(task.id))

    @action(detail=True, methods=['get'])
    def logs(self, request, pk=None):
        from pathlib import Path

        task = self.get_object()
        log_file_path = task.log_file

        if log_file_path and Path(log_file_path).exists():
            try:
                with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
                last_lines = lines[-200:] if len(lines) > 200 else lines
                return Response(
                    {'log_content': ''.join(last_lines), 'total_lines': len(lines), 'returned_lines': len(last_lines)}
                )
            except Exception as e:
                return Response({'log_content': f'读取日志失败: {e}'})

        return Response({'log_content': task.logs or '任务正在初始化，日志即将生成...'})

    @action(detail=True, methods=['get'])
    def tail(self, request, pk=None):
        from ..monitoring import LogReader

        task = self.get_object()
        reader = LogReader(task.id)

        last_n = int(request.query_params.get('n', 50))
        lines = reader.tail_logs(last_n)

        return Response({"lines": lines, "log_content": '\n'.join(lines) if lines else '暂无日志'})

