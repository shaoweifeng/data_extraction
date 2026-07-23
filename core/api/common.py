from functools import wraps

from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response

from ..models import UserPermission


def require_permission(permission_code):
    def decorator(func):
        @wraps(func)
        def wrapper(self, request, *args, **kwargs):
            user = request.user

            if user.is_superuser:
                return func(self, request, *args, **kwargs)

            has_perm = UserPermission.objects.filter(
                user=user,
                permission__code=permission_code,
            ).filter(
                Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
            ).exists()

            if not has_perm:
                return Response(
                    {"error": f"缺少权限：{permission_code}"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            return func(self, request, *args, **kwargs)

        return wrapper

    return decorator

