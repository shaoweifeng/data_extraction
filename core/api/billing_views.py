"""
计费 API

GET  /api/billing/balance/               → 当前用户余额 + 账户概览
GET  /api/billing/estimate/?ref_count=N  → 预估筛选 N 篇所需 credits
POST /api/billing/redeem/                → 兑换码充值
GET  /api/billing/transactions/          → 交易流水分页（?page=1&page_size=10）
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status as http_status

from django.db import transaction
from django.utils import timezone


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def balance(request):
    """
    返回当前用户的 credits 余额与账户概览。

    Response:
        {
            "balance": 168,
            "total_granted": 200,
            "total_consumed": 32,
            "credit_token_ratio": 1000
        }
    """
    from core.services.billing_service import get_or_create_account
    from django.conf import settings

    acct = get_or_create_account(request.user)
    return Response({
        "balance": acct.balance,
        "total_granted": acct.total_granted,
        "total_consumed": acct.total_consumed,
        "credit_token_ratio": getattr(settings, 'BILLING_CREDIT_TOKEN_RATIO', 1000),
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def estimate(request):
    """
    预估筛选 N 篇文献所需 credits 及余额是否充足。

    Query params:
        ref_count (int): 待筛选文献篇数

    Response:
        {
            "ref_count": 20,
            "estimated_credits": 40,
            "balance": 168,
            "sufficient": true
        }
    """
    from core.services.billing_service import estimate_credits, get_balance

    try:
        ref_count = int(request.query_params.get('ref_count', 0))
    except (ValueError, TypeError):
        return Response({"error": "ref_count 必须为正整数"}, status=http_status.HTTP_400_BAD_REQUEST)

    if ref_count <= 0:
        return Response({"error": "ref_count 必须为正整数"}, status=http_status.HTTP_400_BAD_REQUEST)

    estimated = estimate_credits(ref_count)
    bal = get_balance(request.user)

    return Response({
        "ref_count": ref_count,
        "estimated_credits": estimated,
        "balance": bal,
        "sufficient": bal >= estimated,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def redeem(request):
    """
    兑换码充值。

    Request body:
        { "code": "FREE-XXXX-XXXX" }

    Response (200):
        {
            "message": "兑换成功",
            "credits_added": 200,
            "new_balance": 368
        }

    Error codes:
        400  code 字段缺失
        404  兑换码不存在
        410  兑换码已被使用或已过期
    """
    from core.models_billing import RechargeCode, CreditAccount, CreditTransaction
    from django.db.models import F

    code_str = (request.data.get('code') or '').strip()
    if not code_str:
        return Response({"error": "code 不能为空"}, status=http_status.HTTP_400_BAD_REQUEST)

    # 查码（select_for_update 防并发双兑）
    try:
        with transaction.atomic():
            code_obj = RechargeCode.objects.select_for_update().get(code=code_str)

            if not code_obj.is_valid():
                return Response(
                    {"error": "兑换码已使用或已过期", "code": "code_invalid"},
                    status=http_status.HTTP_410_GONE,
                )

            credits = code_obj.credits

            # 更新账户余额（原子）
            acct, _ = CreditAccount.objects.select_for_update().get_or_create(
                user=request.user,
                defaults={'balance': 0, 'total_granted': 0, 'total_consumed': 0},
            )
            acct.balance = F('balance') + credits
            acct.total_granted = F('total_granted') + credits
            acct.save(update_fields=['balance', 'total_granted', 'updated_at'])
            acct.refresh_from_db()

            # 写流水
            CreditTransaction.objects.create(
                account=acct,
                txn_type='recharge',
                amount=credits,
                balance_after=acct.balance,
                note=f'兑换码 {code_str}',
                created_by=request.user,
            )

            # 标记码已用
            code_obj.is_used = True
            code_obj.used_by = request.user
            code_obj.used_at = timezone.now()
            code_obj.save(update_fields=['is_used', 'used_by', 'used_at'])

    except RechargeCode.DoesNotExist:
        return Response(
            {"error": "兑换码不存在", "code": "code_not_found"},
            status=http_status.HTTP_404_NOT_FOUND,
        )

    return Response({
        "message": "兑换成功",
        "credits_added": credits,
        "new_balance": acct.balance,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def transactions(request):
    """
    查询当前用户的交易流水（分页）。

    Query params:
        page       (int, default=1):   页码（从 1 开始）
        page_size  (int, default=10):  每页条数（最大 50）

    Response:
        {
            "count": 42,
            "page": 1,
            "page_size": 10,
            "total_pages": 5,
            "results": [
                {
                    "id": 7,
                    "txn_type": "recharge",
                    "txn_type_display": "充值",
                    "amount": 200,
                    "balance_after": 368,
                    "note": "兑换码 FREE-XXXX-XXXX",
                    "created_at": "2026-08-04T10:00:00+08:00"
                },
                ...
            ]
        }
    """
    from core.models_billing import CreditTransaction, CreditAccount
    import math

    # 分页参数
    try:
        page = max(1, int(request.query_params.get('page', 1)))
    except (ValueError, TypeError):
        page = 1
    try:
        page_size = min(50, max(1, int(request.query_params.get('page_size', 10))))
    except (ValueError, TypeError):
        page_size = 10

    # 获取当前用户账户
    try:
        acct = CreditAccount.objects.get(user=request.user)
    except CreditAccount.DoesNotExist:
        return Response({
            "count": 0, "page": 1, "page_size": page_size,
            "total_pages": 0, "results": [],
        })

    qs = CreditTransaction.objects.filter(account=acct).order_by('-created_at')
    total = qs.count()
    total_pages = math.ceil(total / page_size) if total > 0 else 0

    offset = (page - 1) * page_size
    items = qs[offset: offset + page_size]

    results = [
        {
            "id":               t.id,
            "txn_type":         t.txn_type,
            "txn_type_display": t.get_txn_type_display(),
            "amount":           t.amount,
            "balance_after":    t.balance_after,
            "note":             t.note,
            "created_at":       t.created_at.isoformat(),
        }
        for t in items
    ]

    return Response({
        "count":       total,
        "page":        page,
        "page_size":   page_size,
        "total_pages": total_pages,
        "results":     results,
    })
