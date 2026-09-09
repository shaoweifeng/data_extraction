import json
import logging
import time
from collections import defaultdict
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.db import OperationalError, ProgrammingError
from django.db.models import Count
from django.utils import timezone

from core.models import SystemOperationState, Task
from core.workflow.domain.statuses import TaskStatus


logger = logging.getLogger(__name__)

NORMAL_STATE = {
    'mode': 'normal',
    'message': '',
    'scheduled_at': None,
    'updated_at': None,
}
ACTIVE_TASK_STATUSES = (
    TaskStatus.QUEUING,
    TaskStatus.PENDING,
    TaskStatus.RUNNING,
    TaskStatus.STOPPING,
)

_state_cache = {'expires': 0.0, 'value': NORMAL_STATE}
_PRESENCE_KEY = 'platform:presence'
_PRESENCE_META_KEY = 'platform:presence:meta'
_PRESENCE_RETENTION_SECONDS = 600
_ONLINE_SECONDS = 90
_RECENT_SECONDS = 300
_OPERATIONS_TASK_LIST_LIMIT = 100


def is_platform_admin(user) -> bool:
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    profile = getattr(user, 'profile', None)
    return bool(user.is_superuser or (profile and profile.role == 'admin'))


def _serialize_state(obj):
    return {
        'mode': obj.mode,
        'message': obj.message,
        'scheduled_at': obj.scheduled_at.isoformat() if obj.scheduled_at else None,
        'updated_at': obj.updated_at.isoformat() if obj.updated_at else None,
    }


def get_system_state(*, fresh=False):
    now = time.monotonic()
    if not fresh and now < _state_cache['expires']:
        return dict(_state_cache['value'])
    try:
        state, _ = SystemOperationState.objects.get_or_create(singleton_id=1)
        value = _serialize_state(state)
    except (OperationalError, ProgrammingError):
        # The old application must remain startable before migration 0021 runs.
        value = dict(NORMAL_STATE)
    _state_cache.update(value=value, expires=now + 2.0)
    return dict(value)


def set_system_state(mode, *, message='', scheduled_at=None, user=None):
    valid_modes = {choice[0] for choice in SystemOperationState.MODE_CHOICES}
    if mode not in valid_modes:
        raise ValueError('无效的系统运行状态')
    state, _ = SystemOperationState.objects.get_or_create(singleton_id=1)
    state.mode = mode
    state.message = (message or '').strip()[:500]
    state.scheduled_at = scheduled_at
    state.updated_by = user
    state.save()
    value = _serialize_state(state)
    _state_cache.update(value=value, expires=time.monotonic() + 2.0)
    return value


def assert_accepting_new_work():
    state = get_system_state()
    if state['mode'] != 'normal':
        raise RuntimeError('平台正在排空或维护，暂时不能启动新任务')


def _get_redis():
    import redis
    return redis.from_url(settings.CELERY_BROKER_URL, decode_responses=True)


def record_presence(user, *, tab_id, page='', project_id=None):
    tab_id = str(tab_id or 'default')[:64]
    member = f'{user.id}:{tab_id}'
    now = time.time()
    payload = json.dumps({
        'user_id': user.id,
        'tab_id': tab_id,
        'page': str(page or '')[:300],
        'project_id': project_id,
        'last_seen': timezone.now().isoformat(),
    }, ensure_ascii=False)
    client = _get_redis()
    cutoff = now - _PRESENCE_RETENTION_SECONDS
    stale = client.zrangebyscore(_PRESENCE_KEY, '-inf', cutoff)
    pipe = client.pipeline()
    pipe.zadd(_PRESENCE_KEY, {member: now})
    pipe.hset(_PRESENCE_META_KEY, member, payload)
    pipe.zremrangebyscore(_PRESENCE_KEY, '-inf', cutoff)
    if stale:
        pipe.hdel(_PRESENCE_META_KEY, *stale)
    pipe.expire(_PRESENCE_KEY, _PRESENCE_RETENTION_SECONDS * 2)
    pipe.expire(_PRESENCE_META_KEY, _PRESENCE_RETENTION_SECONDS * 2)
    pipe.execute()


