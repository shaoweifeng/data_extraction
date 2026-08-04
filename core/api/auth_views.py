from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from ..serializers import UserSerializer


# ──────────────────────────────────────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────────────────────────────────────

def _get_client_ip(request) -> str:
    """
    从请求中提取真实客户端 IP。
    优先读 X-Forwarded-For 最左侧地址（反向代理场景），兜底用 REMOTE_ADDR。
    """
    xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '0.0.0.0')


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

@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
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
    # UserProfile 由 post_save 信号自动创建（role=user, is_approved=True），免审核
    # CreditAccount（200 credits 赠送）由 models_billing.py 的 post_save 信号自动创建
    user = User.objects.create_user(username=username, password=password, email=email)
    # 重新查询确保 profile 反向关系完整加载后再序列化（避免信号建 Profile 后缓存未刷新报 500）
    user = User.objects.select_related('profile').get(pk=user.pk)

    # 写注册成功日志
    _log_registration(ip, username, email, success=True)

    return Response(
        {"message": "注册成功，请登录", "user": UserSerializer(user).data},
        status=status.HTTP_201_CREATED,
    )


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

    user = authenticate(request, username=username, password=password)

    if user is None:
        return Response(
            {"error": "用户名或密码错误"},
            status=status.HTTP_401_UNAUTHORIZED,
        )

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


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def me(request):
    user = User.objects.select_related('profile').get(pk=request.user.pk)
    return Response(UserSerializer(user).data)


# 别名（urls.py 及 __init__.py 中以 current_user 引用）
current_user = me
