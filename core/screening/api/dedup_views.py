"""Paginated HTTP read model for database-backed deduplication results."""

from math import ceil

from django.db.models import Case, IntegerField, Value, When
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.screening.models import DedupRun, ReferenceDuplicateGroup
from core.services.access_policy import ProjectAccessPolicy


GROUP_DEFAULT_PAGE_SIZE = 20
GROUP_MAX_PAGE_SIZE = 100
MEMBER_DEFAULT_PAGE_SIZE = 50
MEMBER_MAX_PAGE_SIZE = 200


def _positive_int(value, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _page_params(request, *, default_size: int, max_size: int) -> tuple[int, int]:
    page = _positive_int(request.query_params.get('page'), 1)
    page_size = min(
        _positive_int(request.query_params.get('page_size'), default_size),
        max_size,
    )
    return page, page_size


def _paginated_payload(queryset, *, page: int, page_size: int, serializer) -> dict:
    count = queryset.count()
    offset = (page - 1) * page_size
    rows = list(queryset[offset:offset + page_size]) if offset < count else []
    return {
        'count': count,
        'page': page,
        'page_size': page_size,
        'total_pages': ceil(count / page_size) if count else 0,
        'results': [serializer(row) for row in rows],
    }


def _reference_payload(reference) -> dict:
    return {
        'id': reference.id,
        'title': reference.title,
        'source_file': reference.source_file.filename,
        'source_file_id': reference.source_file_id,
        'source_position': reference.source_record_index,
        'year': reference.publication_year,
        'journal': reference.journal,
        'doi': reference.doi,
        'url': reference.url,
    }


def _visible_run(request, project_id: int, run_id: int) -> DedupRun:
    project = ProjectAccessPolicy.get_project(request.user, project_id)
    if project is None:
        return get_object_or_404(DedupRun.objects.none(), pk=run_id)
    return get_object_or_404(
        DedupRun.objects.select_related('corpus'),
        pk=run_id,
        project=project,
        status=DedupRun.Status.COMPLETED,
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dedup_groups(request, project_id: int, run_id: int):
    run = _visible_run(request, project_id, run_id)
    page, page_size = _page_params(
        request,
        default_size=GROUP_DEFAULT_PAGE_SIZE,
        max_size=GROUP_MAX_PAGE_SIZE,
    )
    queryset = run.groups.select_related(
        'representative_reference__source_file',
    ).order_by('sequence')

    def serialize(group):
        return {
            'id': group.id,
            'sequence': group.sequence,
            'title': group.display_title,
            'match_type': group.match_type,
            'member_count': group.member_count,
            'representative': _reference_payload(group.representative_reference),
        }

    payload = _paginated_payload(
        queryset,
        page=page,
        page_size=page_size,
        serializer=serialize,
    )
    payload.update({
        'dedup_run_id': run.id,
        'corpus_revision': run.corpus_revision,
    })
    return Response(payload)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dedup_group_members(request, project_id: int, run_id: int, group_id: int):
    run = _visible_run(request, project_id, run_id)
    group = get_object_or_404(ReferenceDuplicateGroup, pk=group_id, dedup_run=run)
    page, page_size = _page_params(
        request,
        default_size=MEMBER_DEFAULT_PAGE_SIZE,
        max_size=MEMBER_MAX_PAGE_SIZE,
    )
    queryset = group.members.select_related(
        'reference__source_file',
    ).annotate(
        role_order=Case(
            When(role='kept', then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        ),
    ).order_by('role_order', 'reference_id')

    def serialize(member):
        return {
            'id': member.id,
            'role': member.role,
            'match_reason': member.match_reason,
            'match_score': str(member.match_score) if member.match_score is not None else None,
            'reference': _reference_payload(member.reference),
        }

    payload = _paginated_payload(
        queryset,
        page=page,
        page_size=page_size,
        serializer=serialize,
    )
    payload.update({'dedup_run_id': run.id, 'group_id': group.id})
    return Response(payload)
