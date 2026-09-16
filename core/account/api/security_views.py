from django.conf import settings
from django.contrib.auth import update_session_auth_hash
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .responses import rate_limited_response
from .serializers import (
    EmailChangeConfirmSerializer,
    EmailChangeRequestSerializer,
    PasswordChangeSerializer,
    PasswordForgotSerializer,
    PasswordResetSerializer,
)
from ..models import AccountEmail
from ..services.client_ip import get_client_ip
from ..services.email_change import (
    EmailChangeConflict,
    confirm_email_change,
    issue_email_change_token,
)
from ..services.password_reset import change_password, issue_password_reset_token, reset_password
from ..services.rate_limit import RateLimitUnavailable, consume_rate_limit, refund_rate_limit
from ..services.verification import ExpiredVerificationToken, InvalidVerificationToken
from ..tasks import (
    queue_email_change_confirmation,
    queue_password_changed_notice,
    queue_password_reset_email,
)


def _consume(scope, identifier, limit, window, *, fail_closed=True):
    return consume_rate_limit(
        scope, str(identifier), limit=limit, window_seconds=window, fail_closed=fail_closed,
    )


def _consume_security_change_limits(request, action):
    window = getattr(settings, 'ACCOUNT_SECURITY_CHANGE_WINDOW_SECONDS', 600)
    decisions = []
    for scope, identifier, limit in (
        (
            f'{action}:ip', get_client_ip(request),
            getattr(settings, 'ACCOUNT_SECURITY_CHANGE_IP_LIMIT', 30),
        ),
        (
            f'{action}:user', request.user.pk,
            getattr(settings, 'ACCOUNT_SECURITY_CHANGE_USER_LIMIT', 10),
        ),
    ):
        decision = _consume(scope, identifier, limit, window)
        decisions.append(decision)
        if not decision.allowed:
            return decisions, decision
    return decisions, None


