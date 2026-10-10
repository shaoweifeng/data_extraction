import secrets
import uuid

from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from core.services.image_validation import ImageValidationError, validate_and_reencode_image

from .models import ExternalImageUpload
from .services import store_external_image


def _error(code, message, http_status):
    return Response({'code': code, 'error': message}, status=http_status)


def _authorized(request):
    authorization = request.headers.get('Authorization', '')
    scheme, separator, supplied = authorization.partition(' ')
    if not separator or scheme.casefold() != 'bearer' or not supplied:
        return False
    return secrets.compare_digest(supplied.strip(), settings.EXTERNAL_IMAGE_UPLOAD_API_KEY)


def _response(upload, *, created):
    return Response(
        {
            'id': str(upload.id),
            'path': upload.file.path,
            'relative_path': upload.file.name,
            'mime_type': upload.mime_type,
            'file_size': upload.file_size,
            'width': upload.width,
            'height': upload.height,
            'sha256': upload.sha256,
            'source': upload.source,
            'created_at': upload.created_at,
        },
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def external_image_upload(request):
    if not settings.EXTERNAL_IMAGE_UPLOAD_ENABLED:
        return _error('IMAGE_UPLOAD_DISABLED', '图片上传接口未启用', status.HTTP_503_SERVICE_UNAVAILABLE)
    if not _authorized(request):
        response = _error('INVALID_API_KEY', '缺少或无效的 API Key', status.HTTP_401_UNAUTHORIZED)
        response['WWW-Authenticate'] = 'Bearer'
        return response

    content_length = request.META.get('CONTENT_LENGTH')
    if content_length:
        try:
            if int(content_length) > settings.EXTERNAL_IMAGE_UPLOAD_MAX_REQUEST_BYTES:
                return _error('PAYLOAD_TOO_LARGE', '请求大小超过限制', status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        except ValueError:
            return _error('INVALID_CONTENT_LENGTH', '请求大小信息不合法', status.HTTP_400_BAD_REQUEST)

    try:
        client_request_id = uuid.UUID(request.headers.get('Idempotency-Key', ''))
    except (ValueError, AttributeError):
        return _error(
            'INVALID_IDEMPOTENCY_KEY',
            '缺少或无效的 Idempotency-Key',
            status.HTTP_400_BAD_REQUEST,
        )

    existing = ExternalImageUpload.objects.filter(
        client_request_id=client_request_id,
    ).first()
    if existing:
        return _response(existing, created=False)

    image_file = request.FILES.get('image')
    if image_file is None:
        return _error('IMAGE_REQUIRED', 'multipart/form-data 中缺少 image 文件', status.HTTP_400_BAD_REQUEST)
    source = str(request.data.get('source') or '').strip()
    if len(source) > 100:
        return _error('INVALID_SOURCE', 'source 最多 100 个字符', status.HTTP_400_BAD_REQUEST)

    try:
        image = validate_and_reencode_image(
            image_file,
            max_bytes=settings.EXTERNAL_IMAGE_UPLOAD_MAX_IMAGE_BYTES,
            max_pixels=settings.EXTERNAL_IMAGE_UPLOAD_MAX_PIXELS,
        )
        result = store_external_image(
            client_request_id=client_request_id,
            source=source,
            image=image,
        )
    except ImageValidationError as exc:
        return _error('INVALID_IMAGE', str(exc), status.HTTP_422_UNPROCESSABLE_ENTITY)

    return _response(result.upload, created=result.created)
