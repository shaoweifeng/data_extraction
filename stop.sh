#!/bin/bash

# ============================================================
# 停止脚本：停止由 start.sh -d 启动的所有后台进程
#
# 用法：./stop.sh
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_DIR="$SCRIPT_DIR/pids"

echo "🛑 正在停止数据提取平台..."

stop_process() {
    local name=$1
    local pid_file="$PID_DIR/${name}.pid"

    if [ ! -f "$pid_file" ]; then
        echo "⚠️  $name: 未找到 PID 文件，尝试按进程名查找..."
        return
    fi

    local pid
    pid=$(cat "$pid_file")

    if kill -0 "$pid" 2>/dev/null; then
        kill "$pid"
        sleep 1
        # 确认是否已退出，否则强杀
        if kill -0 "$pid" 2>/dev/null; then
            echo "⚠️  $name (PID: $pid) 未响应，强制终止..."
            kill -9 "$pid" 2>/dev/null
        fi
        echo "✅ $name (PID: $pid) 已停止"
    else
        echo "⚠️  $name (PID: $pid) 进程不存在（可能已停止）"
    fi

    rm -f "$pid_file"
}

# 停止 Django
stop_process "django"

# 停止 Celery（同时兜底用 pgrep 清理残余）
stop_process "celery"
OLD_PIDS=$(pgrep -f "celery.*platform_backend" 2>/dev/null)
if [ -n "$OLD_PIDS" ]; then
    echo "⚠️  发现残余 Celery 进程 (PID: $OLD_PIDS)，正在清理..."
    kill $OLD_PIDS 2>/dev/null
fi

echo ""
echo "✅ 平台已停止。Redis 仍在后台运行（如需停止：redis-cli shutdown）"