@api_view(['POST'])
@permission_classes([AllowAny])
def forgot_password(request):
    serializer = PasswordForgotSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(
            {'error': '请输入有效的邮箱地址', 'code': 'validation_error', 'fields': serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )
    email = serializer.validated_data['email']
    try:
        decisions = (
            _consume(
                'password-forgot:ip', get_client_ip(request),
                getattr(settings, 'PASSWORD_RESET_IP_LIMIT', 20), 24 * 3600,
            ),
            _consume(
                'password-forgot:email', email,
                getattr(settings, 'PASSWORD_RESET_DAILY_SEND_LIMIT', 10), 24 * 3600,
            ),
            _consume(
                'password-forgot:cooldown', email, 1,
                getattr(settings, 'PASSWORD_RESET_RESEND_INTERVAL_SECONDS', 60),
            ),
        )
        denied = next((decision for decision in decisions if not decision.allowed), None)
        if denied:
            return rate_limited_response(denied)
    except RateLimitUnavailable:
        return Response(
            {'error': '账户安全服务暂时不可用，请稍后再试', 'code': 'rate_limit_unavailable'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    identity = AccountEmail.objects.select_related('user').filter(
        normalized_email=email,
        verified_at__isnull=False,
        user__is_active=True,
    ).first()
    profile = getattr(identity.user, 'profile', None) if identity else None
    if identity and not getattr(profile, 'is_banned', False):
        issued = issue_password_reset_token(identity.user)
        queue_password_reset_email(issued.record.pk, issued.raw_token)
    return Response({
        'message': '如果该邮箱对应有效账号，我们会发送密码重置邮件',
        'resend_after': getattr(settings, 'PASSWORD_RESET_RESEND_INTERVAL_SECONDS', 60),
    })


@api_view(['POST'])
@permission_classes([AllowAny])
def reset_password_view(request):
    serializer = PasswordResetSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(
            {'error': '密码重置信息有误', 'code': 'validation_error', 'fields': serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )
    decision = None
    try:
        decision = _consume(
            'password-reset:ip', get_client_ip(request),
            getattr(settings, 'EMAIL_TOKEN_FAILURE_LIMIT', 10),
            getattr(settings, 'EMAIL_TOKEN_FAILURE_WINDOW_SECONDS', 600),
        )
        if not decision.allowed:
            return rate_limited_response(decision)
        result = reset_password(
            serializer.validated_data['token'],
            serializer.validated_data['password'],
        )
    except RateLimitUnavailable:
        return Response(
            {'error': '账户安全服务暂时不可用，请稍后再试', 'code': 'rate_limit_unavailable'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except ExpiredVerificationToken:
        return Response(
            {'error': '密码重置链接已过期，请重新申请', 'code': 'expired_token'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except InvalidVerificationToken:
        return Response(
            {'error': '密码重置链接无效或已被使用', 'code': 'invalid_token'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except DjangoValidationError as exc:
        return Response(
            {
                'error': '新密码不符合安全要求',
                'code': 'validation_error',
                'fields': {'password': exc.messages},
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    if decision:
        refund_rate_limit(decision)
    queue_password_changed_notice(result.user.pk)
    return Response({'message': '密码已重置，请使用新密码登录'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def change_password_view(request):
    try:
        decisions, denied = _consume_security_change_limits(request, 'password-change')
    except RateLimitUnavailable:
        return Response(
            {'error': '账户安全服务暂时不可用，请稍后再试', 'code': 'rate_limit_unavailable'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if denied:
        return rate_limited_response(denied)
    serializer = PasswordChangeSerializer(data=request.data, context={'request': request})
    if not serializer.is_valid():
        return Response(
            {'error': '密码修改信息有误', 'code': 'validation_error', 'fields': serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )
    user = change_password(request.user, serializer.validated_data['new_password'])
    update_session_auth_hash(request, user)
    for decision in decisions:
        refund_rate_limit(decision)
    identity = AccountEmail.objects.filter(user=user, verified_at__isnull=False).first()
    if identity:
        queue_password_changed_notice(user.pk)
    return Response({'message': '密码修改成功'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def request_email_change(request):
    try:
        security_decisions, denied = _consume_security_change_limits(request, 'email-change-auth')
    except RateLimitUnavailable:
        return Response(
            {'error': '账户安全服务暂时不可用，请稍后再试', 'code': 'rate_limit_unavailable'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if denied:
        return rate_limited_response(denied)
    serializer = EmailChangeRequestSerializer(data=request.data, context={'request': request})
    if not serializer.is_valid():
        return Response(
            {'error': '邮箱变更信息有误', 'code': 'validation_error', 'fields': serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )
    email = serializer.validated_data['new_email']
    try:
        decisions = (
            _consume(
                'email-change:ip', get_client_ip(request),
                getattr(settings, 'EMAIL_CHANGE_IP_LIMIT', 20), 24 * 3600,
            ),
            _consume(
                'email-change:user', request.user.pk,
                getattr(settings, 'EMAIL_CHANGE_DAILY_SEND_LIMIT', 10), 24 * 3600,
            ),
            _consume(
                'email-change:cooldown', request.user.pk, 1,
                getattr(settings, 'EMAIL_CHANGE_RESEND_INTERVAL_SECONDS', 60),
            ),
        )
        denied = next((decision for decision in decisions if not decision.allowed), None)
        if denied:
            return rate_limited_response(denied)
        issued = issue_email_change_token(request.user, email)
    except RateLimitUnavailable:
        return Response(
            {'error': '账户安全服务暂时不可用，请稍后再试', 'code': 'rate_limit_unavailable'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except EmailChangeConflict as exc:
        return Response(
            {'error': str(exc), 'code': 'email_conflict'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    for decision in security_decisions:
        refund_rate_limit(decision)
    queued = queue_email_change_confirmation(issued.record.pk, issued.raw_token)
    return Response({
        'message': (
            '验证邮件已发送到新邮箱，验证完成前原邮箱保持有效'
            if queued
            else '邮箱变更申请已创建，但邮件暂未发送，请稍后重试'
        ),
        'email_delivery_queued': queued,
        'resend_after': getattr(settings, 'EMAIL_CHANGE_RESEND_INTERVAL_SECONDS', 60),
    })


@api_view(['POST'])
@permission_classes([AllowAny])
def confirm_email_change_view(request):
    serializer = EmailChangeConfirmSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(
            {'error': '邮箱变更链接无效', 'code': 'invalid_token'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    decision = None
    try:
        decision = _consume(
            'email-change-confirm:ip', get_client_ip(request),
            getattr(settings, 'EMAIL_TOKEN_FAILURE_LIMIT', 10),
            getattr(settings, 'EMAIL_TOKEN_FAILURE_WINDOW_SECONDS', 600),
        )
        if not decision.allowed:
            return rate_limited_response(decision)
        result = confirm_email_change(serializer.validated_data['token'])
    except RateLimitUnavailable:
        return Response(
            {'error': '账户安全服务暂时不可用，请稍后再试', 'code': 'rate_limit_unavailable'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except ExpiredVerificationToken:
        return Response(
            {'error': '邮箱变更链接已过期，请重新申请', 'code': 'expired_token'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except InvalidVerificationToken:
        return Response(
            {'error': '邮箱变更链接无效或已被使用', 'code': 'invalid_token'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except EmailChangeConflict as exc:
        return Response({'error': str(exc), 'code': 'email_conflict'}, status=409)

    if decision:
        refund_rate_limit(decision)
    if result.old_verified_email and result.old_verified_email != result.new_email:
        from ..tasks import queue_email_changed_notice
        queue_email_changed_notice(result.user.pk, result.old_verified_email, result.new_email)
    return Response({'message': '可信邮箱已更新', 'email': result.new_email})
