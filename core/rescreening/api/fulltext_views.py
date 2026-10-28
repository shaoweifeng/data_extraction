"""Rescreen binding and durable lookup commands, never synchronous network searches."""
from urllib.parse import urlsplit, urlunsplit
from django.conf import settings
from django.db.models import Count
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from core.fulltext.api import asset_payload, boolean
from core.fulltext.models import FulltextAsset
from core.rescreening.api.common import boundary, integer, paginated, project_for, visible
from core.rescreening.api.import_views import _key, _accepting_work
from core.rescreening.models import RescreenReference, FulltextLookupJob, FulltextLookupItem, FulltextCandidate
from core.rescreening.services.fulltext_binding import bind_fulltext
from core.rescreening.services.fulltext_lookup import start_lookup, confirm_candidate


def job_payload(job):
    counts = {row['status']: row['count'] for row in job.items.values('status').annotate(count=Count('pk'))}
    return dict(id=job.pk, project_id=job.project_id, task_id=job.task_id, mode=job.mode,
        status=job.status, processed=job.processed_count, total=sum(counts.values()), counts=counts,
        received_bytes=job.received_bytes, request_count=job.request_count, error_code=job.error_code,
        created_at=job.created_at, finished_at=job.finished_at)


def candidate_payload(candidate):
    parsed = urlsplit(candidate.url)
    # Signed URLs and third-party request credentials remain server-side.
    public_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, '', '')) if candidate.url else ''
    return dict(id=candidate.pk, asset_id=candidate.asset_id, source=candidate.source, url=public_url,
        license=candidate.license, title=candidate.title, confidence=candidate.confidence,
        status=candidate.status, error_code=candidate.error_code)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
@boundary
def binding(request, reference_id):
    ref = visible(RescreenReference.objects.active().select_related('project__owner', 'current_binding__asset'), request.user).get(pk=reference_id)
    if request.method == 'POST':
        _accepting_work()
        asset_id = request.data.get('asset_id')
        asset = visible(FulltextAsset.objects.all(), request.user).get(pk=integer(asset_id, 'asset_id')) if asset_id is not None else None
        ref = bind_fulltext(reference=ref, asset=asset, user=request.user,
            expected_version=integer(request.data.get('expected_version'), 'expected_version'),
            expected_revision=integer(request.data.get('expected_revision'), 'expected_revision', minimum=0))
    return Response({'ok': True, 'data': dict(reference_id=ref.pk, input_version=ref.input_version,
        revision=ref.corpus.revision, asset=asset_payload(ref.current_binding.asset) if ref.current_binding_id else None)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@boundary
def start(request):
    _accepting_work()
    ids = request.data.get('ids')
    from core.fulltext.errors import FulltextError
    if not isinstance(ids, list) or not 1 <= len(ids) <= settings.FULLTEXT_LOOKUP_MAX_REFERENCES:
        raise FulltextError('invalid_ids', '请提供文献 ID 列表。')
    job = start_lookup(project=project_for(request), user=request.user,
        ids=[integer(value, 'ids') for value in ids], mode=request.data.get('mode', 'local'),
        idempotency_key=_key(request), download=boolean(request.data.get('download')),
        auto_bind=boolean(request.data.get('auto_bind')),
        candidate_id=integer(request.data['candidate_id'], 'candidate_id') if request.data.get('candidate_id') is not None else None,
        manual_url=request.data.get('manual_url', ''))
    return Response({'ok': True, 'data': job_payload(job)}, status=202)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@boundary
def jobs(request):
    queryset = FulltextLookupJob.objects.filter(project=project_for(request)).order_by('-pk')
    return Response({'ok': True, 'data': paginated(queryset, request, job_payload)})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@boundary
def job_detail(request, job_id):
    job = visible(FulltextLookupJob.objects.all(), request.user).get(pk=job_id)
    return Response({'ok': True, 'data': job_payload(job)})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@boundary
def items(request, job_id):
    job = visible(FulltextLookupJob.objects.all(), request.user).get(pk=job_id)
    queryset = job.items.prefetch_related('candidates').order_by('pk')
    def serialize(item):
        return dict(id=item.pk, reference_id=item.reference_id, input_version=item.input_version,
            status=item.status, error_code=item.error_code, resolver_notes=item.resolver_notes,
            candidates=[candidate_payload(row) for row in item.candidates.all()])
    return Response({'ok': True, 'data': paginated(queryset, request, serialize)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@boundary
def cancel(request, job_id):
    from core.services.task_service import stop_task
    job = visible(FulltextLookupJob.objects.select_related('task'), request.user).get(pk=job_id)
    if job.status in ('pending', 'running'):
        stop_task(job.task, request.user)
    job.refresh_from_db()
    return Response({'ok': True, 'data': job_payload(job)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@boundary
def confirm(request, candidate_id):
    _accepting_work()
    from core.services.access_policy import ProjectAccessPolicy
    candidate = FulltextCandidate.objects.select_related('item__reference__project', 'asset').filter(
        item__job__project__in=ProjectAccessPolicy.visible_projects(request.user)).get(pk=candidate_id)
    ref = confirm_candidate(candidate=candidate, user=request.user,
        expected_version=integer(request.data.get('expected_version'), 'expected_version'))
    return Response({'ok': True, 'data': dict(reference_id=ref.pk, input_version=ref.input_version)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@boundary
def retry(request, job_id):
    from core.fulltext.errors import FulltextError
    _accepting_work()
    old = visible(FulltextLookupJob.objects.select_related('project'), request.user).get(pk=job_id)
    if old.status in FulltextLookupJob.ACTIVE_STATUSES or old.mode == 'manual':
        raise FulltextError('not_retryable', '当前任务尚未结束或不是查找任务。', status=409)
    ids = list(old.items.filter(status__in=('failed', 'cancelled', 'not_found', 'pending', 'processing'))
        .order_by('pk').values_list('reference_id', flat=True)[:settings.FULLTEXT_LOOKUP_MAX_REFERENCES])
    if not ids:
        raise FulltextError('nothing_to_retry', '没有失败或未完成的文献需要重试。', status=409)
    selected = old.items.first().selected_candidate_id if old.mode == 'download' else None
    job = start_lookup(project=old.project, user=request.user, ids=ids, mode=old.mode,
        idempotency_key=_key(request), download=old.settings_snapshot.get('download', False),
        auto_bind=old.settings_snapshot.get('auto_bind', False), candidate_id=selected)
    return Response({'ok': True, 'data': job_payload(job)}, status=202)
