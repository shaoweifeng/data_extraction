#!/bin/bash

echo "🚀 正在启动自动化数据提取平台 (Django + Celery)..."

# 1. 启动 Redis (后台)
if command -v redis-server > /dev/null; then
    redis-server --daemonize yes
    echo "✅ Redis 已启动"
else
    echo "❌ 错误: 未找到 redis-server，请先安装 Redis"
    exit 1
fi

# 2. 启动 Celery Worker (后台)
celery -A platform_backend worker --loglevel=info > celery.log 2>&1 &
echo "✅ Celery Worker 已在后台启动 (日志: celery.log)"

# 3. 启动 Django Server
echo "✅ Django 服务即将启动，请访问 http://127.0.0.1:8000"
python3 manage.py runserver 0.0.0.0:8000
