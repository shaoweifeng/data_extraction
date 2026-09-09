#!/bin/bash
# ============================================================
# 启动脚本：支持后台守护模式 + 集中日志 + PID 管理
#
# 用法：
#   ./start.sh              # 前台模式（构建前端后用 Gunicorn 启动）
#   ./start.sh -d           # 后台守护模式（Gunicorn daemon，日志写文件）
#   ./start.sh --dev        # 开发模式（runserver 前台 + Vite dev server）
#   ./start.sh --dev -d     # 开发模式守护（runserver + Vite 均后台）
#   ./start.sh --no-build   # 跳过前端构建（前台，Gunicorn）
#   ./stop.sh               # 停止所有后台进程（守护模式配套）
# ============================================================
echo "🚀 正在启动自动化数据提取平台 (Django + Celery + Vue)..."

# ── 参数解析 ──────────────────────────────────────────────
DAEMON_MODE=false
DEV_MODE=false
SKIP_BUILD=false

for arg in "$@"; do
    case $arg in
        -d)         DAEMON_MODE=true ;;
        --dev)      DEV_MODE=true; SKIP_BUILD=true ;;
        --no-build) SKIP_BUILD=true ;;
    esac
done

if [ "$DAEMON_MODE" = true ]; then
    echo "📌 守护模式：所有进程后台运行，日志写入 logs/"
fi
if [ "$DEV_MODE" = true ]; then
    echo "🔧 开发模式：跳过构建，启动 Vite dev server (localhost:5173)"
fi

restore_platform_after_health() {
    local health_ok=false
    for i in 1 2 3 4 5 6 7 8 9 10; do
        if curl -fsS "http://127.0.0.1:8000/api/health/ready/?allow_maintenance=1" >/dev/null 2>&1; then
            health_ok=true
            break
        fi
        sleep 1
    done
    if [ "$health_ok" = true ]; then
        echo "✅ Web 健康检查通过"
        if run_manage maintenance_tasks resume; then
            run_manage maintenance normal
            echo "✅ 平台已恢复开放"
            return 0
        fi
        echo "❌ 维护任务恢复失败，平台保持维护状态"
        return 1
    fi
    echo "❌ Web 健康检查失败，平台保持维护状态，请查看错误日志"
    return 1
}

# ── 目录准备 ─────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
PID_DIR="$SCRIPT_DIR/pids"
mkdir -p "$LOG_DIR" "$PID_DIR"
PYTHON_BIN=${PYTHON_BIN:-python}
CELERY_BIN=${CELERY_BIN:-celery}
GUNICORN_BIN=${GUNICORN_BIN:-gunicorn}

run_manage() {
    PYTHONWARNINGS=ignore "$PYTHON_BIN" manage.py "$@"
}

is_running() {
    kill -0 "$1" 2>/dev/null
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

service_is_running() {
    local name=$1
    local pid
    pid=$(read_pid "$name")
    case "$pid" in
        ''|*[!0-9]*) ;;
        *)
            if is_running "$pid" && matches_service_process "$name" "$pid"; then
                echo "❌ ${name} 已在运行（PID: ${pid}）"
                return 0
            fi
            ;;
    esac
    if [ -n "$pid" ]; then
        echo "⚠️  清理 ${name} 的失效 PID 文件（PID: ${pid}）"
        rm -f "$PID_DIR/${name}.pid"
    fi
    pid=$(discover_service_pid "$name")
    if [ -n "$pid" ] && is_running "$pid" && matches_service_process "$name" "$pid"; then
        echo "$pid" > "$PID_DIR/${name}.pid"
        echo "❌ 发现当前项目未登记的 ${name} 进程（PID: ${pid}），已恢复 PID 文件"
        return 0
    fi
    return 1
}

rollback_started_services() {
    local name pid
    echo "⚠️  启动未完成，正在回滚本次已启动的进程..."
    for name in django vite celery; do
        pid=$(read_pid "$name")
        case "$pid" in
            ''|*[!0-9]*) ;;
            *)
                if is_running "$pid" && matches_service_process "$name" "$pid"; then
                    kill -TERM "$pid" 2>/dev/null || true
                fi
                ;;
        esac
        rm -f "$PID_DIR/${name}.pid"
    done
}

