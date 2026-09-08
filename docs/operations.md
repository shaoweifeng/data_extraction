# 运行维护说明

## 环境变量

| 变量 | 必需性 | 说明 |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | 生产必需 | Django 签名密钥，禁止提交到 Git |
| `DJANGO_DEBUG` | 可选 | 生产环境设为 `False` |
| `DJANGO_ALLOWED_HOSTS` | 生产必需 | 逗号分隔的允许主机 |
| `DB_NAME/DB_USER/DB_PASSWORD/DB_HOST/DB_PORT` | 必需 | MySQL 连接参数 |
| `CELERY_BROKER_URL` | 必需 | Redis Broker 地址 |
| `CELERY_RESULT_BACKEND` | 可选 | 默认使用 Django 数据库 |
| `DEEPSEEK_* / DOUBAO_* / QWEN_*` | 按需 | AI Provider 地址、模型与密钥 |
| `MPLCONFIGDIR` | 可选 | Matplotlib 缓存目录；启动脚本默认使用项目 `.cache` |

完整示例见 `.env.example`。

## 启动检查

本地构建模式执行 `./start.sh`。服务器无 Node 环境执行 `./start.sh --no-build`，该模式直接使用版本库中的 `web/dist`。上线前至少确认：

```bash
bash -n start.sh
test -f web/dist/index.html
venv/bin/python manage.py check
venv/bin/python manage.py migrate --check
```

## 数据库备份与恢复

备份前停止写任务或进入维护窗口：

```bash
mysqldump --single-transaction --routines --triggers -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p "$DB_NAME" > backup.sql
```

恢复到空数据库后执行迁移检查：

```bash
mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p "$DB_NAME" < backup.sql
venv/bin/python manage.py migrate
venv/bin/python manage.py check
```

项目文件位于 `media/` 与任务工作目录中，数据库备份必须与对应文件快照一起保存。删除项目按产品规则直接清空，不保留应用内回收站。
