"""Database-paginated hot bibliography queries and explicit cold metadata access."""
from django.db.models import Count, Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from core.bibliography import bibliography_snapshot
from core.rescreening.api.common import boundary, integer, paginated, project_for, visible
from core.rescreening.errors import RescreenError
from core.rescreening.models import RescreenCorpus, RescreenReference
from core.rescreening.services.imports import remove_references
from core.services.access_policy import ProjectAccessPolicy


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@boundary
def references(request):
    queryset = RescreenReference.objects.active().filter(project=project_for(request))
    term = request.query_params.get('q', '').strip()
    if len(term) > 200:
        raise RescreenError('invalid_search', '搜索词不能超过 200 字符。')
    if term:
        queryset = queryset.filter(Q(title__icontains=term) | Q(doi__icontains=term))
    source_type = request.query_params.get('source_type')
    if source_type:
        if source_type not in ('screening', 'bibliography', 'pdf'):
            raise RescreenError('invalid_source_type', '无效的来源类型。')
        queryset = queryset.filter(import_batch__source_type=source_type)
    source_file = request.query_params.get('file_id')
    if source_file:
        queryset = queryset.filter(import_file_id=integer(source_file, 'file_id'))
    fields = ('id', 'title', 'authors', 'journal', 'publication_year', 'doi', 'input_version',
              'import_file_id', 'source_reference_id', 'introduced_revision')
    data = paginated(queryset.order_by('pk').values(*fields), request, lambda row: row)
    return Response({'ok': True, 'data': data})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@boundary
def detail(request, reference_id):
    ref = visible(RescreenReference.objects.active(), request.user).get(pk=reference_id)
    return Response({'ok': True, 'data': dict(id=ref.pk, input_version=ref.input_version,
        bibliography=bibliography_snapshot(ref), source=ref.source_snapshot,
        source_reference_id=ref.source_reference_id, import_file_id=ref.import_file_id)})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@boundary
def raw(request, reference_id):
    ref = visible(RescreenReference.objects.active(), request.user).get(pk=reference_id)
    if not ProjectAccessPolicy.can_view_research_diagnostics(request.user):
        raise RescreenError('permission_denied', '仅研究者和管理员可查看原始诊断数据。', status=403)
    version = ref.raw_metadata_versions.get(input_version=ref.input_version)
    return Response({'ok': True, 'data': dict(raw_fields=version.raw_fields, source_format=version.source_format,
        raw_hash=version.raw_hash, source_extracted_fields=version.source_extracted_fields,
        source_field_definitions=version.source_field_definitions)})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@boundary
def stats(request):
    project = project_for(request)
    corpus = RescreenCorpus.objects.filter(project=project).first()
    counts = RescreenReference.objects.active().filter(project=project).aggregate(
        total=Count('pk'), with_fulltext=Count('pk', filter=Q(current_binding__isnull=False)),
        reviewed=Count('pk', filter=Q(current_review__isnull=False)))
    return Response({'ok': True, 'data': dict(counts, revision=corpus.revision if corpus else 0)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@boundary
def remove(request):
    project = project_for(request)
    ids = request.data.get('ids')
    if not isinstance(ids, list) or not 1 <= len(ids) <= 1000:
        raise RescreenError('invalid_ids', '每次移除应提供 1～1000 个文献 ID。')
    ids = [integer(value, 'ids') for value in ids]
    result = remove_references(project=project, user=request.user, ids=ids,
        expected_revision=integer(request.data.get('expected_revision'), 'expected_revision', minimum=0))
    return Response({'ok': True, 'data': result})
