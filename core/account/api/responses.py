from rest_framework import status
from rest_framework.response import Response

from ..services.rate_limit import RateLimitDecision


def rate_limited_response(decision: RateLimitDecision) -> Response:
    response = Response(
        {'error': '请求过于频繁，请稍后再试', 'code': 'rate_limited'},
        status=status.HTTP_429_TOO_MANY_REQUESTS,
    )
    if decision.retry_after:
        response['Retry-After'] = str(decision.retry_after)
    return response
