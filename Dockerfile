# 使用官方 Python 镜像
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖 (包括 Redis 和 PDF 处理所需的库)
RUN apt-get update && apt-get install -y \
    redis-server \
    gcc \
    python3-dev \
    libmupdf-dev \
    && rm -rf /var/lib/apt/lists/*

# 拷贝依赖文件并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝项目文件
COPY . .

# 暴露端口
EXPOSE 8000

# 启动脚本
COPY start.sh /start.sh
RUN chmod +x /start.sh

CMD ["/start.sh"]
