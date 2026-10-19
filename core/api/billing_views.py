"""
计费 API

GET  /api/billing/balance/               → 当前用户余额 + 账户概览
GET  /api/billing/plans/                 → 当前权益、待生效权益和可售套餐
GET  /api/billing/batches/               → 当前用户积分批次与有效期
GET  /api/billing/estimate/?ref_count=N  → 预估筛选 N 篇所需 credits
POST /api/billing/redeem/                → 兑换码充值
GET  /api/billing/transactions/          → 交易流水分页（?page=1&page_size=10）
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status as http_status

from django.db import models, transaction
from django.conf import settings
from django.utils import timezone
from core.ai.quota import is_unlimited_ai_user


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def balance(request):
    """
    返回当前用户的 credits 余额与账户概览。

    Response:
        {
            "balance": 168,
            "total_granted": 200,
            "total_consumed": 32
        }
    """
    from core.services.billing_service import get_or_create_account
    user = request.user
    is_unlimited = is_unlimited_ai_user(user)
    from core.services.entitlement_service import resolve_user_entitlements
    plan = resolve_user_entitlements(user).as_dict()

    if is_unlimited:
        return Response({
            "balance": None,          # None 表示无限额度，前端显示 ∞
            "total_granted": None,
            "total_consumed": None,
            "is_unlimited": True,
            "plan": plan,
        })

    acct = get_or_create_account(user)
    return Response({
        "balance": acct.balance,
        "total_granted": acct.total_granted,
        "total_consumed": acct.total_consumed,
        "is_unlimited": False,
        "plan": plan,
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
        # model_ids: 逗号分隔字符串，如 "deepseek-v4-flash,doubao-seed-1.8"
        model_ids_raw = request.query_params.get('model_ids', '')
        model_ids = [m.strip() for m in model_ids_raw.split(',') if m.strip()] if model_ids_raw else []

        # 向后兼容：若只传 model_count（旧逻辑），用默认费率 × model_count
        if not model_ids:
            model_count = max(1, int(request.query_params.get('model_count', 1)))
        else:
            model_count = len(model_ids)
    except (ValueError, TypeError):
        return Response({"error": "ref_count 必须为正整数"}, status=http_status.HTTP_400_BAD_REQUEST)

    if ref_count <= 0:
        return Response({"error": "ref_count 必须为正整数"}, status=http_status.HTTP_400_BAD_REQUEST)

    feature = request.query_params.get('feature', 'ai_screen')
    if feature not in {'ai_screen', 'qa_eval'}:
        return Response({"error": "feature 仅支持 ai_screen 或 qa_eval"}, status=http_status.HTTP_400_BAD_REQUEST)
    estimate_detail = None
    if model_ids:
        if getattr(settings, 'MODEL_WEIGHTED_BILLING_ENABLED', False):
            from core.services.billing_estimate_service import (
                BillingEstimateError, estimate_model_credits,
            )
            try:
                estimate_detail = estimate_model_credits(
                    ref_count,
                    model_ids,
                    feature=feature,
                )
            except BillingEstimateError as exc:
                return Response(
                    {"error": str(exc), "code": "billing_rate_unavailable"},
                    status=http_status.HTTP_409_CONFLICT,
                )
            estimated = estimate_detail['reserve_credits']
        else:
            estimated = estimate_credits(ref_count, model_ids, feature=feature)
    else:
        estimated = estimate_credits(ref_count, feature=feature) * model_count
    user = request.user
    is_unlimited = is_unlimited_ai_user(user)

    if is_unlimited:
        response = {
            "ref_count": ref_count,
            "estimated_credits": estimated,
            "balance": None,
            "sufficient": True,
            "is_unlimited": True,
        }
        if estimate_detail:
            response['estimate_detail'] = estimate_detail
        return Response(response)

    bal = get_balance(user)
    response = {
        "ref_count": ref_count,
        "estimated_credits": estimated,
        "balance": bal,
        "sufficient": bal >= estimated,
        "is_unlimited": False,
    }
    if estimate_detail:
        response['estimate_detail'] = estimate_detail
    return Response(response)


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
    from django.conf import settings
    from core.models_billing import RechargeCode, CreditAccount, CreditTransaction
    from django.db.models import F

    code_str = (request.data.get('code') or '').strip()
    if not code_str:
        return Response({"error": "code 不能为空"}, status=http_status.HTTP_400_BAD_REQUEST)

    if getattr(settings, 'CREDIT_BATCH_LEDGER_ENABLED', False):
        from core.services.credit_ledger_service import CreditLedgerError, redeem_credit_code

        code_type = RechargeCode.objects.filter(code=code_str).values_list(
            'code_type', flat=True,
        ).first()
        if code_type == 'PLAN':
            from core.services.entitlement_service import EntitlementError, redeem_plan_code

            try:
                entitlement = redeem_plan_code(request.user, code_str)
            except EntitlementError as exc:
                error = str(exc)
                status_map = {
                    'code_not_found': http_status.HTTP_404_NOT_FOUND,
                    'code_invalid': http_status.HTTP_410_GONE,
                    'future_plan_change_exists': http_status.HTTP_409_CONFLICT,
                    'plan_version_unavailable': http_status.HTTP_409_CONFLICT,
                    'plan_billing_disabled': http_status.HTTP_409_CONFLICT,
                }
                messages = {
                    'code_not_found': '兑换码不存在',
                    'code_invalid': '兑换码已使用或已过期',
                    'future_plan_change_exists': '已有其他套餐的待生效换档安排',
                    'plan_version_unavailable': '该套餐版本当前不可开通',
                    'plan_billing_disabled': '套餐功能暂未开放',
                }
                return Response(
                    {'error': messages.get(error, error), 'code': error},
                    status=status_map.get(error, http_status.HTTP_400_BAD_REQUEST),
                )
            from core.services.billing_service import get_balance
            from core.services.entitlement_service import resolve_user_entitlements

            now = timezone.now()
            active_period = entitlement.billing_periods.filter(
                period_start__lte=now,
                period_end__gt=now,
                grant_status='granted',
                grant_batch__isnull=False,
            ).select_related('grant_batch').first()
            return Response({
                'message': '套餐兑换成功',
                'credits_added': active_period.grant_batch.granted_amount if active_period else 0,
                'new_balance': get_balance(request.user),
                'plan': resolve_user_entitlements(request.user).as_dict(),
                'entitlement_id': entitlement.pk,
            })

        try:
            txn = redeem_credit_code(request.user, code_str)
        except CreditLedgerError as exc:
            error = str(exc)
            if error == 'code_not_found':
                return Response(
                    {"error": "兑换码不存在", "code": error},
                    status=http_status.HTTP_404_NOT_FOUND,
                )
            if error == 'code_invalid':
                return Response(
                    {"error": "兑换码已使用或已过期", "code": error},
                    status=http_status.HTTP_410_GONE,
                )
            if error == 'plan_code_not_available':
                return Response(
                    {"error": "套餐兑换将在套餐功能启用后开放", "code": error},
                    status=http_status.HTTP_409_CONFLICT,
                )
            return Response(
                {"error": error, "code": "redeem_failed"},
                status=http_status.HTTP_400_BAD_REQUEST,
            )
        return Response({
            "message": "兑换成功",
            "credits_added": txn.amount,
            "new_balance": txn.balance_after,
        })

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
def plans(request):
    """Return published personal plan versions and the caller's current rights."""
    from core.models_billing import PlanPriceVersion, UserPlanEntitlement
    from core.services.entitlement_service import resolve_user_entitlements

    now = timezone.now()
    rows = (
        PlanPriceVersion.objects.filter(
            status='published', plan__is_active=True,
        ).filter(
            models.Q(effective_from__isnull=True) | models.Q(effective_from__lte=now),
        ).filter(
            models.Q(effective_until__isnull=True) | models.Q(effective_until__gt=now),
        ).select_related('plan').order_by('monthly_price_cny', 'pk')
    )
    scheduled = UserPlanEntitlement.objects.filter(
        user=request.user,
        status='scheduled',
        starts_at__gt=now,
    ).select_related('price_version__plan').order_by('starts_at', 'pk')
    return Response({
        'current': resolve_user_entitlements(request.user).as_dict(),
        'scheduled': [{
            'plan_code': item.price_version.plan.code,
            'plan_name': item.price_version.plan.name,
            'version': item.price_version.version,
            'starts_at': item.starts_at.isoformat(),
            'expires_at': item.expires_at.isoformat(),
        } for item in scheduled],
        'plans': [{
            'plan_code': row.plan.code,
            'name': row.plan.name,
            'description': row.plan.description,
            'version': row.version,
            'monthly_price_cny': str(row.monthly_price_cny),
            'included_credits': row.included_credits,
            'ai_call_slots': row.ai_call_slots,
            'project_limit': row.project_limit,
            'storage_limit_mb': row.storage_limit_mb,
            'valid_months': row.valid_months,
        } for row in rows],
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def credit_batches(request):
    """Return only the caller's credit batches, including expiry and reservations."""
    import math

    from core.models_billing import CreditAccount, CreditGrantBatch

    try:
        page = max(1, int(request.query_params.get('page', 1)))
        page_size = min(50, max(1, int(request.query_params.get('page_size', 10))))
    except (TypeError, ValueError):
        return Response(
            {'error': 'page 和 page_size 必须为正整数'},
            status=http_status.HTTP_400_BAD_REQUEST,
        )
    account = CreditAccount.objects.filter(user=request.user).first()
    if account is None:
        return Response({
            'count': 0, 'page': 1, 'page_size': page_size,
            'total_pages': 0, 'results': [],
        })
    rows = CreditGrantBatch.objects.filter(account=account).select_related(
        'entitlement__price_version__plan',
    ).order_by(
        models.F('expires_at').asc(nulls_last=True), '-created_at',
    )
    total = rows.count()
    offset = (page - 1) * page_size
    now = timezone.now()
    return Response({
        'count': total,
        'page': page,
        'page_size': page_size,
        'total_pages': math.ceil(total / page_size) if total else 0,
        'results': [{
            'id': row.pk,
            'batch_type': row.batch_type,
            'batch_type_display': row.get_batch_type_display(),
            'granted_amount': row.granted_amount,
            'remaining_amount': row.remaining_amount,
            'reserved_amount': row.reserved_amount,
            'expires_at': row.expires_at.isoformat() if row.expires_at else None,
            'is_expired': bool(row.expires_at and row.expires_at <= now),
            'plan_name': (
                row.entitlement.price_version.plan.name if row.entitlement_id else ''
            ),
            'created_at': row.created_at.isoformat(),
        } for row in rows[offset:offset + page_size]],
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
    items = list(qs[offset: offset + page_size])

    from collections import defaultdict
    from core.models_billing import TokenUsageLog
    from core.services.ai_models_config import get_model_config

    usage_by_transaction = defaultdict(list)
    usage_logs = TokenUsageLog.objects.filter(
        transaction_id__in=[item.pk for item in items],
    ).select_related('project').prefetch_related('call_details')
    for log in usage_logs:
        models_map = {}
        for detail in log.call_details.all():
            model = models_map.setdefault(detail.model_id, {
                'model_id': detail.model_id,
                'model_name': (get_model_config(detail.model_id) or {}).get(
                    'name', detail.model_id,
                ),
                'calls': 0,
                'raw_credits': 0,
            })
            model['calls'] += 1
            model['raw_credits'] += detail.raw_credits or 0
        usage_by_transaction[log.transaction_id].append({
            'usage_log_id': log.pk,
            'project_id': log.project_id,
            'project_name': log.project.name if log.project_id else '',
            'task_id': log.task_id,
            'pricing_version': log.pricing_version,
            'credits_consumed': log.credits_consumed,
            'models': [{**value, 'raw_credits': str(value['raw_credits'])}
                       for value in models_map.values()],
        })

    results = [
        {
            "id":               t.id,
            "txn_type":         t.txn_type,
            "txn_type_display": t.get_txn_type_display(),
            "amount":           t.amount,
            "balance_after":    t.balance_after,
            "note":             t.note,
            "created_at":       t.created_at.isoformat(),
            "usage":            usage_by_transaction.get(t.pk, []),
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
