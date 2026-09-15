from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from core.api.auth_views import legacy_register
from core.serializers import UserSerializer

from .serializers import RegistrationSerializer
from ..services.client_ip import get_client_ip
from ..services.rate_limit import (
    RateLimitDecision,
    RateLimitUnavailable,
    consume_rate_limit,
    refund_rate_limit,
)
from ..services.registration import (
    RegistrationConflict,
    record_registration_attempt,
    register_user,
)


def _rate_limited(decision: RateLimitDecision):
    response = Response(
        {'error': '请求过于频繁，请稍后再试', 'code': 'rate_limited'},
        status=status.HTTP_429_TOO_MANY_REQUESTS,
    )
    if decision.retry_after:
        response['Retry-After'] = str(decision.retry_after)
    return response


def _consume_registration_limit(scope, identifier, limit, window):
    return consume_rate_limit(
        scope,
        identifier,
        limit=limit,
        window_seconds=window,
        fail_closed=True,
    )


@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    if not getattr(settings, 'REGISTRATION_ENABLED', True):
        return Response(
            {'error': '注册暂未开放', 'code': 'registration_closed'},
            status=status.HTTP_403_FORBIDDEN,
        )

    if not getattr(settings, 'ACCOUNT_REGISTRATION_V2_ENABLED', False):
        return legacy_register(request)

    if request.content_type != 'application/json':
        return Response(
            {'error': '请求必须使用 application/json', 'code': 'invalid_content_type'},
            status=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        )

    try:
        content_length = int(request.META.get('CONTENT_LENGTH') or 0)
    except (TypeError, ValueError):
        content_length = 0
    max_bytes = getattr(settings, 'ACCOUNT_REGISTRATION_MAX_REQUEST_BYTES', 16 * 1024)
    if content_length > max_bytes:
        return Response(
            {'error': '注册请求内容过大', 'code': 'request_too_large'},
            status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )

    if getattr(settings, 'REQUIRE_EMAIL_VERIFICATION', False):
        return Response(
            {'error': '邮箱验证功能尚未启用', 'code': 'email_verification_unavailable'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    ip_address = get_client_ip(request)
    request_window = getattr(settings, 'REGISTRATION_REQUEST_WINDOW_SECONDS', 600)
    daily_window = getattr(settings, 'REGISTRATION_WINDOW_HOURS', 24) * 3600

    try:
        for decision in (
            _consume_registration_limit(
                'register:global',
                'global',
                getattr(settings, 'REGISTRATION_GLOBAL_REQUEST_LIMIT', 500),
                request_window,
            ),
            _consume_registration_limit(
                'register:ip-request',
                ip_address,
                getattr(settings, 'REGISTRATION_IP_REQUEST_LIMIT', 20),
                request_window,
            ),
        ):
            if not decision.allowed:
                return _rate_limited(decision)
    except RateLimitUnavailable:
        return Response(
            {'error': '账户安全服务暂时不可用，请稍后再试', 'code': 'rate_limit_unavailable'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    payload = request.data
    if not isinstance(payload, dict):
        return Response(
            {'error': '注册请求必须是 JSON 对象', 'code': 'validation_error'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    serializer = RegistrationSerializer(data=payload)
    if not serializer.is_valid():
        record_registration_attempt(
            ip_address=ip_address,
            username=payload.get('username', ''),
            email=payload.get('email', ''),
            success=False,
            fail_reason='字段校验失败',
        )
        return Response(
            {'error': '注册信息有误', 'code': 'validation_error', 'fields': serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    data = serializer.validated_data
    account_slot = None
    try:
        email_decision = _consume_registration_limit(
            'register:email-request',
            data['email'],
            getattr(settings, 'REGISTRATION_EMAIL_REQUEST_LIMIT', 5),
            daily_window,
        )
        if not email_decision.allowed:
            return _rate_limited(email_decision)

        account_slot = _consume_registration_limit(
            'register:ip-account',
            ip_address,
            getattr(settings, 'REGISTRATION_IP_ACCOUNT_LIMIT', 3),
            daily_window,
        )
        if not account_slot.allowed:
            return _rate_limited(account_slot)

        user = register_user(
            username=data['username'],
            email=data['email'],
            password=data['password'],
            is_active=True,
        )
    except RateLimitUnavailable:
        return Response(
            {'error': '账户安全服务暂时不可用，请稍后再试', 'code': 'rate_limit_unavailable'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except RegistrationConflict as exc:
        if account_slot:
            refund_rate_limit(account_slot)
        field_message = '用户名已存在' if exc.field == 'username' else '邮箱已被使用'
        record_registration_attempt(
            ip_address=ip_address,
            username=data['username'],
            email=data['email'],
            success=False,
            fail_reason=field_message,
        )
        return Response(
            {
                'error': '注册信息有误',
                'code': 'validation_error',
                'fields': {exc.field: [field_message]},
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Exception:
        if account_slot:
            refund_rate_limit(account_slot)
        raise

    record_registration_attempt(
        ip_address=ip_address,
        username=data['username'],
        email=data['email'],
        success=True,
    )
    user = type(user).objects.select_related('profile').get(pk=user.pk)
    return Response(
        {'message': '注册成功，请登录', 'user': UserSerializer(user).data},
        status=status.HTTP_201_CREATED,
    )
