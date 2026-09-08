from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from django.utils import timezone

from django.contrib.auth.models import User

from ..models import UserPermission
from ..serializers import UserSerializer
from .common import require_permission
from ..services.access_policy import ProjectAccessPolicy


class UserViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if ProjectAccessPolicy.is_platform_admin(self.request.user):
            return User.objects.all()
        return User.objects.filter(pk=self.request.user.pk)

    @require_permission('user.view_all')
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @action(detail=True, methods=['post'])
    @require_permission('user.approve')
    def approve(self, request, pk=None):
        """手动审核用户（现已免审核，保留接口做管理员补操作用）。"""
        user = self.get_object()
        profile = user.profile
        profile.is_approved = True
        profile.approved_at = timezone.now()
        profile.approved_by = request.user
        profile.save()
        return Response({"message": "用户审核已通过", "user": UserSerializer(user).data})

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

    @action(detail=True, methods=['post'])
    @require_permission('user.approve')
    def adjust_credits(self, request, pk=None):
        """
        管理员手动调整用户 credits 余额。

        Request body:
            {
                "amount": 500,      # 正数=充值，负数=扣除
                "note": "活动赠送"  # 可选备注
            }

        Response (200):
            {
                "message": "调额成功",
                "username": "alice",
                "amount": 500,
                "new_balance": 700
            }
        """
        from core.models_billing import CreditAccount, CreditTransaction
        from django.db import transaction as db_transaction
        from django.db.models import F

        target_user = self.get_object()

        # 参数校验
        try:
            amount = int(request.data.get('amount', 0))
        except (ValueError, TypeError):
            return Response({"error": "amount 必须为整数"}, status=400)
        if amount == 0:
            return Response({"error": "amount 不能为 0"}, status=400)

        note = (request.data.get('note') or '').strip() or '管理员调额'

        with db_transaction.atomic():
            acct, _ = CreditAccount.objects.select_for_update().get_or_create(
                user=target_user,
                defaults={'balance': 0, 'total_granted': 0, 'total_consumed': 0},
            )

            # 防止余额被调成负数
            if amount < 0 and acct.balance + amount < 0:
                return Response(
                    {"error": f"扣除后余额将为负数（当前余额 {acct.balance}），操作拒绝"},
                    status=400,
                )

            acct.balance = F('balance') + amount
            if amount > 0:
                acct.total_granted = F('total_granted') + amount
            acct.save(update_fields=['balance', 'total_granted', 'updated_at'])
            acct.refresh_from_db()

            CreditTransaction.objects.create(
                account=acct,
                txn_type='adjust',
                amount=amount,
                balance_after=acct.balance,
                note=note,
                created_by=request.user,
            )

        sign = '+' if amount > 0 else ''
        return Response({
            "message": "调额成功",
            "username": target_user.username,
            "amount": amount,
            "amount_display": f"{sign}{amount} credits",
            "new_balance": acct.balance,
            "note": note,
        })