# 加载本地配置，使 Shell、Django、Gunicorn 和 Celery 使用同一组环境变量。
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    . "$SCRIPT_DIR/.env"
    set +a
fi

# Matplotlib 字体缓存使用项目内可写目录，避免服务器用户 HOME 不可写。
export MPLCONFIGDIR=${MPLCONFIGDIR:-$SCRIPT_DIR/.cache/matplotlib}
mkdir -p "$MPLCONFIGDIR"

# ── 日志文件路径 ──────────────────────────────────────────
DJANGO_LOG="$LOG_DIR/gunicorn_access.log"
DJANGO_ERR="$LOG_DIR/gunicorn_error.log"
CELERY_LOG="$LOG_DIR/celery.log"
VITE_LOG="$LOG_DIR/vite.log"

# 0) 数据库配置（MySQL）
export DB_NAME=${DB_NAME:-data_extraction}
export DB_USER=${DB_USER:-root}
export DB_PASSWORD=${DB_PASSWORD:-}
export DB_HOST=${DB_HOST:-127.0.0.1}
export DB_PORT=${DB_PORT:-3306}

# AI 筛选配置
export AI_TIMEOUT=${AI_TIMEOUT:-120}

# ── 阶段四：全局并发控制 ──────────────────────────────────────
# 全局最大线程槽数（所有 ai_screen 任务占用线程数之和上限）
export AI_SCREEN_MAX_GLOBAL_THREADS=${AI_SCREEN_MAX_GLOBAL_THREADS:-64}
# 普通用户默认并发线程数（未设置 concurrency_limit 时的 fallback）
export AI_SCREEN_DEFAULT_CONCURRENCY=${AI_SCREEN_DEFAULT_CONCURRENCY:-2}
# 管理员/超管并发线程数
export AI_SCREEN_ADMIN_CONCURRENCY=${AI_SCREEN_ADMIN_CONCURRENCY:-16}
# 排队重试间隔（秒）
export AI_SCREEN_QUEUE_RETRY_INTERVAL=${AI_SCREEN_QUEUE_RETRY_INTERVAL:-30}
# 最大排队等待次数（120 × 30s = 1 小时）
export AI_SCREEN_QUEUE_MAX_RETRIES=${AI_SCREEN_QUEUE_MAX_RETRIES:-120}

# ── 阶段五：注册防刷 ─────────────────────────────────────────
# 同一 IP 在窗口期内最多允许成功注册的账号数（超出返回 429）
export REGISTER_IP_LIMIT=${REGISTER_IP_LIMIT:-3}
# 限流窗口（小时）
export REGISTER_IP_WINDOW_HOURS=${REGISTER_IP_WINDOW_HOURS:-24}
# 邮箱验证开关（false=关闭，注册时邮箱选填；true=开启，需配置 SMTP）
export REQUIRE_EMAIL_VERIFICATION=${REQUIRE_EMAIL_VERIFICATION:-false}

