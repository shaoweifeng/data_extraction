from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from ..services.legal import current_legal_documents, get_current_legal_document


def _serialize(document, include_content=False):
    data = {
        'type': document.document_type,
        'title': document.title,
        'version': document.version,
        'effective_date': document.effective_date,
        'content_sha256': document.content_sha256,
    }
    if include_content:
        data['content'] = document.content
    return data


@api_view(['GET'])
@permission_classes([AllowAny])
def current_legal_document_list(request):
    return Response({'documents': [_serialize(item) for item in current_legal_documents()]})


@api_view(['GET'])
@permission_classes([AllowAny])
def legal_document_detail(request, document_type):
    try:
        document = get_current_legal_document(document_type)
    except KeyError:
        return Response({'error': '协议不存在', 'code': 'not_found'}, status=404)
    return Response(_serialize(document, include_content=True))
