from django.db import connection
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .services import (
    get_operations_snapshot,
    get_system_state,
    is_platform_admin,
    pause_long_running_tasks,
    record_presence,
    resume_maintenance_tasks,
    set_system_state,
)


def _require_admin(request):
    if not is_platform_admin(request.user):
        return Response({'error': '仅管理员可以执行此操作'}, status=status.HTTP_403_FORBIDDEN)
    return None


@api_view(['GET'])
@permission_classes([AllowAny])
def system_status(request):
    return Response({**get_system_state(), 'server_time': timezone.now().isoformat()})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def presence_heartbeat(request):
    try:
        record_presence(
            request.user,
            tab_id=request.data.get('tab_id'),
            page=request.data.get('page', ''),
            project_id=request.data.get('project_id'),
        )
    except Exception:
        # Presence must never make the application unusable when Redis is unavailable.
        return Response({'ok': False, 'state': get_system_state()}, status=status.HTTP_200_OK)
    return Response({'ok': True, 'state': get_system_state()})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def operations_status(request):
    denied = _require_admin(request)
    if denied:
        return denied
    inspect_celery = request.query_params.get('inspect_celery', 'true').lower() != 'false'
    return Response(get_operations_snapshot(inspect_celery=inspect_celery))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def operations_state(request):
    denied = _require_admin(request)
    if denied:
        return denied
    scheduled_at = request.data.get('scheduled_at')
    if scheduled_at:
        scheduled_at = parse_datetime(scheduled_at)
        if scheduled_at is None:
            return Response({'error': 'scheduled_at 必须是 ISO 8601 时间'}, status=400)
    try:
        result = set_system_state(
            request.data.get('mode'),
            message=request.data.get('message', ''),
            scheduled_at=scheduled_at,
            user=request.user,
        )
    except ValueError as exc:
        return Response({'error': str(exc)}, status=400)
    return Response(result)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def operations_pause_tasks(request):
    denied = _require_admin(request)
    if denied:
        return denied
    if get_system_state(fresh=True)['mode'] == 'normal':
        return Response({'error': '请先进入排空或维护模式'}, status=400)
    return Response(pause_long_running_tasks())


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def operations_resume_tasks(request):
    denied = _require_admin(request)
    if denied:
        return denied
    return Response(resume_maintenance_tasks())


@api_view(['GET'])
@permission_classes([AllowAny])
def health_live(request):
    return Response({'status': 'ok'})


@api_view(['GET'])
@permission_classes([AllowAny])
def health_ready(request):
    checks = {'database': False, 'redis': False}
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
        checks['database'] = True
    except Exception:
        pass
    try:
        from .services import _get_redis
        checks['redis'] = bool(_get_redis().ping())
    except Exception:
        pass
    state = get_system_state(fresh=True)
    allow_maintenance = request.query_params.get('allow_maintenance') == '1'
    ready = all(checks.values()) and (allow_maintenance or state['mode'] != 'maintenance')
    return Response(
        {'status': 'ok' if ready else 'not_ready', 'checks': checks, 'mode': state['mode']},
        status=200 if ready else 503,
    )
