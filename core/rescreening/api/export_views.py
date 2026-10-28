"""Authenticated exports: asynchronous creation, project-isolated receipts and downloads."""
from django.db import transaction
from django.http import FileResponse
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from core.models import Project
from core.rescreening.api.common import boundary, integer, paginated, project_for, visible
from core.rescreening.api.import_views import _accepting_work, _key
from core.rescreening.models import RescreenExport
from core.rescreening.services import exports as service


def payload(row, current):
    return {key: getattr(row, key) for key in ('id', 'status', 'format', 'scope', 'mode', 'source_revision',
        'total_count', 'processed_count', 'created_at', 'finished_at', 'download_name', 'error_code')} | {
        'current': row.fingerprint == current,
        'retained_bytes': row.output_size + row.snapshot_size,
        'selection': row.configuration_snapshot.get('selection'),
        'download_url': f'/api/rescreening/exports/{row.pk}/download/' if row.status == 'completed' and row.output else None,
        'expired': row.status == 'completed' and not row.output and row.format != 'skip'}


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
@boundary
def exports(request):
    project = project_for(request)
    if request.method == 'POST':
        _accepting_work()
        job = service.start_export(project=project, user=request.user, format=request.data.get('format'),
            scope=request.data.get('scope', 'all'), mode=request.data.get('mode', 'draft'), idempotency_key=_key(request),
            expected_fingerprint=request.data.get('fingerprint'),
            offset=integer(request.data.get('offset', 0), 'offset', minimum=0, maximum=100000),
            limit=integer(request.data['limit'], 'limit', maximum=100000) if request.data.get('limit') is not None else None)
        return Response({'ok': True, 'data': payload(job, service.fingerprint(project))}, status=202)
    current = service.fingerprint(project)
    return Response({'ok': True, 'data': paginated(RescreenExport.objects.filter(project=project).order_by('-pk'),
        request, lambda row: payload(row, current))})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@boundary
def cancel(request, export_id):
    job = visible(RescreenExport.objects.select_related('project'), request.user).get(pk=export_id)
    service._permission(job.project, request.user)
    with transaction.atomic():
        Project.objects.select_for_update().get(pk=job.project_id)
        job = RescreenExport.objects.select_for_update().get(pk=export_id)
        if job.status in ('pending', 'running'):
            job.status = 'cancelled' if job.status == 'pending' else 'cancelling'
            job.finished_at = timezone.now() if job.status == 'cancelled' else None
            job.save(update_fields=['status', 'finished_at'])
            from core.services.task_service import stop_task
            transaction.on_commit(lambda: stop_task(job.task, request.user))
    return Response({'ok': True, 'data': payload(job, service.fingerprint(job.project))})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@boundary
def download(request, export_id):
    from core.rescreening.errors import RescreenError
    job = visible(RescreenExport.objects.all(), request.user).get(pk=export_id)
    if job.status != 'completed' or not job.output:
        raise RescreenError('export_unavailable', '导出尚未完成或文件已过保留期，请重新生成。', status=410)
    try:
        output = job.output.storage.open(job.output.name, 'rb')
    except FileNotFoundError:
        raise RescreenError('export_unavailable', '文件已不存在，请重新生成。', status=410)
    response = FileResponse(output, as_attachment=True, filename=job.download_name)
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@boundary
def purge(request, export_id):
    from django.contrib.auth import get_user_model
    from core.models import ActivityLog
    job = visible(RescreenExport.objects.select_related('project'), request.user).get(pk=export_id)
    service._permission(job.project, request.user)
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=job.project.owner_id)
        Project.objects.select_for_update().get(pk=job.project_id)
        job = RescreenExport.objects.select_for_update().get(pk=export_id)
        service.purge_files(job)
        ActivityLog.objects.create(project=job.project, created_by=request.user, operation_type='rescreen_export_purged',
                                   operation_detail={'export_id': job.pk})
    return Response({'ok': True, 'data': payload(job, service.fingerprint(job.project))})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@boundary
def skip(request):
    _accepting_work()
    project = project_for(request)
    job = service.skip_export(project=project, user=request.user, idempotency_key=_key(request),
                              expected_fingerprint=request.data.get('fingerprint'))
    return Response({'ok': True, 'data': payload(job, service.fingerprint(project))})
