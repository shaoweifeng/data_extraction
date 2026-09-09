#!/bin/bash
# Graceful platform shutdown. Use --force only after accepting possible task/data loss.
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_DIR="$SCRIPT_DIR/pids"
PYTHON_BIN="$SCRIPT_DIR/venv/bin/python"
CELERY_BIN="$SCRIPT_DIR/venv/bin/celery"
GUNICORN_BIN="$SCRIPT_DIR/venv/bin/gunicorn"
FORCE=false
DRAIN_TIMEOUT=300
TASK_TIMEOUT=900
WEB_TIMEOUT=300

for arg in "$@"; do
    case "$arg" in
        --force) FORCE=true ;;
        --drain-timeout=*) DRAIN_TIMEOUT="${arg#*=}" ;;
        --task-timeout=*) TASK_TIMEOUT="${arg#*=}" ;;
        --web-timeout=*) WEB_TIMEOUT="${arg#*=}" ;;
        -h|--help)
            echo "用法: ./stop.sh [--force] [--drain-timeout=300] [--task-timeout=900] [--web-timeout=300]"
            exit 0
            ;;
    esac
done

if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    . "$SCRIPT_DIR/.env"
    set +a
fi

export MPLCONFIGDIR=${MPLCONFIGDIR:-$SCRIPT_DIR/.cache/matplotlib}

run_manage() {
    PYTHONWARNINGS=ignore "$PYTHON_BIN" manage.py "$@"
}

is_running() {
    kill -0 "$1" 2>/dev/null
}

wait_for_exit() {
    local pid=$1
    local timeout=$2
    local elapsed=0
    while is_running "$pid"; do
        if [ "$elapsed" -ge "$timeout" ]; then
            return 1
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    return 0
}

read_pid() {
    local name=$1
    local pid_file="$PID_DIR/${name}.pid"
    if [ -f "$pid_file" ]; then
        tr -d '[:space:]' < "$pid_file"
    fi
}

matches_service_process() {
    local name=$1
    local pid=$2
    local command
    command=$(ps -p "$pid" -o command= 2>/dev/null) || return 1
    case "$name" in
        celery) [[ "$command" == *celery*platform_backend* ]] ;;
        django) [[ "$command" == *gunicorn*platform_backend.wsgi* || "$command" == *"manage.py runserver"* ]] ;;
        vite) [[ "$command" == *vite* || "$command" == *"npm run dev"* ]] ;;
        *) return 1 ;;
    esac
}

discover_service_pid() {
    local name=$1
    case "$name" in
        celery) pgrep -o -f "$CELERY_BIN -A platform_backend" 2>/dev/null || true ;;
        django) pgrep -o -f "$GUNICORN_BIN platform_backend.wsgi" 2>/dev/null || true ;;
        vite) pgrep -o -f "$SCRIPT_DIR/web/node_modules/.bin/vite" 2>/dev/null || true ;;
    esac
}

has_managed_process() {
    local name pid
    local found=false
    for name in celery django vite; do
        pid=$(read_pid "$name")
        if [ -n "$pid" ]; then
            case "$pid" in
                *[!0-9]*) ;;
                *)
                    if is_running "$pid" && matches_service_process "$name" "$pid"; then
                        found=true
                        continue
                    fi
                    ;;
            esac
            echo "⚠️  忽略 ${name} 的失效 PID 文件（PID: ${pid}）"
            rm -f "$PID_DIR/${name}.pid"
        fi
        pid=$(discover_service_pid "$name")
        if [ -n "$pid" ] && is_running "$pid" && matches_service_process "$name" "$pid"; then
            echo "$pid" > "$PID_DIR/${name}.pid"
            echo "ℹ️  已接管当前项目未登记的 ${name} 进程（PID: ${pid}）"
            found=true
        fi
    done
    [ "$found" = true ]
}

