# 优雅停机方案（重启前确认无活跃用户）

> 记录时间：2026-09-05  
> 背景：每次升级/重启服务（gunicorn + celery）会导致正在使用平台的用户请求中断，
> 耗时任务（AI评价、文件解析、筛选）也会被直接杀死。需要一种方式在重启前确认无人使用。

---

## 核心诉求

| 场景 | 期望 |
|------|------|
| 有用户正在运行 AI 评价/解析/筛选 | 重启前能感知，等待任务完成或提示风险 |
| 有用户正在浏览/操作界面 | 可感知（非强制要求） |
| 重启流程 | 尽量自动化，不需要人肉登数据库 |

---

## 方案一：Celery 任务活跃检测（推荐短期实现）

Celery 提供 `inspect().active()` 接口，可直接查询所有 worker 当前正在执行的任务，
**零代码改动，现成可用**。

### 在 `start.sh` 重启前自动检查

```bash
# 检查是否有活跃 Celery 任务
check_active_tasks() {
    source venv/bin/activate
    export DJANGO_SETTINGS_MODULE=platform_backend.settings
    active=$(python -c "
from platform_backend.celery import app
inspect = app.control.inspect()
active = inspect.active()
count = sum(len(v) for v in (active or {}).values())
print(count)
" 2>/dev/null)
    echo "${active:-0}"
}

# 重启前判断
ACTIVE=$(check_active_tasks)
if [ "$ACTIVE" -gt 0 ]; then
    echo "⚠️  当前有 $ACTIVE 个任务正在运行，建议等待完成后再重启"
    echo "   强制继续请按 Enter，取消请 Ctrl+C"
    read
fi
```

**优点**：
- 无需前端改动，无需数据库变更
- 直接反映"有没有人在跑耗时任务"，这才是重启真正有风险的场景

**缺点**：
- 只能感知异步任务，无法知道有多少人在浏览界面

---

## 方案二：心跳接口 + Redis 在线用户统计（推荐中期实现）

### 原理

前端每 30 秒发一次心跳，后端把 `user_id → last_seen` 写入 Redis（TTL=60s），
超时自动过期，无需手动清理。

### 后端实现（约 20 行）

```python
# core/api/heartbeat.py
@login_required
@require_http_methods(['POST'])
def heartbeat(request):
    import redis, json
    from django.conf import settings
    r = redis.Redis.from_url(settings.REDIS_URL)
    key = f"online:user:{request.user.id}"
    data = {
        'user_id': request.user.id,
        'username': request.user.username,
        'last_seen': timezone.now().isoformat(),
    }
    r.setex(key, 60, json.dumps(data))  # TTL = 60s
    return JsonResponse({'ok': True})

def get_online_users():
    """返回当前在线用户列表（供管理接口调用）"""
    import redis, json
    from django.conf import settings
    r = redis.Redis.from_url(settings.REDIS_URL)
    keys = r.keys("online:user:*")
    users = []
    for k in keys:
        v = r.get(k)
        if v:
            users.append(json.loads(v))
    return users
```

### 前端实现（约 5 行）

```javascript
// 在 App.vue 或 router 里加定时器
setInterval(() => {
    if (isLoggedIn) http.post('/heartbeat/')
}, 30000)
```

---

## 方案三：管理后台状态页（整合展示）

在 `/admin/platform-status/` 或平台设置页中展示：

| 维度 | 数据来源 | 刷新方式 |
|------|----------|----------|
| 当前在线用户数 | Redis 心跳 | 实时 |
| 正在运行的 Celery 任务 | inspect().active() | 实时 |
| 最近5分钟 API 请求量 | Gunicorn access.log | 定时 |
| 活跃 Session 数 | django_session 表 | 定时 |

重启前在此页面确认"在线用户=0，活跃任务=0"后再操作。

---

## 实施优先级

| 优先级 | 方案 | 改动量 | 覆盖场景 |
|--------|------|--------|----------|
| ⭐ P0 | `start.sh` 加 Celery 任务检查 | ~20行 shell | 防止任务被强杀 |
| 🔧 P1 | 心跳接口 + Redis 在线统计 | ~30行后端+5行前端 | 感知活跃用户 |
| 💡 P2 | 管理后台状态页 | 中等 | 可视化运维 |

---

## 补充：Gunicorn 优雅停机

Gunicorn 本身支持 `--graceful-timeout`，收到 `SIGTERM` 后会等待正在处理的 HTTP 请求完成：

```bash
# start.sh 重启时用 graceful reload 代替直接 kill
kill -HUP $GUNICORN_PID   # 优雅重载（不中断已有连接）
# 或
kill -TERM $GUNICORN_PID  # 发送 SIGTERM，等待 graceful-timeout 后退出
```

Celery 同理，`SIGTERM` 会等当前任务执行完毕（`--max-tasks-per-child` 配合使用更佳）。

**因此正确的重启顺序**：
1. 检查 active tasks（方案一）
2. `kill -TERM <celery_pid>`（等任务自然完成）
3. `kill -HUP <gunicorn_pid>`（优雅重载，不断请求）
4. 等待旧 worker 退出后启动新进程
