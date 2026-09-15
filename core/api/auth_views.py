from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from datetime import timedelta
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from ..serializers import UserSerializer
from core.account.services.client_ip import get_client_ip
from core.account.services.rate_limit import consume_rate_limit, refund_rate_limit


# ──────────────────────────────────────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────────────────────────────────────

def _get_client_ip(request) -> str:
    """Compatibility alias for the trusted-proxy-aware resolver."""
    return get_client_ip(request)


def _check_ip_register_limit(ip: str) -> tuple[bool, int]:
    """
    检查该 IP 在窗口期内的成功注册数是否已达上限。

    Returns:
        (allowed, count) — allowed=True 表示允许继续注册，count 为已注册数
    """
    from ..models import RegistrationLog

    limit = getattr(settings, 'REGISTER_IP_LIMIT', 3)
    window_hours = getattr(settings, 'REGISTER_IP_WINDOW_HOURS', 24)
    since = timezone.now() - timedelta(hours=window_hours)

    count = RegistrationLog.objects.filter(
        ip_address=ip,
        success=True,
        created_at__gte=since,
    ).count()

    return count < limit, count


def _log_registration(ip: str, username: str, email: str,
                       success: bool, fail_reason: str = '') -> None:
    """写一条注册日志（成功/失败均记录）。"""
    try:
        from ..models import RegistrationLog
        RegistrationLog.objects.create(
            ip_address=ip,
            username=username,
            email=email or '',
            success=success,
            fail_reason=fail_reason,
        )
    except Exception:
        pass  # 日志写入失败不阻断主流程


# ──────────────────────────────────────────────────────────────────────────────
# 注册
# ──────────────────────────────────────────────────────────────────────────────

def legacy_register(request):
    """Temporary compatibility path used while account registration v2 is dark."""
    username = request.data.get('username', '').strip()
    password = request.data.get('password', '')
    email    = request.data.get('email', '').strip()
    ip       = _get_client_ip(request)

    # ── 基础参数校验 ──────────────────────────────────────────────────────────
    if not username or not password:
        _log_registration(ip, username or '(空)', email, success=False, fail_reason='用户名或密码为空')
        return Response(
            {"error": "用户名和密码不能为空"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if User.objects.filter(username=username).exists():
        _log_registration(ip, username, email, success=False, fail_reason='用户名已存在')
        return Response(
            {"error": "用户名已存在"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # ── 邮箱验证占位（REQUIRE_EMAIL_VERIFICATION=True 时生效，当前默认关闭）────
    require_email_verification = getattr(settings, 'REQUIRE_EMAIL_VERIFICATION', False)
    if require_email_verification:
        # TODO: 接入 SMTP 后在此处实现邮箱格式校验 + 发送验证邮件
        # 1. 校验 email 格式（非空、合法）
        # 2. 发送验证码到邮箱
        # 3. 注册流程改为「先发验证码 → 用户填验证码 → 再创建账号」
        # 当前如果开关打开但未实现，直接报错提示未配置
        return Response(
            {"error": "邮箱验证功能尚未配置，请联系管理员"},
            status=status.HTTP_501_NOT_IMPLEMENTED,
        )

    # ── 同 IP 注册频率限制 ────────────────────────────────────────────────────
    allowed, current_count = _check_ip_register_limit(ip)
    if not allowed:
        limit = getattr(settings, 'REGISTER_IP_LIMIT', 3)
        window_hours = getattr(settings, 'REGISTER_IP_WINDOW_HOURS', 24)
        _log_registration(ip, username, email, success=False,
                          fail_reason=f'IP限流({current_count}/{limit})')
        return Response(
            {
                "error": f"该IP注册过于频繁，{window_hours} 小时内最多注册 {limit} 个账号，请稍后再试",
                "code": "ip_rate_limit",
            },
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    # ── 创建用户 ──────────────────────────────────────────────────────────────
    # UserProfile/CreditAccount 由信号兜底创建；赠送通过显式计费 Service 完成。
    with transaction.atomic():
        user = User.objects.create_user(username=username, password=password, email=email)
        free_credits = getattr(settings, 'BILLING_FREE_CREDITS_ON_REGISTER', 200)
        if free_credits > 0:
            from core.services.billing_service import grant_credits
            grant_credits(
                user,
                free_credits,
                note='注册赠送（兼容注册链路）',
                idempotency_key=f'legacy_welcome_grant:{user.pk}',
            )
    # 重新查询确保 profile 反向关系完整加载后再序列化（避免信号建 Profile 后缓存未刷新报 500）
    user = User.objects.select_related('profile').get(pk=user.pk)

    # 写注册成功日志
    _log_registration(ip, username, email, success=True)

    return Response(
        {"message": "注册成功，请登录", "user": UserSerializer(user).data},
        status=status.HTTP_201_CREATED,
    )


@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    return legacy_register(request)


# ──────────────────────────────────────────────────────────────────────────────
# 登录 / 登出
# ──────────────────────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([AllowAny])
def login_view(request):
    username = request.data.get('username')
    password = request.data.get('password')

    if not username or not password:
        return Response(
            {"error": "用户名和密码不能为空"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    login_limits = []
    if getattr(settings, 'ACCOUNT_RATE_LIMIT_ENABLED', False):
        ip_address = get_client_ip(request)
        window = getattr(settings, 'LOGIN_FAILURE_WINDOW_SECONDS', 600)
        ip_limit = consume_rate_limit(
            'login:ip',
            ip_address,
            limit=getattr(settings, 'LOGIN_IP_FAILURE_LIMIT', 50),
            window_seconds=window,
            fail_closed=False,
        )
        login_limits.append(ip_limit)
        if not ip_limit.allowed:
            response = Response(
                {"error": "登录尝试过于频繁，请稍后再试", "code": "rate_limited"},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
            if ip_limit.retry_after:
                response['Retry-After'] = str(ip_limit.retry_after)
            return response

        identifier_limit = consume_rate_limit(
            'login:identifier',
            str(username).strip().lower(),
            limit=getattr(settings, 'LOGIN_IDENTIFIER_FAILURE_LIMIT', 10),
            window_seconds=window,
            fail_closed=False,
        )
        login_limits.append(identifier_limit)
        if not identifier_limit.allowed:
            response = Response(
                {"error": "登录尝试过于频繁，请稍后再试", "code": "rate_limited"},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
            if identifier_limit.retry_after:
                response['Retry-After'] = str(identifier_limit.retry_after)
            return response

    user = authenticate(request, username=username, password=password)

    if user is None:
        return Response(
            {"error": "用户名或密码错误"},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    for decision in login_limits:
        refund_rate_limit(decision)

    # 封禁检查
    profile = getattr(user, 'profile', None)
    if profile and profile.is_banned:
        return Response(
            {"error": "账号已被封禁，请联系管理员"},
            status=status.HTTP_403_FORBIDDEN,
        )

    login(request, user)
    user = User.objects.select_related('profile').get(pk=user.pk)
    return Response(
        {"message": "登录成功", "user": UserSerializer(user).data},
        status=status.HTTP_200_OK,
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout_view(request):
    logout(request)
    return Response({"message": "已登出"}, status=status.HTTP_200_OK)


@ensure_csrf_cookie
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def me(request):
    user = User.objects.select_related('profile').get(pk=request.user.pk)
    return Response(UserSerializer(user).data)


# 别名（urls.py 及 __init__.py 中以 current_user 引用）
current_user = me