def get_presence_snapshot():
    now = time.time()
    try:
        client = _get_redis()
        members = client.zrangebyscore(_PRESENCE_KEY, now - _PRESENCE_RETENTION_SECONDS, '+inf')
        raw_metadata = client.hmget(_PRESENCE_META_KEY, members) if members else []
        scored = client.zrangebyscore(
            _PRESENCE_KEY, now - _PRESENCE_RETENTION_SECONDS, '+inf', withscores=True,
        )
        scores = dict(scored)
        redis_available = True
    except Exception as exc:
        logger.warning('读取在线用户状态失败: %s', exc)
        members, raw_metadata, scores, redis_available = [], [], {}, False

    tabs = []
    for member, raw in zip(members, raw_metadata):
        if not raw:
            continue
        try:
            item = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        item['_score'] = scores.get(member, 0)
        tabs.append(item)

    online_tabs = [item for item in tabs if item['_score'] >= now - _ONLINE_SECONDS]
    recent_tabs = [item for item in tabs if item['_score'] >= now - _RECENT_SECONDS]
    online_user_ids = {item['user_id'] for item in online_tabs}
    recent_user_ids = {item['user_id'] for item in recent_tabs}
    user_records = list(
        get_user_model().objects.filter(id__in=recent_user_ids).select_related('profile')
    )
    users_by_id = {user.id: user for user in user_records}
    grouped = defaultdict(list)
    for item in online_tabs:
        grouped[item['user_id']].append(item)
    users = []
    for user_id, user_tabs in grouped.items():
        latest = max(user_tabs, key=lambda item: item['_score'])
        users.append({
            'user_id': user_id,
            'username': users_by_id[user_id].username if user_id in users_by_id else f'user-{user_id}',
            'is_admin': is_platform_admin(users_by_id.get(user_id)),
            'last_seen': latest.get('last_seen'),
            'page': latest.get('page', ''),
            'project_id': latest.get('project_id'),
            'tabs': len(user_tabs),
        })
    users.sort(key=lambda item: item.get('last_seen') or '', reverse=True)
    return {
        'redis_available': redis_available,
        'online_users': len(online_user_ids),
        'active_tabs': len(online_tabs),
        'recent_users': len(recent_user_ids),
        'users': users,
    }


def _celery_snapshot():
    result = {'available': False, 'workers': 0, 'active': 0, 'reserved': 0, 'scheduled': 0}
    try:
        from platform_backend.celery import app
        # BROKER_POOL_LIMIT=1 时不让 Inspector 再从全局池中无限等待连接。
        with app.connection_for_write() as connection:
            inspector = app.control.inspect(timeout=0.5, connection=connection)
            active = inspector.active() or {}
            reserved = inspector.reserved() or {}
            scheduled = inspector.scheduled() or {}
        worker_names = set(active) | set(reserved) | set(scheduled)
        result.update(
            available=bool(worker_names),
            workers=len(worker_names),
            active=sum(len(items) for items in active.values()),
            reserved=sum(len(items) for items in reserved.values()),
            scheduled=sum(len(items) for items in scheduled.values()),
        )
    except Exception as exc:
        result['error'] = str(exc)
    return result


def get_operations_snapshot(*, inspect_celery=True):
    presence = get_presence_snapshot()
    # 只返回前 N 个活动任务的小字段，避免队列异常积压时撑高运维页内存。
    active_tasks = list(
        Task.objects.filter(status__in=ACTIVE_TASK_STATUSES)
        .values(
            'id', 'task_type', 'status', 'progress', 'project_id', 'project__name',
            'created_by_id', 'created_by__username', 'started_at',
        )
        .order_by('created_at')[:_OPERATIONS_TASK_LIST_LIMIT]
    )
    task_counts = {
        row['status']: row['count']
        for row in Task.objects.filter(status__in=ACTIVE_TASK_STATUSES)
        .values('status').annotate(count=Count('id'))
    }
    tasks = [{
        'id': task['id'],
        'type': task['task_type'],
        'status': task['status'],
        'progress': round(task['progress'] * 100, 1),
        'project_id': task['project_id'],
        'project': task['project__name'],
        'user_id': task['created_by_id'],
        'username': task['created_by__username'] or '',
        'started_at': task['started_at'].isoformat() if task['started_at'] else None,
    } for task in active_tasks]
    celery = _celery_snapshot() if inspect_celery else {'available': None}
    active_db_count = sum(task_counts.values())
    online_non_admin_users = sum(not item.get('is_admin') for item in presence['users'])
    state = get_system_state(fresh=True)
    # Celery/Gunicorn/Vite 正是 stop.sh 负责关闭的对象，不能要求它们在停机前已经退出。
    # 平台可开始停机的条件只是：没有普通在线用户，且没有活动业务任务。
    safe_to_stop = online_non_admin_users == 0 and active_db_count == 0
    return {
        'state': state,
        'presence': presence,
        'online_non_admin_users': online_non_admin_users,
        'sessions': {
            'unexpired': Session.objects.filter(expire_date__gt=timezone.now()).count(),
            'note': '未过期会话不等于当前在线用户',
        },
        'task_counts': task_counts,
        'active_task_count': active_db_count,
        'tasks': tasks,
        'tasks_truncated': active_db_count > len(tasks),
        'task_list_limit': _OPERATIONS_TASK_LIST_LIMIT,
        'celery': celery,
        'safe_to_stop': safe_to_stop,
        'server_time': timezone.now().isoformat(),
    }


