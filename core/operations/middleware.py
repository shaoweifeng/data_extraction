from django.http import JsonResponse

from .services import get_system_state, is_platform_admin


_ALWAYS_ALLOWED_PREFIXES = (
    '/api/system/status/',
    '/api/health/',
    '/api/presence/heartbeat/',
    '/api/operations/',
    '/api/auth/logout/',
    '/api/auth/me/',
    '/admin/',
    '/static/',
    '/assets/',
    '/media/',
)

_DRAIN_BLOCKED_PREFIXES = (
    '/api/qa/refs/import/',
    '/api/qa/refs/upload/',
    '/api/qa/eval/start/',
    '/api/qa/chart/generate/',
    '/api/qa/export/excel/',
)


def _starts_new_work(request):
    path = request.path
    if request.method == 'DELETE':
        return True
    if request.method not in ('POST', 'PUT', 'PATCH'):
        return False
    if path == '/api/projects/' or path == '/api/files/' or path == '/api/tasks/':
        return True
    if any(path.startswith(prefix) for prefix in _DRAIN_BLOCKED_PREFIXES):
        return True
    return path.endswith('/start/') or path.endswith('/resume/')


class MaintenanceModeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith('/api/') or request.path.startswith(_ALWAYS_ALLOWED_PREFIXES):
            return self.get_response(request)
        state = get_system_state()
        if state['mode'] == 'normal' or is_platform_admin(getattr(request, 'user', None)):
            return self.get_response(request)
        if state['mode'] == 'maintenance':
            return JsonResponse(
                {'code': 'SYSTEM_MAINTENANCE', 'message': state['message'] or '平台正在维护，请稍后再试'},
                status=503,
                headers={'Retry-After': '60'},
            )
        if state['mode'] == 'draining' and _starts_new_work(request):
            return JsonResponse(
                {'code': 'SYSTEM_DRAINING', 'message': state['message'] or '平台即将维护，暂时不能启动新任务'},
                status=503,
                headers={'Retry-After': '60'},
            )
        return self.get_response(request)
