from django.conf import settings
from django.contrib.auth import get_user_model, login
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from core.serializers import UserSerializer

from ..services.authentication import authenticate_identifier
from ..services.client_ip import get_client_ip
from ..services.rate_limit import consume_rate_limit, refund_rate_limit

User = get_user_model()


@api_view(['POST'])
@permission_classes([AllowAny])
def login_view(request):
    identifier = request.data.get('username')
    password = request.data.get('password')
    if not identifier or not password:
        return Response(
            {'error': '用户名或邮箱和密码不能为空'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    decisions = []
    if getattr(settings, 'ACCOUNT_RATE_LIMIT_ENABLED', False):
        window = getattr(settings, 'LOGIN_FAILURE_WINDOW_SECONDS', 600)
        ip_decision = consume_rate_limit(
            'login:ip', get_client_ip(request),
            limit=getattr(settings, 'LOGIN_IP_FAILURE_LIMIT', 50),
            window_seconds=window, fail_closed=False,
        )
        decisions.append(ip_decision)
        if not ip_decision.allowed:
            response = Response(
                {'error': '登录尝试过于频繁，请稍后再试', 'code': 'rate_limited'},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
            if ip_decision.retry_after:
                response['Retry-After'] = str(ip_decision.retry_after)
            return response
        identifier_decision = consume_rate_limit(
            'login:identifier', str(identifier).strip().casefold(),
            limit=getattr(settings, 'LOGIN_IDENTIFIER_FAILURE_LIMIT', 10),
            window_seconds=window, fail_closed=False,
        )
        decisions.append(identifier_decision)
        if not identifier_decision.allowed:
            response = Response(
                {'error': '登录尝试过于频繁，请稍后再试', 'code': 'rate_limited'},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
            if identifier_decision.retry_after:
                response['Retry-After'] = str(identifier_decision.retry_after)
            return response

    user = authenticate_identifier(request, identifier, password)
    if user is None:
        return Response({'error': '用户名或密码错误'}, status=status.HTTP_401_UNAUTHORIZED)
    profile = getattr(user, 'profile', None)
    if profile and profile.is_banned:
        return Response({'error': '账号已被封禁，请联系管理员'}, status=status.HTTP_403_FORBIDDEN)

    for decision in decisions:
        refund_rate_limit(decision)
    login(request, user)
    user = User.objects.select_related('profile').get(pk=user.pk)
    return Response(
        {'message': '登录成功', 'user': UserSerializer(user).data},
        status=status.HTTP_200_OK,
    )