stop_with_timeout() {
    local name=$1
    local timeout=$2
    local pid
    pid=$(read_pid "$name")
    case "$pid" in
        ''|*[!0-9]*) pid='' ;;
        *) ;;
    esac
    if [ -z "$pid" ] || ! is_running "$pid" || ! matches_service_process "$name" "$pid"; then
        echo "ℹ️  $name 未运行"
        rm -f "$PID_DIR/${name}.pid"
        return 0
    fi

    echo "⏳ 正在优雅停止 ${name} (PID: ${pid}，最长等待 ${timeout}s)..."
    kill -TERM "$pid" 2>/dev/null || true
    if wait_for_exit "$pid" "$timeout"; then
        rm -f "$PID_DIR/${name}.pid"
        echo "✅ $name 已停止"
        return 0
    fi

    if [ "$FORCE" = true ]; then
        echo "⚠️  $name 超时，按 --force 要求强制终止"
        kill -9 "$pid" 2>/dev/null || true
        rm -f "$PID_DIR/${name}.pid"
        return 0
    fi

    echo "❌ $name 在 ${timeout}s 内未退出。平台仍保持维护模式，未执行强杀。"
    echo "   排查完成后重试，或明确接受风险后使用 ./stop.sh --force"
    return 1
}

service_pid_is_running() {
    local name=$1
    local pid
    pid=$(read_pid "$name")
    case "$pid" in
        ''|*[!0-9]*) return 1 ;;
    esac
    is_running "$pid" && matches_service_process "$name" "$pid"
}

operations_snapshot() {
    run_manage operations_status --json --no-celery 2>/dev/null
}

platform_idle() {
    local snapshot
    snapshot=$(operations_snapshot) || return 1
    echo "$snapshot" | grep -q '"online_non_admin_users": 0' \
        && echo "$snapshot" | grep -q '"active_task_count": 0'
}

tasks_idle() {
    local snapshot
    snapshot=$(operations_snapshot) || return 1
    echo "$snapshot" | grep -q '"active_task_count": 0'
}

echo "🛑 开始平台优雅停机"
cd "$SCRIPT_DIR" || exit 1

if ! has_managed_process; then
    echo "✅ 未发现由 start.sh 启动的服务，平台已处于停止状态。"
    exit 0
fi

# 纯前端开发服务不承载用户任务，无需访问数据库或进入维护流程。
if ! service_pid_is_running "celery" && ! service_pid_is_running "django"; then
    stop_with_timeout "vite" 30 || exit 1
    echo "✅ 前端开发服务已停止。"
    exit 0
fi

if [ ! -x "$PYTHON_BIN" ]; then
    echo "❌ 找不到项目虚拟环境 Python: $PYTHON_BIN"
    exit 1
fi

if [ "$FORCE" = false ]; then
    run_manage maintenance draining \
        --message "平台即将升级，已停止接收新任务，请保存当前操作。" || exit 1

    echo "⏳ 等待用户离开和现有任务自然完成（最长 ${DRAIN_TIMEOUT}s）..."
    elapsed=0
    while ! platform_idle; do
        if [ "$elapsed" -ge "$DRAIN_TIMEOUT" ]; then
            break
        fi
        if [ $((elapsed % 30)) -eq 0 ]; then
            run_manage operations_status --no-celery || true
        fi
        sleep 5
        elapsed=$((elapsed + 5))
    done

    run_manage maintenance maintenance \
        --message "平台正在升级，完成后将自动恢复访问。" || exit 1
    run_manage maintenance_tasks pause || exit 1

    echo "⏳ 等待任务写入断点并退出（最长 ${TASK_TIMEOUT}s）..."
    elapsed=0
    while ! tasks_idle; do
        if [ "$elapsed" -ge "$TASK_TIMEOUT" ]; then
            echo "❌ 仍有活动任务或 Celery 工作未结束，取消停机且保留维护模式。"
            echo "   请运行: $PYTHON_BIN manage.py operations_status"
            exit 1
        fi
        sleep 5
        elapsed=$((elapsed + 5))
    done
else
    echo "⚠️  强制模式：跳过排空和任务安全检查"
    run_manage maintenance maintenance \
        --message "平台正在进行紧急维护。" || true
fi

# Celery TERM is a warm shutdown: stop consuming and wait for active tasks.
stop_with_timeout "celery" "$TASK_TIMEOUT" || exit 1
# Gunicorn TERM waits for in-flight HTTP requests to finish.
stop_with_timeout "django" "$WEB_TIMEOUT" || exit 1
stop_with_timeout "vite" 30 || exit 1

echo "✅ 平台已安全停止。MySQL 与 Redis 保持运行。"
