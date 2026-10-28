"""Private asset endpoints; pagination, permission checks and Range-aware downloads."""
from django.db.models import Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from core.fulltext.downloads import pdf_response
from core.fulltext.errors import FulltextError
from core.fulltext.models import FulltextAsset
from core.fulltext.services import create_assets, retry_asset, delete_asset, rebuild_asset
from core.rescreening.api.common import boundary, paginated, project_for, visible


def asset_payload(asset):
    return {**{name: getattr(asset, name) for name in (
        'id', 'original_filename', 'size_bytes', 'status', 'scan_status', 'extraction_status',
        'page_count', 'extracted_page_count', 'extracted_text_chars', 'extraction_truncated',
        'truncated_at_page', 'chunk_count', 'extraction_version', 'chunking_version',
        'processing_task_id', 'error_code', 'error_message', 'created_at')},
        'download_url': f'/api/fulltext/assets/{asset.pk}/download/' if asset.status == 'ready' else None,
        'ai_ready': asset.status == 'ready' and asset.extraction_status == 'completed' and not asset.extraction_truncated}


def boolean(value, default=False):
    if value is None:
        return default
    if value in (True, 'true', '1', 1):
        return True
    if value in (False, 'false', '0', 0):
        return False
    raise FulltextError('invalid_boolean', '布尔参数必须为 true/false。')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@boundary
def assets(request):
    queryset = FulltextAsset.objects.filter(project=project_for(request)).order_by('-pk')
    status = request.query_params.get('status')
    if status:
        queryset = queryset.filter(status=status)
    term = request.query_params.get('q', '').strip()
    if len(term) > 200:
        raise FulltextError('invalid_search', '搜索词不能超过 200 字符。')
    if term:
        queryset = queryset.filter(Q(original_filename__icontains=term) | Q(primary_doi__icontains=term))
    return Response({'ok': True, 'data': paginated(queryset.defer('metadata', 'provenance'), request, asset_payload)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@boundary
def upload(request):
    from core.rescreening.api.import_views import _accepting_work
    _accepting_work()
    result, refs = create_assets(project=project_for(request), user=request.user,
        files=request.FILES.getlist('files') or request.FILES.getlist('files[]'),
        create_references=boolean(request.data.get('create_references')))
    return Response({'ok': True, 'data': {'assets': [asset_payload(row) for row in result],
        'references': [{'id': row.pk, 'input_version': row.input_version,
            'removed': row.removed_revision is not None} for row in refs]}}, status=202)


@api_view(['GET', 'DELETE'])
@permission_classes([IsAuthenticated])
@boundary
def detail(request, asset_id):
    asset = visible(FulltextAsset.objects.select_related('project__owner'), request.user).get(pk=asset_id)
    if request.method == 'DELETE':
        delete_asset(asset, request.user)
        return Response({'ok': True})
    return Response({'ok': True, 'data': asset_payload(asset)})


@api_view(['GET', 'HEAD'])
@permission_classes([IsAuthenticated])
@boundary
def download(request, asset_id):
    asset = visible(FulltextAsset.objects.all(), request.user).get(pk=asset_id)
    if asset.status != 'ready' or not asset.raw_file:
        raise FulltextError('asset_not_ready', '全文尚不可下载。', status=409)
    return pdf_response(request, asset)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@boundary
def retry(request, asset_id):
    from core.rescreening.api.import_views import _accepting_work
    _accepting_work()
    asset = visible(FulltextAsset.objects.select_related('project__owner'), request.user).get(pk=asset_id)
    return Response({'ok': True, 'data': asset_payload(retry_asset(asset, request.user))}, status=202)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@boundary
def rebuild(request, asset_id):
    from core.rescreening.api.import_views import _accepting_work
    _accepting_work()
    asset = visible(FulltextAsset.objects.select_related('project__owner'), request.user).get(pk=asset_id)
    return Response({'ok': True, 'data': asset_payload(rebuild_asset(asset, request.user))}, status=202)
