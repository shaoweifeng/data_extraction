from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .responses import rate_limited_response
from .serializers import EmailVerificationSerializer, VerificationResendSerializer
from ..models import AccountEmail
from ..services.client_ip import get_client_ip
from ..services.rate_limit import (
    RateLimitUnavailable,
    consume_rate_limit,
    refund_rate_limit,
)
from ..services.verification import (
    ExpiredVerificationToken,
    InvalidVerificationToken,
    activate_email,
    issue_email_activation_token,
)
from ..tasks import queue_verification_email


@api_view(['POST'])
@permission_classes([AllowAny])
def verify_email(request):
    serializer = EmailVerificationSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(
            {'error': '验证链接无效', 'code': 'invalid_token', 'fields': serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    decision = None
    try:
        decision = consume_rate_limit(
            'email-verify:ip',
            get_client_ip(request),
            limit=getattr(settings, 'EMAIL_TOKEN_FAILURE_LIMIT', 10),
            window_seconds=getattr(settings, 'EMAIL_TOKEN_FAILURE_WINDOW_SECONDS', 600),
            fail_closed=True,
        )
        if not decision.allowed:
            return rate_limited_response(decision)
        result = activate_email(serializer.validated_data['token'])
    except RateLimitUnavailable:
        return Response(
            {'error': '账户安全服务暂时不可用，请稍后再试', 'code': 'rate_limit_unavailable'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except ExpiredVerificationToken:
        return Response(
            {'error': '验证链接已过期，请重新发送', 'code': 'expired_token'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except InvalidVerificationToken:
        return Response(
            {'error': '验证链接无效或已被替换', 'code': 'invalid_token'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if decision:
        refund_rate_limit(decision)
    return Response(
        {
            'message': '邮箱已验证，账号已激活',
            'code': 'already_verified' if result.already_verified else 'email_verified',
        },
        status=status.HTTP_200_OK,
    )


@api_view(['POST'])
@permission_classes([AllowAny])
def resend_verification_email(request):
    serializer = VerificationResendSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(
            {'error': '请输入有效的邮箱地址', 'code': 'validation_error', 'fields': serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    email = serializer.validated_data['email']
    ip_address = get_client_ip(request)
    try:
        decisions = (
            consume_rate_limit(
                'email-resend:ip', ip_address,
                limit=getattr(settings, 'EMAIL_RESEND_IP_LIMIT', 20),
                window_seconds=getattr(settings, 'REGISTRATION_REQUEST_WINDOW_SECONDS', 600),
                fail_closed=True,
            ),
            consume_rate_limit(
                'email-resend:cooldown', email,
                limit=1,
                window_seconds=getattr(settings, 'EMAIL_RESEND_INTERVAL_SECONDS', 60),
                fail_closed=True,
            ),
            consume_rate_limit(
                'email-resend:daily', email,
                limit=getattr(settings, 'EMAIL_DAILY_SEND_LIMIT', 10),
                window_seconds=24 * 3600,
                fail_closed=True,
            ),
        )
        for decision in decisions:
            if not decision.allowed:
                return rate_limited_response(decision)
    except RateLimitUnavailable:
        return Response(
            {'error': '账户安全服务暂时不可用，请稍后再试', 'code': 'rate_limit_unavailable'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    identity = AccountEmail.objects.select_related('user').filter(
        normalized_email=email,
        verified_at__isnull=True,
        user__is_active=False,
    ).first()
    if identity:
        issued = issue_email_activation_token(identity.user)
        queue_verification_email(issued.record.pk, issued.raw_token)

    return Response(
        {
            'message': '如果该邮箱存在待验证账号，我们会重新发送验证邮件',
            'resend_after': getattr(settings, 'EMAIL_RESEND_INTERVAL_SECONDS', 60),
        },
        status=status.HTTP_200_OK,
    )
