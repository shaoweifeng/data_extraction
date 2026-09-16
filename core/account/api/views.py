from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from core.api.auth_views import legacy_register
from core.serializers import UserSerializer

from .responses import rate_limited_response
from .serializers import RegistrationSerializer
from ..services.client_ip import get_client_ip
from ..services.rate_limit import (
    RateLimitUnavailable,
    consume_rate_limit,
    refund_rate_limit,
)
from ..services.registration import (
    RegistrationConflict,
    record_registration_attempt,
    register_pending_user,
    register_user,
)
from ..services.security_audit import record_security_event, request_fingerprints
from ..tasks import queue_verification_email


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
                return rate_limited_response(decision)
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
        record_security_event(
            request=request, event_type='registration', outcome='failure',
            identifier=payload.get('email', ''), detail={'reason': 'validation'},
        )
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
    fingerprints = request_fingerprints(request)
    acceptance_context = {
        'ip_hash': fingerprints['ip_hash'],
        'user_agent_hash': fingerprints['user_agent_hash'],
    }
    account_slot = None
    try:
        email_decision = _consume_registration_limit(
            'register:email-request',
            data['email'],
            getattr(settings, 'REGISTRATION_EMAIL_REQUEST_LIMIT', 5),
            daily_window,
        )
        if not email_decision.allowed:
            return rate_limited_response(email_decision)

        account_slot = _consume_registration_limit(
            'register:ip-account',
            ip_address,
            getattr(settings, 'REGISTRATION_IP_ACCOUNT_LIMIT', 3),
            daily_window,
        )
        if not account_slot.allowed:
            return rate_limited_response(account_slot)

        requires_verification = getattr(settings, 'REQUIRE_EMAIL_VERIFICATION', False)
        if requires_verification:
            pending = register_pending_user(
                username=data['username'],
                email=data['email'],
                password=data['password'],
                acceptance_context=acceptance_context,
            )
            user = pending.user
            email_queued = queue_verification_email(
                pending.verification.record.pk,
                pending.verification.raw_token,
            )
        else:
            user = register_user(
                username=data['username'],
                email=data['email'],
                password=data['password'],
                is_active=True,
                acceptance_context=acceptance_context,
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
    record_security_event(
        request=request, event_type='registration', outcome='success',
        user=user, identifier=data['email'],
    )
    if requires_verification:
        return Response(
            {
                'message': (
                    '验证邮件正在发送，请查收邮件完成账号激活'
                    if email_queued
                    else '账号已创建，但验证邮件暂时未能发送，请稍后重新发送'
                ),
                'requires_email_verification': True,
                'email': data['email'],
                'resend_after': getattr(settings, 'EMAIL_RESEND_INTERVAL_SECONDS', 60),
                'email_delivery_queued': email_queued,
            },
            status=status.HTTP_201_CREATED,
        )

    user = type(user).objects.select_related('profile').get(pk=user.pk)
    return Response(
        {
            'message': '注册成功，请登录',
            'requires_email_verification': False,
            'user': UserSerializer(user).data,
        },
        status=status.HTTP_201_CREATED,
    )