def pause_long_running_tasks():
    """Cooperatively pause resumable long-running tasks for maintenance."""
    from core.scheduler import TaskScheduler

    candidates = list(Task.objects.filter(
        status__in=(TaskStatus.QUEUING, TaskStatus.PENDING, TaskStatus.RUNNING),
        task_type__in=('ai_screen', 'qa_eval'),
    ).order_by('created_at'))
    paused, failed = [], []
    for task in candidates:
        config = dict(task.config or {})
        config['paused_by_maintenance'] = True
        config['maintenance_paused_at'] = timezone.now().isoformat()
        Task.objects.filter(pk=task.pk).update(config=config)
        try:
            if TaskScheduler(task.project_id).stop_task(task.id):
                paused.append(task.id)
            else:
                failed.append({'task_id': task.id, 'error': '任务状态已变化'})
        except Exception as exc:
            failed.append({'task_id': task.id, 'error': str(exc)})
    return {'paused': paused, 'failed': failed}


def resume_maintenance_tasks():
    """Resume tasks that were cooperatively paused by maintenance."""
    from core.scheduler import TaskScheduler

    candidates = list(Task.objects.filter(
        status=TaskStatus.STOPPED,
        task_type__in=('ai_screen', 'qa_eval'),
        config__paused_by_maintenance=True,
    ).order_by('created_at'))
    resumed, failed = [], []
    for task in candidates:
        try:
            new_task = TaskScheduler(task.project_id).resume_task(
                task.id, maintenance_resume=True,
            )
            resumed.append({'old_task_id': task.id, 'new_task_id': new_task.id})
        except Exception as exc:
            failed.append({'task_id': task.id, 'error': str(exc)})
    return {'resumed': resumed, 'failed': failed}


def reconcile_interrupted_tasks(*, apply=False):
    """Find task rows left active after all workers have stopped, optionally repair them."""
    interrupted = list(Task.objects.filter(
        status__in=(TaskStatus.RUNNING, TaskStatus.STOPPING),
    ).select_related('project').order_by('created_at'))
    report = {'found': [], 'repaired': [], 'dry_run': not apply}
    for task in interrupted:
        resumable = task.task_type in ('ai_screen', 'qa_eval')
        item = {
            'task_id': task.id,
            'project_id': task.project_id,
            'type': task.task_type,
            'status': task.status,
            'action': 'pause_for_resume' if resumable else 'mark_failed',
        }
        report['found'].append(item)
        if not apply:
            continue

        config = dict(task.config or {})
        if resumable:
            config['paused_by_maintenance'] = True
            config['maintenance_paused_at'] = timezone.now().isoformat()
            config['recovered_after_interruption'] = True
            Task.objects.filter(pk=task.pk).update(
                status=TaskStatus.STOPPED,
                config=config,
                completed_at=timezone.now(),
                error_message='服务重启时发现中断任务，已转为可恢复状态',
            )
            if task.task_type == 'qa_eval':
                from core.models import QAReference
                ref_ids = config.get('ref_ids') or []
                refs = QAReference.objects.filter(project_id=task.project_id, ai_eval_status='running')
                if ref_ids:
                    refs = refs.filter(pk__in=ref_ids)
                refs.update(ai_eval_status='pending')
        else:
            Task.objects.filter(pk=task.pk).update(
                status=TaskStatus.FAILED,
                completed_at=timezone.now(),
                error_message='服务重启时发现任务被中断，请重新执行该步骤',
            )
        report['repaired'].append(item)

    if apply:
        try:
            from core.services.concurrency_service import reset_slots
            reset_slots(force=False)
        except Exception as exc:
            report['slot_reset_error'] = str(exc)
    return report
