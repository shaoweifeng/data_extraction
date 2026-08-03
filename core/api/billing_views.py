"""
计费 API

GET  /api/billing/balance/               → 当前用户余额 + 账户概览
GET  /api/billing/estimate/?ref_count=N  → 预估筛选 N 篇所需 credits
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status


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
        return Response({"error": "ref_count 必须为正整数"}, status=status.HTTP_400_BAD_REQUEST)

    if ref_count <= 0:
        return Response({"error": "ref_count 必须为正整数"}, status=status.HTTP_400_BAD_REQUEST)

    estimated = estimate_credits(ref_count)
    balance = get_balance(request.user)

    return Response({
        "ref_count": ref_count,
        "estimated_credits": estimated,
        "balance": balance,
        "sufficient": balance >= estimated,
    })
