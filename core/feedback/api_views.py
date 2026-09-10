import uuid
from datetime import timedelta

from django.conf import settings
from django.http import FileResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.operations.services import is_platform_admin

from .models import FeedbackAttachment, FeedbackDailyQuota, UserFeedback
from .serializers import FeedbackSubmissionSerializer
from .services import FeedbackLimitExceeded, submit_feedback
from .validators import FeedbackImageValidationError, validate_feedback_images


def _error(code, message, http_status):
    return Response({'code': code, 'error': message}, status=http_status)


def _submission_response(feedback, remaining_today, *, created):
    return Response(
        {
            'id': str(feedback.id),
            'display_code': feedback.display_code,
            'status': feedback.status,
            'created_at': feedback.created_at,
            'remaining_today': remaining_today,
        },
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def feedback_submit(request):
    if is_platform_admin(request.user):
        return _error('FEEDBACK_NOT_AVAILABLE', '管理员账号不使用用户反馈入口', status.HTTP_403_FORBIDDEN)

    content_length = request.META.get('CONTENT_LENGTH')
    if content_length:
        try:
            if int(content_length) > settings.FEEDBACK_MAX_REQUEST_BYTES:
                return _error('PAYLOAD_TOO_LARGE', '反馈内容和图片总大小超过限制', status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        except ValueError:
            return _error('INVALID_CONTENT_LENGTH', '请求大小信息不合法', status.HTTP_400_BAD_REQUEST)

    request_id = request.headers.get('Idempotency-Key', '')
    try:
        client_request_id = uuid.UUID(request_id)
    except (ValueError, AttributeError):
        return _error('INVALID_IDEMPOTENCY_KEY', '缺少或无效的 Idempotency-Key', status.HTTP_400_BAD_REQUEST)

    # 在解析、解码图片前做快速拒绝；事务内还会再次加锁校验，保证并发正确性。
    quota = FeedbackDailyQuota.objects.filter(user=request.user, quota_date=timezone.localdate()).first()
    existing = UserFeedback.objects.filter(
        reporter_user_id=request.user.id,
        client_request_id=client_request_id,
    ).first()
    if existing:
        used_count = quota.used_count if quota else 0
        return _submission_response(
            existing,
            max(0, settings.FEEDBACK_DAILY_LIMIT - used_count),
            created=False,
        )
    if quota and quota.used_count >= settings.FEEDBACK_DAILY_LIMIT:
        response = _error('FEEDBACK_DAILY_LIMIT', '今日反馈次数已用完，请明天再试', status.HTTP_429_TOO_MANY_REQUESTS)
        response['Retry-After'] = '86400'
        return response
    burst_since = timezone.now() - timedelta(seconds=settings.FEEDBACK_BURST_WINDOW_SECONDS)
    if UserFeedback.objects.filter(user=request.user, created_at__gte=burst_since).count() >= settings.FEEDBACK_BURST_LIMIT:
        response = _error('FEEDBACK_BURST_LIMIT', '提交过于频繁，请稍后再试', status.HTTP_429_TOO_MANY_REQUESTS)
        response['Retry-After'] = '60'
        return response

    serializer = FeedbackSubmissionSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(
            {'code': 'INVALID_FEEDBACK', 'error': '反馈内容不符合要求', 'fields': serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        images = validate_feedback_images(request.FILES.getlist('images'))
        result = submit_feedback(
            user=request.user,
            client_request_id=client_request_id,
            data=serializer.validated_data,
            images=images,
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
        )
    except FeedbackImageValidationError as exc:
        return _error('INVALID_IMAGE', str(exc), status.HTTP_422_UNPROCESSABLE_ENTITY)
    except FeedbackLimitExceeded as exc:
        response = _error(exc.code, str(exc), status.HTTP_429_TOO_MANY_REQUESTS)
        response['Retry-After'] = '60' if exc.code == 'FEEDBACK_BURST_LIMIT' else '86400'
        return response
    except ValueError as exc:
        return _error('INVALID_PROJECT', str(exc), status.HTTP_400_BAD_REQUEST)

    return _submission_response(result.feedback, result.remaining_today, created=result.created)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def feedback_attachment(request, attachment_id):
    attachment = FeedbackAttachment.objects.select_related('feedback__user').filter(pk=attachment_id).first()
    if attachment is None:
        return _error('ATTACHMENT_NOT_FOUND', '图片不存在', status.HTTP_404_NOT_FOUND)
    if not is_platform_admin(request.user) and attachment.feedback.user_id != request.user.id:
        # 不暴露附件是否真实存在。
        return _error('ATTACHMENT_NOT_FOUND', '图片不存在', status.HTTP_404_NOT_FOUND)
    if not attachment.file or not attachment.file.storage.exists(attachment.file.name):
        return _error('ATTACHMENT_NOT_FOUND', '图片不存在', status.HTTP_404_NOT_FOUND)

    response = FileResponse(
        attachment.file.storage.open(attachment.file.name, 'rb'),
        content_type=attachment.mime_type,
        filename=attachment.original_name,
    )
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Security-Policy'] = "default-src 'none'; sandbox"
    response['Cache-Control'] = 'private, max-age=300'
    return response
