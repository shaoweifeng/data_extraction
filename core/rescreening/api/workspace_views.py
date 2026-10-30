"""Project-scoped workspace recovery, human review and private configuration."""
from django.db.models import Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from core.bibliography import bibliography_snapshot
from core.rescreening.api.common import boundary, integer, paginated, project_for, visible
from core.rescreening.errors import RescreenError
from core.rescreening.models import RescreenReference, RescreenRunItem
from core.rescreening.services import workspace as service


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@boundary
def state(request):
    return Response({'ok': True, 'data': service.workspace_state(project_for(request), request.user)})


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
@boundary
def configuration(request):
    project = project_for(request)
    if request.method == 'GET':
        data = service.configuration(project, request.user)
    else:
        from core.rescreening.api.import_views import _accepting_work
        _accepting_work()
        data = service.save_configuration(project=project, user=request.user,
            expected_version=integer(request.data.get('expected_version'), 'expected_version', minimum=0),
            criteria=request.data.get('criteria'), model_ids=request.data.get('model_ids', []),
            custom_prompt=request.data.get('custom_prompt'))
    return Response({'ok': True, 'data': data})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@boundary
def references(request):
    queryset = service.reference_query(project_for(request)).select_related('current_binding__asset', 'current_review')
    term = request.query_params.get('q', '').strip()
    if len(term) > 200:
        raise RescreenError('invalid_search', '搜索词不能超过 200 字符。')
    if term:
        queryset = queryset.filter(Q(title__icontains=term) | Q(doi__icontains=term))
    status = request.query_params.get('status', '')
    filters = {'ready': Q(current_binding__asset__status='ready', current_binding__asset__extraction_status='completed',
                          current_binding__asset__extraction_truncated=False),
               'missing': Q(current_binding__isnull=True),
               'unreviewed': Q(review_valid=False) | Q(current_review__decision='pending'),
               'reconfirm': Q(review_valid=False, current_review__isnull=False),
               'pending': Q(review_valid=True, current_review__decision='pending'),
               'conflict': Q(suggestion_decision='conflict')}
    if status in ('included', 'excluded', 'not_retrieved'):
        queryset = queryset.filter(review_valid=True, current_review__decision=status)
    elif status:
        if status not in filters:
            raise RescreenError('invalid_status', '无效的列表筛选条件。')
        queryset = queryset.filter(filters[status])
    return Response({'ok': True, 'data': paginated(queryset.order_by('pk'), request, service.reference_payload)})


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
@boundary
def review(request, reference_id):
    ref = visible(RescreenReference.objects.active().select_related('project'), request.user).get(pk=reference_id)
    if request.method == 'POST':
        from core.rescreening.api.import_views import _accepting_work
        _accepting_work()
        optional_id = lambda name: integer(request.data[name], name) if request.data.get(name) is not None else None
        service.save_review(project=ref.project, user=request.user, reference_id=ref.pk,
            input_version=integer(request.data.get('input_version'), 'input_version'),
            expected_version=integer(request.data.get('expected_version'), 'expected_version', minimum=0),
            criteria_revision_id=optional_id('criteria_revision_id'), suggestion_id=optional_id('suggestion_id'),
            suggestion_revision=integer(request.data.get('suggestion_revision', 0), 'suggestion_revision', minimum=0),
            decision=request.data.get('decision'), reason=request.data.get('exclusion_reason', ''), note=request.data.get('note', ''))
    current = service.reference_query(ref.project).select_related('current_review__reviewed_by', 'current_binding__asset').get(pk=ref.pk)
    review = current.current_review
    asset = current.current_binding.asset if current.current_binding_id else None
    data = {**service.reference_payload(current), 'bibliography': bibliography_snapshot(current),
        'criteria_revision_id': service.configuration(ref.project)['criteria_revision_id'],
        'review': {'decision': review.decision, 'exclusion_reason': review.exclusion_reason, 'note': review.note,
                   'version': review.version, 'reviewed_by': review.reviewed_by.username if review.reviewed_by else '',
                   'updated_at': review.updated_at} if review else None,
        'pdf_url': f'/api/fulltext/assets/{asset.pk}/download/' if asset and asset.status == 'ready' else None}
    return Response({'ok': True, 'data': data})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@boundary
def history(request, reference_id):
    ref = visible(RescreenReference.objects.active(), request.user).get(pk=reference_id)
    from core.rescreening.models import RescreenReviewEvent
    events = RescreenReviewEvent.objects.filter(review__reference=ref).select_related('created_by').order_by('-pk')
    return Response({'ok': True, 'data': paginated(events, request, lambda row: {
        'id': row.pk, 'version': row.version, 'payload': row.payload, 'created_at': row.created_at,
        'author': row.created_by.username if row.created_by else ''})})
