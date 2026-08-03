"""
全局 AI 筛选并发控制服务（阶段四）

设计：
  - Redis key `ai_screen:slots`（整数）：当前已占用的线程槽数
  - Redis ZSET `ai_screen:queue`（score=入队时间戳）：等待中的任务队列
    member 格式："{task_id}:{slots_needed}"

接口：
  - get_user_concurrency(user)   → 该用户应使用的并发线程数
  - try_acquire(task_id, slots)  → 原子尝试占槽，成功返回 True，否则入队返回 False
  - release(task_id, slots)      → 归还槽位，并唤醒队首任务
  - get_queue_position(task_id, slots) → 返回排队位置（1-based）和队列信息
  - cancel_queue(task_id, slots) → 从队列中移除（用户取消排队）
"""

import time
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

# Redis key
_SLOTS_KEY = "ai_screen:slots"
_QUEUE_KEY = "ai_screen:queue"

# Lua 脚本：原子尝试占槽
# 逻辑：
#   1. 如果队列为空，或我已在队列且是队首 → 尝试占槽
#   2. 占槽成功则从队列移除（如果在的话），返回 1
#   3. 占槽失败 → 如果还不在队列里则入队（ZADD NX），返回 0
_ACQUIRE_LUA = """
local slots_key = KEYS[1]
local queue_key = KEYS[2]
local max_slots = tonumber(ARGV[1])
local slots_need = tonumber(ARGV[2])
local member = ARGV[3]
local now_ts = tonumber(ARGV[4])

local used = tonumber(redis.call('GET', slots_key) or 0)
local queue_head = redis.call('ZRANGE', queue_key, 0, 0)[1]

-- 只有在队列为空或自己是队首时才允许抢槽
local can_try = (queue_head == nil or queue_head == false or queue_head == member)

if can_try and (used + slots_need <= max_slots) then
    redis.call('INCRBY', slots_key, slots_need)
    redis.call('ZREM', queue_key, member)
    return 1
else
    -- 不在队列里则入队（NX 防止重复入队改变score）
    local score = redis.call('ZSCORE', queue_key, member)
    if score == false then
        redis.call('ZADD', queue_key, now_ts, member)
    end
    return 0
end
"""

# Lua 脚本：归还槽位
_RELEASE_LUA = """
local slots_key = KEYS[1]
local slots_need = tonumber(ARGV[1])
local current = tonumber(redis.call('GET', slots_key) or 0)
local new_val = math.max(0, current - slots_need)
redis.call('SET', slots_key, new_val)
return new_val
"""


def _get_redis():
    """获取 Django-Celery 复用的 Redis 连接（不引入新依赖）。"""
    import redis as redis_lib
    url = getattr(settings, 'CELERY_BROKER_URL', 'redis://localhost:6379/0')
    return redis_lib.from_url(url, decode_responses=True)


def get_user_concurrency(user) -> int:
    """
    获取用户的 AI 筛选并发线程数。

    优先级：
      1. superuser / admin 角色 → AI_SCREEN_ADMIN_CONCURRENCY（默认 16）
      2. profile.concurrency_limit 有值 → 使用该值
      3. fallback → AI_SCREEN_DEFAULT_CONCURRENCY（默认 2）
    """
    admin_conc = getattr(settings, 'AI_SCREEN_ADMIN_CONCURRENCY', 16)
    default_conc = getattr(settings, 'AI_SCREEN_DEFAULT_CONCURRENCY', 2)

    if user is None:
        return default_conc

    profile = getattr(user, 'profile', None)
    if user.is_superuser or (profile and profile.role == 'admin'):
        return admin_conc

    if profile and profile.concurrency_limit:
        return int(profile.concurrency_limit)

    return default_conc


def _make_member(task_id: int, slots: int) -> str:
    return f"{task_id}:{slots}"


