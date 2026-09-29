"""HTTP boundary for transactional screening reference imports."""

from django.conf import settings
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.api.common import check_permission
from core.screening.models import ReferenceImportBatch
from core.screening.services.import_errors import ScreeningImportError
from core.screening.services.import_service import (
    ACTIVE_BATCH_STATUSES,
    batch_payload,
    cancel_import_batch,
    create_add_import,
    delete_failed_import_batch,
    retry_import_batch,
)
from core.services.access_policy import ProjectAccessPolicy


def _error_response(exc: ScreeningImportError):
    return Response({'error': exc.as_dict()}, status=exc.http_status)


class ScreeningImportViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return ReferenceImportBatch.objects.filter(
            project__in=ProjectAccessPolicy.visible_projects(self.request.user),
        ).select_related('project', 'task', 'created_by').prefetch_related('files__source_file')

    def get_object(self):
        from django.shortcuts import get_object_or_404

        return get_object_or_404(self.get_queryset(), pk=self.kwargs['pk'])

    def list(self, request):
        queryset = self.get_queryset()
        project_id = request.query_params.get('project')
        if project_id:
            try:
                project_id = int(project_id)
            except (TypeError, ValueError):
                return _error_response(ScreeningImportError(
                    'invalid_project', '项目 ID 格式不正确。', http_status=400,
                ))
            queryset = queryset.filter(project_id=project_id)
        queryset = queryset.order_by('-created_at')[:100]
        return Response({'results': [batch_payload(batch) for batch in queryset]})

    def retrieve(self, request, pk=None):
        return Response(batch_payload(self.get_object()))

    def destroy(self, request, pk=None):
        batch = self.get_object()
        try:
            delete_failed_import_batch(batch, request.user)
        except ScreeningImportError as exc:
            return _error_response(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def create(self, request):
        content_length = request.META.get('CONTENT_LENGTH')
        if content_length:
            try:
                if int(content_length) > settings.DATA_UPLOAD_MAX_MEMORY_SIZE:
                    return _error_response(ScreeningImportError(
                        'request_too_large', '上传请求体超过平台限制。', http_status=413,
                        details={'limit': settings.DATA_UPLOAD_MAX_MEMORY_SIZE},
                    ))
            except (TypeError, ValueError):
                pass
        if not check_permission(request.user, 'file.upload'):
            return _error_response(ScreeningImportError(
                'permission_denied', '缺少权限：file.upload。', http_status=403,
            ))

        project_id = request.data.get('project')
        try:
            project_id = int(project_id)
        except (TypeError, ValueError):
            return _error_response(ScreeningImportError('invalid_project', '缺少有效项目 ID。'))
        project = ProjectAccessPolicy.get_project(request.user, project_id)
        if project is None:
            return _error_response(ScreeningImportError(
                'project_not_found', '项目不存在或无权访问。', http_status=404,
            ))

        files = request.FILES.getlist('files') or request.FILES.getlist('file')
        try:
            batch = create_add_import(project=project, user=request.user, uploaded_files=files)
        except ScreeningImportError as exc:
            return _error_response(exc)
        return Response(batch_payload(batch), status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        batch = self.get_object()
        if batch.status not in ACTIVE_BATCH_STATUSES:
            return _error_response(ScreeningImportError(
                'invalid_import_state', '该批次当前不能取消。', http_status=409,
            ))
        if batch.task_id:
            from core.services.task_service import stop_task

            batch.task.refresh_from_db()
            if batch.task.status in ('pending', 'queuing', 'running'):
                stop_task(batch.task, request.user)
        cancel_import_batch(batch.id)
        batch.refresh_from_db()
        return Response(batch_payload(batch))

    @action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        batch = self.get_object()
        try:
            batch = retry_import_batch(batch, request.user)
        except ScreeningImportError as exc:
            return _error_response(exc)
        return Response(batch_payload(batch), status=status.HTTP_202_ACCEPTED)
