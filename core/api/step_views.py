from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from django.utils import timezone

from ..models import ActivityLog, StageStep, Task
from ..serializers import StageStepSerializer, TaskSerializer
from .common import require_permission


class StageStepViewSet(viewsets.ModelViewSet):
    serializer_class = StageStepSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            return StageStep.objects.all()
        return StageStep.objects.filter(stage__project__owner=user)

    @action(detail=True, methods=['post'])
    @require_permission('step.start')
    def start(self, request, pk=None):
        from ..scheduler import TaskScheduler

        step = self.get_object()
        stage = step.stage
        project = stage.project

        if project.owner != request.user and not request.user.is_superuser:
            return Response({"error": "无权操作该项目"}, status=status.HTTP_403_FORBIDDEN)

        if step.status == 'in_progress':
            return Response({"error": "步骤正在运行中"}, status=status.HTTP_400_BAD_REQUEST)

        if step.status == 'completed':
            return Response({"error": "步骤已完成，请勿重复执行"}, status=status.HTTP_400_BAD_REQUEST)

        config = request.data.get('config', {})

        if step.step_key == 'criteria' and 'criteria' in config:
            step.metadata = step.metadata or {}
            step.metadata['criteria'] = config['criteria']
            step.save()

        scheduler = TaskScheduler(project.id)

        try:
            task = scheduler.start_step(step.step_key, request.user.id, **config)

            step.status = 'in_progress'
            step.started_at = timezone.now()
            step.save()

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

        if project.owner != request.user and not request.user.is_superuser:
            return Response({"error": "无权操作该项目"}, status=status.HTTP_403_FORBIDDEN)

        if step.status != 'in_progress':
            return Response({"error": "步骤未在运行"}, status=status.HTTP_400_BAD_REQUEST)

        running_task = Task.objects.filter(project=project, task_type=step.step_key, status='running').first()

        if not running_task:
            step.status = 'stopped'
            step.save()
            return Response({"message": "步骤已停止"})

        scheduler = TaskScheduler(project.id)
        success = scheduler.stop_task(running_task.id)

        if success:
            step.status = 'stopped'
            step.completed_at = timezone.now()
            step.save()
            return Response({"message": "步骤已停止"})
        return Response({"error": "停止失败"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    @require_permission('step.skip')
    def skip(self, request, pk=None):
        step = self.get_object()

        if not step.can_skip:
            return Response({"error": "该步骤不允许跳过"}, status=status.HTTP_400_BAD_REQUEST)

        step.status = 'skipped'
        step.completed_at = timezone.now()
        step.save()

        return Response(StageStepSerializer(step).data)

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        step = self.get_object()
        step.status = 'completed'
        step.completed_at = timezone.now()
        step.save()
        return Response(StageStepSerializer(step).data)

    @action(detail=True, methods=['patch'])
    def update_metadata(self, request, pk=None):
        step = self.get_object()
        metadata = request.data.get('metadata', {})

        if step.step_key == 'criteria' and 'criteria' in metadata:
            old_criteria = set((step.metadata or {}).get('criteria', []))
            new_criteria = set(metadata['criteria'])
            project = step.stage.project
            for c in (new_criteria - old_criteria):
                ActivityLog.objects.create(
                    project=project,
                    operation_type='criteria_add',
                    operation_detail={'criteria': c},
                    created_by=request.user,
                )
            for c in (old_criteria - new_criteria):
                ActivityLog.objects.create(
                    project=project,
                    operation_type='criteria_delete',
                    operation_detail={'criteria': c},
                    created_by=request.user,
                )

        if step.step_key == 'field_extraction' and 'fields' in metadata:
            old_fields = {(f['name'], f['definition']) for f in (step.metadata or {}).get('fields', [])}
            new_fields = {(f['name'], f['definition']) for f in metadata['fields']}
            project = step.stage.project
            for f in (new_fields - old_fields):
                ActivityLog.objects.create(
                    project=project,
                    operation_type='field_extraction_add',
                    operation_detail={'field_name': f[0], 'field_definition': f[1]},
                    created_by=request.user,
                )
            for f in (old_fields - new_fields):
                ActivityLog.objects.create(
                    project=project,
                    operation_type='field_extraction_delete',
                    operation_detail={'field_name': f[0], 'field_definition': f[1]},
                    created_by=request.user,
                )

        step.metadata = step.metadata or {}
        step.metadata.update(metadata)
        step.save()
        return Response(StageStepSerializer(step).data)