def try_acquire(task_id: int, slots: int) -> bool:
    """
    原子尝试为 task_id 占用 slots 个线程槽。

    Returns:
        True  → 占槽成功，任务可以立即开始
        False → 槽位不足，已入队等待
    """
    max_slots = getattr(settings, 'AI_SCREEN_MAX_GLOBAL_THREADS', 64)
    member = _make_member(task_id, slots)
    try:
        r = _get_redis()
        result = r.eval(
            _ACQUIRE_LUA,
            2,
            _SLOTS_KEY, _QUEUE_KEY,
            str(max_slots), str(slots), member, str(time.time()),
        )
        acquired = bool(result)
        if acquired:
            logger.info(f"[并发] task={task_id} 抢到 {slots} 槽")
        else:
            logger.info(f"[并发] task={task_id} 槽不足，进入排队队列")
        return acquired
    except Exception as e:
        logger.warning(f"[并发] try_acquire 失败（降级为直接执行）: {e}")
        return True  # Redis 不可用时降级放行


def release(task_id: int, slots: int) -> None:
    """
    归还 slots 个线程槽，并尝试唤醒队首任务。
    """
    member = _make_member(task_id, slots)
    try:
        r = _get_redis()
        new_val = r.eval(_RELEASE_LUA, 1, _SLOTS_KEY, str(slots))
        # 清理自己（正常情况已在 acquire 时移除，这里保底）
        r.zrem(_QUEUE_KEY, member)
        logger.info(f"[并发] task={task_id} 归还 {slots} 槽，当前已用: {new_val}")
        _notify_queue_head()
    except Exception as e:
        logger.warning(f"[并发] release 失败: {e}")


def _notify_queue_head():
    """触发一个轻量 Celery 任务让队首任务立刻重试，而不是等 retry countdown。"""
    try:
        from core.executors.celery_tasks import wake_queue_head
        wake_queue_head.apply_async(countdown=1)
    except Exception as e:
        logger.debug(f"[并发] 唤醒队首失败（不影响功能，会靠 retry 自动重试）: {e}")


def get_queue_info(task_id: int, slots: int) -> dict:
    """
    返回该任务在队列中的位置和全局槽使用情况。

    Returns:
        {
            "position": 3,          # 在队列中的位置（1-based），0 表示不在队列
            "queue_length": 5,      # 队列总长度
            "slots_used": 40,       # 当前已占用槽数
            "slots_total": max_slots,  # 来自 settings.AI_SCREEN_MAX_GLOBAL_THREADS
            "slots_free": 24,       # 当前剩余槽数
        }
    """
    max_slots = getattr(settings, 'AI_SCREEN_MAX_GLOBAL_THREADS', 64)
    member = _make_member(task_id, slots)
    try:
        r = _get_redis()
        used = int(r.get(_SLOTS_KEY) or 0)
        rank = r.zrank(_QUEUE_KEY, member)   # 0-based，None 表示不在队列
        queue_len = r.zcard(_QUEUE_KEY)
        return {
            "position": (rank + 1) if rank is not None else 0,
            "queue_length": queue_len,
            "slots_used": used,
            "slots_total": max_slots,
            "slots_free": max(0, max_slots - used),
        }
    except Exception as e:
        logger.warning(f"[并发] get_queue_info 失败: {e}")
        return {"position": 0, "queue_length": 0, "slots_used": 0,
                "slots_total": max_slots, "slots_free": max_slots}


def cancel_queue(task_id: int, slots: int) -> None:
    """从排队 ZSET 中移除该任务（用户取消/任务被删除时调用）。"""
    member = _make_member(task_id, slots)
    try:
        r = _get_redis()
        r.zrem(_QUEUE_KEY, member)
        logger.info(f"[并发] task={task_id} 已从队列移除")
    except Exception as e:
        logger.warning(f"[并发] cancel_queue 失败: {e}")


def reset_slots(force: bool = False) -> None:
    """
    紧急重置槽计数（运维用，防止崩溃导致槽泄漏）。
    force=True 时直接清零，否则只重置为 0。
    """
    try:
        r = _get_redis()
        r.set(_SLOTS_KEY, 0)
        if force:
            r.delete(_QUEUE_KEY)
        logger.warning("[并发] 槽计数已重置")
    except Exception as e:
        logger.error(f"[并发] reset_slots 失败: {e}")
