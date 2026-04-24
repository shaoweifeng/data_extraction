#!/bin/bash

echo "🚀 正在启动自动化数据提取平台 (Django + Celery)..."

# 0) 数据库配置（MySQL）
export DB_NAME=${DB_NAME:-data_extraction}
export DB_USER=${DB_USER:-root}
export DB_PASSWORD=${DB_PASSWORD:-123456}
export DB_HOST=${DB_HOST:-127.0.0.1}
export DB_PORT=${DB_PORT:-3306}

# AI 筛选配置
# AI_PROVIDER: 使用的 AI 引擎，默认 deepseek（当前支持: deepseek）
# AI_API_KEY : API 密钥（必填，留空则使用 mock 模拟数据）
# AI_API_URL : 接口地址，默认 https://api.deepseek.com/v1（兼容 OpenAI 格式的服务可直接替换）
# AI_MODEL   : 模型名称，默认 deepseek-chat
# AI_TIMEOUT : 单次请求超时秒数，默认 120
export AI_PROVIDER=${AI_PROVIDER:-deepseek}
export AI_API_KEY=${AI_API_KEY:-sk-f9652b9622494e9cbcd9c43a7d25eff7}
export AI_API_URL=${AI_API_URL:-https://api.deepseek.com/v1}
export AI_MODEL=${AI_MODEL:-deepseek-chat}
export AI_TIMEOUT=${AI_TIMEOUT:-120}

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
