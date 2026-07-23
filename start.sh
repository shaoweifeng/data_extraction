#!/bin/bash

# ============================================================
# 启动脚本：支持后台守护模式 + 集中日志 + PID 管理
#
# 用法：
#   ./start.sh          # 前台模式（终端可见日志，Ctrl+C 停止）
#   ./start.sh -d       # 后台守护模式（日志写文件，进程常驻）
#   ./stop.sh           # 停止所有后台进程（守护模式配套）
# ============================================================

echo "🚀 正在启动自动化数据提取平台 (Django + Celery)..."

# ── 守护模式开关 ──────────────────────────────────────────
DAEMON_MODE=false
if [ "$1" = "-d" ]; then
    DAEMON_MODE=true
    echo "📌 守护模式：所有进程后台运行，日志写入 logs/"
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

# 0) 数据库配置（MySQL）
export DB_NAME=${DB_NAME:-data_extraction}
export DB_USER=${DB_USER:-root}
export DB_PASSWORD=${DB_PASSWORD:-123456}
export DB_HOST=${DB_HOST:-127.0.0.1}
export DB_PORT=${DB_PORT:-3306}

# AI 筛选配置
# AI_PROVIDER: 使用的 AI 引擎，默认 deepseek（当前支持: deepseek / doubao / qwen）
# AI_TIMEOUT : 单次请求超时秒数，默认 120
export AI_TIMEOUT=${AI_TIMEOUT:-120}

# DeepSeek 配置
export DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY:-sk-f9652b9622494e9cbcd9c43a7d25eff7}
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

# 1. 启动 Redis (后台)
if command -v redis-server > /dev/null; then
    redis-server --daemonize yes 2>/dev/null || true  # 已在运行时忽略错误
    echo "✅ Redis 已启动"
else
    echo "❌ 错误: 未找到 redis-server，请先安装 Redis"
    exit 1
fi

# 2. 启动 Celery Worker (后台)
# 先清理旧的 worker 进程，避免重启后出现双 worker 抢任务的问题
OLD_PIDS=$(pgrep -f "celery.*platform_backend" 2>/dev/null)
if [ -n "$OLD_PIDS" ]; then
    echo "⚠️  发现旧 Celery Worker 进程 (PID: $OLD_PIDS)，正在终止..."
    kill $OLD_PIDS 2>/dev/null
    sleep 2
    echo "✅ 旧进程已终止"
fi
# -P threads: 使用线程池（代替 prefork），AI 初筛是 I/O 密集型任务，线程模式内存更省
# -c 16: 允许最多 16 个任务并发（每个 ai_screen 项目占用 1 个槽）
nohup celery -A platform_backend worker --loglevel=info -P threads -c 16 \
    >> "$CELERY_LOG" 2>&1 &
CELERY_PID=$!
echo $CELERY_PID > "$PID_DIR/celery.pid"
echo "✅ Celery Worker 已在后台启动 (PID: $CELERY_PID, 并发槽: 16, 模式: threads)"
echo "   日志: $CELERY_LOG"

# 3. 启动 Django Server
echo "✅ Django 服务即将启动，请访问 http://127.0.0.1:8000"

if [ "$DAEMON_MODE" = true ]; then
    # ── 守护模式：Django 也后台运行，日志写文件 ──────────
    # Django runserver stdout = access log；stderr = error/traceback
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
else
    # ── 前台模式：Django 前台阻塞，方便开发调试 ──────────
    echo "   (前台模式，Ctrl+C 可停止 Django；Celery 仍在后台运行)"
    echo "   如需后台常驻，请使用: ./start.sh -d"
    python3 manage.py runserver 0.0.0.0:8000
fi
