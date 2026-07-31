from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from django.utils import timezone

from django.contrib.auth.models import User

from ..models import RoleTemplate, UserPermission
from ..serializers import UserSerializer
from .common import require_permission


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    @require_permission('user.view_all')
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @action(detail=True, methods=['post'])
    @require_permission('user.approve')
    def approve(self, request, pk=None):
        user = self.get_object()
        profile = user.profile

        profile.is_approved = True
        profile.approved_at = timezone.now()
        profile.approved_by = request.user
        profile.save()

        try:
            template = RoleTemplate.objects.get(name='标准研究者')
            for rtp in template.template_permissions.all():
                UserPermission.objects.get_or_create(
                    user=user,
                    permission=rtp.permission,
                    defaults={'granted_by': request.user, 'granted_at': timezone.now()},
                )
        except RoleTemplate.DoesNotExist:
            pass

        return Response({"message": "用户已审核通过并授予基础权限", "user": UserSerializer(user).data})

    @action(detail=True, methods=['post'])
    @require_permission('user.approve')
    def ban(self, request, pk=None):
        """封禁用户（禁止登录）。超级用户不可被封禁。"""
        user = self.get_object()
        if user.is_superuser:
            return Response({"error": "不能封禁超级用户"}, status=400)
        profile = user.profile
        profile.is_banned = True
        profile.save(update_fields=['is_banned', 'updated_at'])
        return Response({"message": "用户已封禁", "user": UserSerializer(user).data})

    @action(detail=True, methods=['post'])
    @require_permission('user.approve')
    def unban(self, request, pk=None):
        """解封用户。"""
        user = self.get_object()
        profile = user.profile
        profile.is_banned = False
        profile.save(update_fields=['is_banned', 'updated_at'])
        return Response({"message": "用户已解封", "user": UserSerializer(user).data})

