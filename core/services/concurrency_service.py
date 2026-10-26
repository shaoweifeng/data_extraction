"""Redis-backed global and per-user aggregate AI call-slot leases."""

import logging
import time

from django.conf import settings

logger = logging.getLogger(__name__)

_QUEUE_KEY = 'ai_slots:v2:queue'
_LEASES_KEY = 'ai_slots:v2:leases'
_FALLBACK_TASKS = set()

_ACQUIRE_LUA = """
local queue_key = KEYS[1]
local leases_key = KEYS[2]
local global_limit = tonumber(ARGV[1])
local user_limit = tonumber(ARGV[2])
local slots_need = tonumber(ARGV[3])
local member = ARGV[4]
local user_id = ARGV[5]
local now_ts = tonumber(ARGV[6])
local expires_ts = tonumber(ARGV[7])
local queue_cutoff_ts = tonumber(ARGV[8])

redis.call('ZREMRANGEBYSCORE', leases_key, '-inf', now_ts)
redis.call('ZREMRANGEBYSCORE', queue_key, '-inf', queue_cutoff_ts)
-- A queued task may change its requested size after an entitlement expires.
-- Remove its obsolete queue member or it can block its own new request.
local task_prefix = string.match(member, '^[^:]+:')
for _, queued in ipairs(redis.call('ZRANGE', queue_key, 0, -1)) do
    if queued ~= member and string.sub(queued, 1, string.len(task_prefix)) == task_prefix then
        redis.call('ZREM', queue_key, queued)
    end
end
if redis.call('ZSCORE', leases_key, member) ~= false then
    redis.call('ZADD', leases_key, expires_ts, member)
    redis.call('ZREM', queue_key, member)
    return 1
end

local global_used = 0
local user_used = 0
local leases = redis.call('ZRANGE', leases_key, 0, -1)
for _, lease in ipairs(leases) do
    local _, _, lease_user, lease_slots = string.find(lease, '^[^:]+:([^:]+):([^:]+)$')
    local n = tonumber(lease_slots) or 0
    global_used = global_used + n
    if lease_user == user_id then user_used = user_used + n end
end

local queue_head = redis.call('ZRANGE', queue_key, 0, 0)[1]
local can_try = (queue_head == nil or queue_head == false or queue_head == member)
if can_try and global_used + slots_need <= global_limit and user_used + slots_need <= user_limit then
    redis.call('ZADD', leases_key, expires_ts, member)
    redis.call('ZREM', queue_key, member)
    return 1
end
if redis.call('ZSCORE', queue_key, member) == false then
    redis.call('ZADD', queue_key, now_ts, member)
end
return 0
"""

_RELEASE_LUA = """
local queue_key = KEYS[1]
local leases_key = KEYS[2]
local task_id = ARGV[1]
local prefix = task_id .. ':'
for _, member in ipairs(redis.call('ZRANGE', leases_key, 0, -1)) do
    if string.sub(member, 1, string.len(prefix)) == prefix then
        redis.call('ZREM', leases_key, member)
    end
end
for _, member in ipairs(redis.call('ZRANGE', queue_key, 0, -1)) do
    if string.sub(member, 1, string.len(prefix)) == prefix then
        redis.call('ZREM', queue_key, member)
    end
end
return 1
"""


def _get_redis():
    import redis as redis_lib

    return redis_lib.from_url(
        getattr(settings, 'CELERY_BROKER_URL', 'redis://localhost:6379/0'),
        decode_responses=True,
    )


def get_user_concurrency(user) -> int:
    """Resolve the single entitlement source instead of legacy profile fields."""
    if user is None:
        return int(getattr(settings, 'PLAN_FREE_AI_CALL_SLOTS', 2))
    from core.services.entitlement_service import resolve_user_entitlements

    return max(1, int(resolve_user_entitlements(user).ai_call_slots))


def slots_for_task(task, user_limit: int) -> int:
    """Screening uses its worker pool; QA currently issues one call at a time."""
    if task.task_type == 'ai_screen':
        configured = (task.config or {}).get('concurrency')
        return min(user_limit, max(1, int(configured or user_limit)))
    return 1


def refresh_task_slots(task, *, stop_checker=lambda: False) -> int:
    """Reacquire only at a safe boundary, after all current calls have finished.

    Release before waiting so downgraded tasks cannot deadlock by retaining
    old leases. Requests already sent to providers are never interrupted.
    """
    if not (task.config or {}).get('ai_slot_lease'):
        return slots_for_task(task, get_user_concurrency(task.created_by))
    release(task.pk)
    while not stop_checker():
        user_limit = get_user_concurrency(task.created_by)
        slots = slots_for_task(task, user_limit)
        if try_acquire(task.pk, slots, user_id=task.created_by_id, user_limit=user_limit):
            lease = {
                'user_id': task.created_by_id, 'slots': slots, 'user_limit': user_limit,
                'redis_fallback': acquire_used_fallback(task.pk),
            }
            task.refresh_from_db(fields=['config'])
            task.config = {**(task.config or {}), 'ai_slot_lease': lease}
            task.save(update_fields=['config'])
            return slots
        time.sleep(1)
    release(task.pk)
    return 0