# DeepSeek 配置
export DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY:-}
export DEEPSEEK_API_URL=${DEEPSEEK_API_URL:-https://api.deepseek.com/v1}
export DEEPSEEK_MODEL=${DEEPSEEK_MODEL:-deepseek-v4-flash}

# 豆包（字节跳动 Doubao / Ark）配置
export DOUBAO_API_KEY=${DOUBAO_API_KEY:-}
export DOUBAO_API_URL=${DOUBAO_API_URL:-https://ark.cn-beijing.volces.com/api/v3}
export DOUBAO_MODEL=${DOUBAO_MODEL:-ep-20260509162819-bvjfj}

# 千问（阿里云 DashScope）配置
export QWEN_API_KEY=${QWEN_API_KEY:-}
export QWEN_API_URL=${QWEN_API_URL:-https://dashscope.aliyuncs.com/compatible-mode/v1}
export QWEN_MODEL=${QWEN_MODEL:-qwen3.7-plus}

# 兼容旧环境变量（保留，优先级低于上方）
export AI_API_KEY=${AI_API_KEY:-$DEEPSEEK_API_KEY}
export AI_API_URL=${AI_API_URL:-$DEEPSEEK_API_URL}
export AI_MODEL=${AI_MODEL:-$DEEPSEEK_MODEL}

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1 || ! command -v "$CELERY_BIN" >/dev/null 2>&1; then
    echo "❌ 当前环境缺少 python 或 celery，请先激活项目虚拟环境"
    exit 1
fi
if [ "$DEV_MODE" = false ] && ! command -v "$GUNICORN_BIN" >/dev/null 2>&1; then
    echo "❌ 当前环境缺少 gunicorn，请先激活项目虚拟环境"
    exit 1
fi

# start.sh 和 stop.sh 统一以 PID 文件并核对真实命令，避免两边判断矛盾。
ALREADY_RUNNING=false
for service_name in celery django vite; do
    if service_is_running "$service_name"; then
        ALREADY_RUNNING=true
    fi
done
if [ "$ALREADY_RUNNING" = true ]; then
    echo "   启动已取消；如需重启，请先执行 ./stop.sh"
    exit 1
fi

# ── 前端构建（非开发模式） ─────────────────────────────────
if [ "$SKIP_BUILD" = false ]; then
    WEB_DIR="$SCRIPT_DIR/web"
    if [ ! -d "$WEB_DIR" ]; then
        echo "❌ 错误: 未找到 web/ 目录，请确认 Vue 工程已初始化"
        exit 1
    fi

    # 检查 node 和 npm
    if ! command -v node > /dev/null; then
        echo "❌ 错误: 未找到 node，请先安装 Node.js (>= 18)"
        exit 1
    fi

    echo "📦 正在构建前端 (npm run build)..."
    cd "$WEB_DIR"

    # 安装依赖（node_modules 不存在时）
    if [ ! -d "node_modules" ]; then
        echo "   首次安装依赖，请稍候..."
        npm install --silent
    fi

    # 执行构建
    if npm run build --silent; then
        echo "✅ 前端构建完成 → web/dist/"
    else
        echo "❌ 前端构建失败，请检查 web/ 目录下的错误信息"
        exit 1
    fi

    cd "$SCRIPT_DIR"
fi

# 1. 启动 Redis（后台）
if command -v redis-server > /dev/null; then
    redis-server --daemonize yes 2>/dev/null || true
    echo "✅ Redis 已启动"
else
    echo "❌ 错误: 未找到 redis-server，请先安装 Redis"
    exit 1
fi

# 2. 启动 Celery Worker（后台）
if ! run_manage migrate --check; then
    echo "❌ 检测到未执行的数据库迁移，请先运行："
    echo "   python manage.py migrate"
    exit 1
fi

# 此时已确认没有旧 Worker，可安全修复上次异常退出遗留的 running/stopping 状态。
if ! run_manage reconcile_interrupted_tasks --apply; then
    echo "❌ 中断任务核对失败，本次启动已取消"
    exit 1
fi

nohup "$CELERY_BIN" -A platform_backend worker --loglevel=info -P threads -c 16 \
    >> "$CELERY_LOG" 2>&1 &
CELERY_PID=$!
echo $CELERY_PID > "$PID_DIR/celery.pid"
sleep 1
if ! is_running "$CELERY_PID" || ! matches_service_process "celery" "$CELERY_PID"; then
    echo "❌ Celery Worker 启动失败，请查看: $CELERY_LOG"
    rollback_started_services
    exit 1
fi
echo "✅ Celery Worker 已在后台启动 (PID: $CELERY_PID, 并发槽: 16, 模式: threads)"
echo "   日志: $CELERY_LOG"

# 3. 开发模式：启动 Vite dev server
if [ "$DEV_MODE" = true ]; then
    WEB_DIR="$SCRIPT_DIR/web"
    if [ ! -d "$WEB_DIR/node_modules" ]; then
        echo "📦 安装前端依赖..."
        cd "$WEB_DIR" && npm install --silent && cd "$SCRIPT_DIR"
    fi

    if [ "$DAEMON_MODE" = true ]; then
        nohup sh -c "cd '$WEB_DIR' && npm run dev" >> "$VITE_LOG" 2>&1 &
        VITE_PID=$!
        echo $VITE_PID > "$PID_DIR/vite.pid"
        echo "✅ Vite dev server 已在后台启动 (PID: $VITE_PID)"
        echo "   日志: $VITE_LOG"
        echo "   前端访问: http://localhost:5173  (代理 API → localhost:8000)"
    else
        # 前台模式：Vite 先放后台，Django 占前台，Ctrl+C 时一起退出
        cd "$WEB_DIR" && npm run dev &
        VITE_PID=$!
        echo $VITE_PID > "$PID_DIR/vite.pid"
        cd "$SCRIPT_DIR"
        echo "✅ Vite dev server 已启动 (PID: $VITE_PID)"
        echo "   前端访问: http://localhost:5173  (代理 API → localhost:8000)"
        # 注册 Ctrl+C 清理函数
        trap "kill $VITE_PID 2>/dev/null; rm -f '$PID_DIR/vite.pid'; echo ''; echo '🛑 已停止 Vite 和 Django'" INT TERM
    fi
fi

# 4. 启动 Django Server（开发模式用 runserver，生产/守护模式用 Gunicorn）
if [ "$DEV_MODE" = true ]; then
    echo "✅ Django 服务即将启动，请访问 http://127.0.0.1:8000 (API)"
else
    echo "✅ Django 服务即将启动，请访问 http://127.0.0.1:8000"
fi

if [ "$DAEMON_MODE" = true ]; then
    if [ "$DEV_MODE" = true ]; then
        # ── 守护模式 + 开发模式：仍用 runserver ──────────────
        nohup "$PYTHON_BIN" manage.py runserver 0.0.0.0:8000 \
            >> "$DJANGO_LOG" 2>> "$DJANGO_ERR" &
        DJANGO_PID=$!
        echo $DJANGO_PID > "$PID_DIR/django.pid"
        echo "✅ Django (runserver) 已在后台启动 (PID: $DJANGO_PID)"
    else
        # ── 守护模式：Gunicorn 后台运行，自行写 PID 文件 ──────
        if ! "$GUNICORN_BIN" platform_backend.wsgi:application \
            --bind 0.0.0.0:8000 \
            --workers 4 \
            --threads 2 \
            --timeout 300 \
            --daemon \
            --pid "$PID_DIR/django.pid" \
            --access-logfile "$DJANGO_LOG" \
            --error-logfile "$DJANGO_ERR"; then
            echo "❌ Gunicorn 启动失败，请查看: $DJANGO_ERR"
            rollback_started_services
            exit 1
        fi
        sleep 1
        DJANGO_PID=$(read_pid "django")
        if [ -z "$DJANGO_PID" ] || ! is_running "$DJANGO_PID" \
            || ! matches_service_process "django" "$DJANGO_PID"; then
            echo "❌ Gunicorn 未能保持运行，请查看: $DJANGO_ERR"
            rollback_started_services
            exit 1
        fi
        echo "✅ Gunicorn 已在后台启动 (PID: $DJANGO_PID, workers: 4×2线程)"
    fi
    echo "   访问日志 : $DJANGO_LOG"
    echo "   错误日志 : $DJANGO_ERR"
    echo ""
    echo "👉 查看日志  : tail -f $DJANGO_LOG"
    echo "👉 查看报错  : tail -f $DJANGO_ERR"
    echo "👉 停止服务  : ./stop.sh"
    if [ "$DEV_MODE" = true ]; then
        echo "👉 前端日志  : tail -f $VITE_LOG"
    fi
    # 守护模式启动后确认 Web 存活，再恢复维护暂停的任务并开放平台。
    if ! restore_platform_after_health; then
        rollback_started_services
        exit 1
    fi
else
    # 前台模式的 Gunicorn/runserver 会阻塞当前 Shell，因此后台等待健康检查。
    restore_platform_after_health &
    if [ "$DEV_MODE" = true ]; then
        # ── 前台开发模式：runserver 前台阻塞 ─────────────────
        echo "   (前台模式，Ctrl+C 可停止；Celery 仍在后台运行)"
        echo "   如需后台常驻，请使用: ./start.sh --dev -d"
        "$PYTHON_BIN" manage.py runserver 0.0.0.0:8000
    else
        # ── 前台生产模式：Gunicorn 前台阻塞 ──────────────────
        echo "   (前台模式，Ctrl+C 可停止；Celery 仍在后台运行)"
        echo "   如需后台常驻，请使用: ./start.sh -d"
        "$GUNICORN_BIN" platform_backend.wsgi:application \
            --bind 0.0.0.0:8000 \
            --workers 4 \
            --threads 2 \
            --timeout 300 \
            --pid "$PID_DIR/django.pid" \
            --access-logfile "$DJANGO_LOG" \
            --error-logfile "$DJANGO_ERR"
    fi
fi
