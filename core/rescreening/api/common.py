"""Shared validation, authorization and bounded pagination."""
from functools import wraps
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.core.paginator import Paginator
from rest_framework.response import Response
from core.rescreening.errors import RescreenError
from core.screening.services.import_errors import ScreeningImportError
from core.services.access_policy import ProjectAccessPolicy
from core.services.storage_quota_service import StorageQuotaExceeded
from core.fulltext.errors import FulltextError


def boundary(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (RescreenError, FulltextError) as exc:
            return Response({'ok': False, 'code': exc.code, 'error': str(exc)}, status=exc.status)
        except ScreeningImportError as exc:
            return Response({'ok': False, 'code': exc.code, 'error': str(exc)}, status=exc.http_status)
        except StorageQuotaExceeded as exc:
            return Response({'ok': False, 'code': exc.code, 'error': str(exc)}, status=413)
        except ObjectDoesNotExist:
            return Response({'ok': False, 'code': 'not_found', 'error': '资源不存在。'}, status=404)
        except PermissionDenied:
            return Response({'ok': False, 'code': 'permission_denied', 'error': '无权访问该项目或资源。'}, status=403)
    return wrapped


def integer(value, name, *, minimum=1, maximum=None):
    if isinstance(value, (bool, float)):
        raise RescreenError('invalid_parameter', f'{name} 必须是整数。')
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        raise RescreenError('invalid_parameter', f'{name} 必须是整数。')
    if result < minimum or (maximum is not None and result > maximum):
        raise RescreenError('invalid_parameter', f'{name} 超出允许范围。')
    return result


def project_for(request):
    data = request.query_params if request.method == 'GET' else request.data
    return ProjectAccessPolicy.require_project(request.user, integer(data.get('project_id'), 'project_id'))


def visible(queryset, user):
    return queryset.filter(project__in=ProjectAccessPolicy.visible_projects(user))


def paginated(queryset, request, serialize):
    page = integer(request.query_params.get('page', 1), 'page')
    size = integer(request.query_params.get('page_size', 50), 'page_size', maximum=200)
    paginator = Paginator(queryset, size)
    if page > paginator.num_pages:
        raise RescreenError('invalid_page', '页码超出范围。')
    current = paginator.page(page)
    return {'items': [serialize(item) for item in current], 'total': paginator.count,
            'page': page, 'page_size': size, 'pages': paginator.num_pages}