def _make_member(task_id: int, user_id: int, slots: int) -> str:
    return f'{task_id}:{user_id}:{slots}'


def try_acquire(task_id: int, slots: int, *, user_id: int = 0, user_limit: int | None = None) -> bool:
    global_limit = int(getattr(settings, 'AI_SCREEN_MAX_GLOBAL_THREADS', 64))
    user_limit = max(1, int(user_limit or global_limit))
    now = time.time()
    ttl = max(60, int(getattr(settings, 'AI_SLOT_LEASE_TTL_SECONDS', 86400)))
    queue_ttl = max(60, int(getattr(settings, 'AI_SLOT_QUEUE_TTL_SECONDS', ttl)))
    member = _make_member(task_id, user_id, slots)
    try:
        acquired = bool(_get_redis().eval(
            _ACQUIRE_LUA, 2, _QUEUE_KEY, _LEASES_KEY,
            str(global_limit), str(user_limit), str(slots), member,
            str(user_id), str(now), str(now + ttl), str(now - queue_ttl),
        ))
        logger.info(
            '[并发] task=%s user=%s slots=%s result=%s',
            task_id, user_id, slots, 'acquired' if acquired else 'queued',
        )
        _FALLBACK_TASKS.discard(task_id)
        return acquired
    except Exception as exc:
        logger.warning('[并发] Redis 占槽失败，降级执行 task=%s: %s', task_id, exc)
        _FALLBACK_TASKS.add(task_id)
        return True


def acquire_used_fallback(task_id: int) -> bool:
    """Return and clear the current-process audit marker for a fail-open claim."""
    if task_id in _FALLBACK_TASKS:
        _FALLBACK_TASKS.discard(task_id)
        return True
    return False


def release(task_id: int, slots: int = 0, *, user_id: int = 0) -> None:
    try:
        _get_redis().eval(_RELEASE_LUA, 2, _QUEUE_KEY, _LEASES_KEY, str(task_id))
        logger.info('[并发] task=%s user=%s 已归还槽位', task_id, user_id)
    except Exception as exc:
        logger.warning('[并发] release 失败: %s', exc)


def _lease_usage(r, now: float, user_id: int) -> tuple[int, int]:
    r.zremrangebyscore(_LEASES_KEY, '-inf', now)
    global_used = 0
    user_used = 0
    for member in r.zrange(_LEASES_KEY, 0, -1):
        try:
            _, lease_user, lease_slots = member.split(':', 2)
            lease_slots = int(lease_slots)
        except (TypeError, ValueError):
            continue
        global_used += lease_slots
        if str(lease_user) == str(user_id):
            user_used += lease_slots
    return global_used, user_used


def get_queue_info(
    task_id: int,
    slots: int,
    *,
    user_id: int = 0,
    user_limit: int | None = None,
) -> dict:
    global_limit = int(getattr(settings, 'AI_SCREEN_MAX_GLOBAL_THREADS', 64))
    user_limit = max(1, int(user_limit or global_limit))
    member = _make_member(task_id, user_id, slots)
    try:
        r = _get_redis()
        queue_ttl = max(60, int(getattr(settings, 'AI_SLOT_QUEUE_TTL_SECONDS', 86400)))
        r.zremrangebyscore(_QUEUE_KEY, '-inf', time.time() - queue_ttl)
        global_used, user_used = _lease_usage(r, time.time(), user_id)
        rank = r.zrank(_QUEUE_KEY, member)
        return {
            'position': rank + 1 if rank is not None else 0,
            'queue_length': r.zcard(_QUEUE_KEY),
            'slots_used': global_used,
            'slots_total': global_limit,
            'slots_free': max(0, global_limit - global_used),
            'user_slots_used': user_used,
            'user_slots_total': user_limit,
            'user_slots_free': max(0, user_limit - user_used),
        }
    except Exception as exc:
        logger.warning('[并发] get_queue_info 失败: %s', exc)
        return {
            'position': 0, 'queue_length': 0, 'slots_used': 0,
            'slots_total': global_limit, 'slots_free': global_limit,
            'user_slots_used': 0, 'user_slots_total': user_limit,
            'user_slots_free': user_limit,
        }


def cancel_queue(task_id: int, slots: int = 0) -> None:
    release(task_id, slots)


def reset_slots(force: bool = False) -> None:
    try:
        r = _get_redis()
        r.delete(_LEASES_KEY)
        if force:
            r.delete(_QUEUE_KEY)
        logger.warning('[并发] AI 槽位租约已重置')
    except Exception as exc:
        logger.error('[并发] reset_slots 失败: %s', exc)
