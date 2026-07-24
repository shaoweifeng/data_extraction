#!/bin/bash
# ============================================================
# 启动脚本：支持后台守护模式 + 集中日志 + PID 管理
#
# 用法：
#   ./start.sh              # 前台模式（构建前端后启动，Ctrl+C 停止）
#   ./start.sh -d           # 后台守护模式（日志写文件，进程常驻）
#   ./start.sh --dev        # 开发模式（前台，跳过构建，启动 Vite dev server）
#   ./start.sh --dev -d     # 开发模式守护（Vite + Django 均后台）
#   ./start.sh --no-build   # 跳过前端构建（前台）
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

# ── 目录准备 ─────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
PID_DIR="$SCRIPT_DIR/pids"
mkdir -p "$LOG_DIR" "$PID_DIR"

# ── 日志文件路径 ──────────────────────────────────────────
DJANGO_LOG="$LOG_DIR/django.log"
DJANGO_ERR="$LOG_DIR/error.log"
CELERY_LOG="$LOG_DIR/celery.log"
VITE_LOG="$LOG_DIR/vite.log"

# 0) 数据库配置（MySQL）
export DB_NAME=${DB_NAME:-data_extraction}
export DB_USER=${DB_USER:-root}
export DB_PASSWORD=${DB_PASSWORD:-123456}
export DB_HOST=${DB_HOST:-127.0.0.1}
export DB_PORT=${DB_PORT:-3306}

# AI 筛选配置
export AI_TIMEOUT=${AI_TIMEOUT:-120}

# DeepSeek 配置
export DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY:-sk-dcc67593b429483daf0be1d45a7c0290}
export DEEPSEEK_API_URL=${DEEPSEEK_API_URL:-https://api.deepseek.com/v1}
export DEEPSEEK_MODEL=${DEEPSEEK_MODEL:-deepseek-v4-flash}

# 豆包（字节跳动 Doubao / Ark）配置
export DOUBAO_API_KEY=${DOUBAO_API_KEY:-8dfb9fb8-77c9-4db3-be22-0aff21ecaf89}
export DOUBAO_API_URL=${DOUBAO_API_URL:-https://ark.cn-beijing.volces.com/api/v3}
export DOUBAO_MODEL=${DOUBAO_MODEL:-ep-20260509162819-bvjfj}

# 千问（阿里云 DashScope）配置
export QWEN_API_KEY=${QWEN_API_KEY:-sk-022f866434dc4165a448503ebb766f38}
export QWEN_API_URL=${QWEN_API_URL:-https://dashscope.aliyuncs.com/compatible-mode/v1}
export QWEN_MODEL=${QWEN_MODEL:-qwen-plus}

# 兼容旧环境变量（保留，优先级低于上方）
export AI_API_KEY=${AI_API_KEY:-$DEEPSEEK_API_KEY}
export AI_API_URL=${AI_API_URL:-$DEEPSEEK_API_URL}
export AI_MODEL=${AI_MODEL:-$DEEPSEEK_MODEL}

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
# 先清理旧的 worker 进程，避免重启后出现双 worker 抢任务的问题
OLD_PIDS=$(pgrep -f "celery.*platform_backend" 2>/dev/null)
if [ -n "$OLD_PIDS" ]; then
    echo "⚠️  发现旧 Celery Worker 进程 (PID: $OLD_PIDS)，正在终止..."
    kill $OLD_PIDS 2>/dev/null
    sleep 2
    echo "✅ 旧进程已终止"
fi

nohup celery -A platform_backend worker --loglevel=info -P threads -c 16 \
    >> "$CELERY_LOG" 2>&1 &
CELERY_PID=$!
echo $CELERY_PID > "$PID_DIR/celery.pid"
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

# 4. 启动 Django Server
if [ "$DEV_MODE" = true ]; then
    echo "✅ Django 服务即将启动，请访问 http://127.0.0.1:8000 (API)"
else
    echo "✅ Django 服务即将启动，请访问 http://127.0.0.1:8000"
fi

if [ "$DAEMON_MODE" = true ]; then
    # ── 守护模式：Django 也后台运行，日志写文件 ──────────
    nohup python3 manage.py runserver 0.0.0.0:8000 \
        >> "$DJANGO_LOG" 2>> "$DJANGO_ERR" &
    DJANGO_PID=$!
    echo $DJANGO_PID > "$PID_DIR/django.pid"
    echo "✅ Django 已在后台启动 (PID: $DJANGO_PID)"
    echo "   访问日志 : $DJANGO_LOG"
    echo "   错误日志 : $DJANGO_ERR"
    echo ""
    echo "👉 查看日志  : tail -f $DJANGO_LOG"
    echo "👉 查看报错  : tail -f $DJANGO_ERR"
    echo "👉 停止服务  : ./stop.sh"
    if [ "$DEV_MODE" = true ]; then
        echo "👉 前端日志  : tail -f $VITE_LOG"
    fi
else
    # ── 前台模式：Django 前台阻塞，方便开发调试 ──────────
    echo "   (前台模式，Ctrl+C 可停止；Celery 仍在后台运行)"
    echo "   如需后台常驻，请使用: ./start.sh -d"
    python3 manage.py runserver 0.0.0.0:8000
fi
