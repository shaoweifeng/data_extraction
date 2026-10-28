"""Import commands and private source inspection; no public file URLs."""
from uuid import uuid4
from django.http import FileResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from core.rescreening.api.common import boundary, paginated, project_for, visible
from core.rescreening.errors import RescreenError
from core.rescreening.models import RescreenImportBatch, RescreenImportFile
from core.rescreening.services.imports import start_import, retry_import
from core.rescreening.services.source import source_preview
from core.services.access_policy import ProjectAccessPolicy


def _batch(batch, user):
    diagnostics = ProjectAccessPolicy.can_view_research_diagnostics(user)
    data = {key: getattr(batch, key) for key in (
        'id', 'project_id', 'source_type', 'status', 'base_revision', 'target_revision',
        'accepted_count', 'task_id', 'created_at', 'finished_at',
    )}
    data['retryable'] = batch.status in ('failed', 'cancelled') and (
        batch.source_type == 'screening' or batch.files.exists())
    data['error'] = (batch.error_message if diagnostics else '导入未完成，请重试或联系管理员。') if batch.error_code else ''
    if diagnostics:
        data.update(error_code=batch.error_code, rejected_count=batch.rejected_count,
                    skipped_count=batch.skipped_count)
    return data


def _key(request):
    key = request.headers.get('Idempotency-Key') or str(uuid4())
    if len(key) > 128 or not key.isascii() or any(ord(char) < 33 for char in key):
        raise RescreenError('invalid_idempotency_key', 'Idempotency-Key 必须是 1～128 位可见 ASCII 字符。')
    return key


def _accepting_work():
    from core.operations.services import assert_accepting_new_work
    try:
        assert_accepting_new_work()
    except RuntimeError as exc:
        raise RescreenError('maintenance', str(exc), status=503)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@boundary
def preview(request):
    return Response({'ok': True, 'data': source_preview(project_for(request))})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@boundary
def upload(request):
    _accepting_work()
    batch = start_import(project=project_for(request), user=request.user, idempotency_key=_key(request),
                         uploads=request.FILES.getlist('files') or request.FILES.getlist('files[]'))
    return Response({'ok': True, 'data': _batch(batch, request.user)}, status=202)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@boundary
def from_screening(request):
    _accepting_work()
    project = project_for(request)
    snapshot = source_preview(project)
    if request.data.get('source_fingerprint') != snapshot['fingerprint']:
        raise RescreenError('source_changed', '请先预览并传入最新的 source_fingerprint。', status=409)
    batch = start_import(project=project, user=request.user, idempotency_key=_key(request), preview=snapshot)
    return Response({'ok': True, 'data': _batch(batch, request.user)}, status=202)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@boundary
def batches(request):
    queryset = RescreenImportBatch.objects.filter(project=project_for(request)).order_by('-pk')
    return Response({'ok': True, 'data': paginated(queryset, request, lambda row: _batch(row, request.user))})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@boundary
def detail(request, batch_id):
    batch = visible(RescreenImportBatch.objects.all(), request.user).get(pk=batch_id)
    data = _batch(batch, request.user)
    diagnostics = ProjectAccessPolicy.can_view_research_diagnostics(request.user)
    data['files'] = [dict(id=row.pk, filename=row.original_filename, size_bytes=row.size_bytes,
        report=row.report if diagnostics else {'parsed_entries': row.report.get('parsed_entries', 0)})
        for row in batch.files.order_by('pk')]
    return Response({'ok': True, 'data': data})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@boundary
def retry(request, batch_id):
    _accepting_work()
    batch = visible(RescreenImportBatch.objects.all(), request.user).get(pk=batch_id)
    batch = retry_import(batch_id=batch.pk, user=request.user)
    return Response({'ok': True, 'data': _batch(batch, request.user)}, status=202)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@boundary
def cancel(request, batch_id):
    from core.services.task_service import stop_task
    batch = visible(RescreenImportBatch.objects.select_related('task'), request.user).get(pk=batch_id)
    if batch.status in RescreenImportBatch.ACTIVE_STATUSES and batch.task:
        if not stop_task(batch.task, request.user):
            raise RescreenError('cancel_conflict', '任务状态已变化，请刷新后重试。', status=409)
    batch.refresh_from_db()
    return Response({'ok': True, 'data': _batch(batch, request.user)})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@boundary
def download(request, file_id):
    source = RescreenImportFile.objects.filter(batch__project__in=ProjectAccessPolicy.visible_projects(request.user)).get(pk=file_id)
    try:
        handle = source.raw_file.open('rb')
    except OSError:
        raise RescreenError('file_missing', '源文件不存在。', status=404)
    return FileResponse(handle, as_attachment=True, filename=source.original_filename, content_type='application/octet-stream')
