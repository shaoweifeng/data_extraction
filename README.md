# 自动化数据提取平台

基于 Django、Celery 和 Vue 3 的文献初筛与质量评价平台。后端采用模块化单体，业务代码按 `screening`、`quality`、`workflow`、`artifacts` 和 `ai` 划分；前端按 `features` 划分。

## 环境

- Python 3.9
- MySQL 8（或兼容版本）
- Redis
- Node.js 仅用于本地开发和构建；服务器可直接使用已提交的 `web/dist`

复制 `.env.example` 为 `.env`，至少配置数据库和生产环境的 `DJANGO_SECRET_KEY`。AI 服务只需配置实际使用的供应商密钥。

## 安装与启动

```bash
python3.9 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/python manage.py migrate
./start.sh
```

服务器没有 Node 时：

```bash
./start.sh --no-build
```

## 验证

```bash
MPLCONFIGDIR=/tmp/data-extraction-mpl venv/bin/python manage.py check
MPLCONFIGDIR=/tmp/data-extraction-mpl venv/bin/python manage.py test core.tests --settings=platform_backend.test_settings
cd web && npm ci && npm test && npm run lint -- --quiet && npm run build
```

架构入口见 [当前架构说明](docs/architecture.md)，接口见 [API 契约](docs/api-contract-baseline.md)，部署、备份与恢复见 [运行维护说明](docs/operations.md)。
