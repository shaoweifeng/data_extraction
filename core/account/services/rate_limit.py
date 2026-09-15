from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from functools import lru_cache

from django.conf import settings

logger = logging.getLogger(__name__)

_CONSUME_LUA = """
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
local limit = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
if current >= limit then
    return {0, current, math.max(0, redis.call('TTL', KEYS[1]))}
end
current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], window)
end
return {1, current, math.max(0, redis.call('TTL', KEYS[1]))}
"""

_REFUND_LUA = """
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
if current <= 1 then
    redis.call('DEL', KEYS[1])
    return 0
end
return redis.call('DECR', KEYS[1])
"""


class RateLimitUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    count: int = 0
    retry_after: int = 0
    key: str | None = None
    unavailable: bool = False


@lru_cache(maxsize=4)
def _build_client(url: str):
    import redis

    return redis.from_url(url, decode_responses=True, protocol=2)


def _client():
    url = getattr(settings, 'RATE_LIMIT_REDIS_URL', '')
    if not url:
        raise RateLimitUnavailable('RATE_LIMIT_REDIS_URL 未配置')
    return _build_client(url)


def _key(scope: str, identifier: str) -> str:
    prefix = getattr(settings, 'ACCOUNT_RATE_LIMIT_PREFIX', 'account:rate')
    digest = hashlib.sha256(identifier.encode('utf-8')).hexdigest()
    return f'{prefix}:{scope}:{digest}'


def consume_rate_limit(
    scope: str,
    identifier: str,
    *,
    limit: int,
    window_seconds: int,
    fail_closed: bool,
) -> RateLimitDecision:
    if not getattr(settings, 'ACCOUNT_RATE_LIMIT_ENABLED', False):
        return RateLimitDecision(allowed=True)

    key = _key(scope, identifier)
    try:
        allowed, count, ttl = _client().eval(
            _CONSUME_LUA,
            1,
            key,
            int(limit),
            int(window_seconds),
        )
        return RateLimitDecision(bool(allowed), int(count), int(ttl), key)
    except Exception as exc:
        logger.error('[账户限流] Redis 操作失败 scope=%s: %s', scope, exc)
        if fail_closed:
            raise RateLimitUnavailable('账户安全服务暂时不可用') from exc
        return RateLimitDecision(allowed=True, unavailable=True)


def refund_rate_limit(decision: RateLimitDecision) -> None:
    if not decision.key:
        return
    try:
        _client().eval(_REFUND_LUA, 1, decision.key)
    except Exception as exc:
        logger.warning('[账户限流] 回退计数失败: %s', exc)
