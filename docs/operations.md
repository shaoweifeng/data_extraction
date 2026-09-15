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
| `ACCOUNT_REGISTRATION_V2_ENABLED` | 可选 | 阶段 1 新注册链路开关；完成邮箱验证前保持 `False` |
| `ACCOUNT_RATE_LIMIT_ENABLED` | 生产必需 | 公开注册或登录保护启用时设为 `True` |
| `RATE_LIMIT_REDIS_URL` | 生产必需 | 账户限流专用 Redis 地址，建议使用独立逻辑库 |
| `TRUSTED_PROXY_IPS` | 生产必需 | 可信 CDN/Nginx 地址或 CIDR，逗号分隔 |
| `DEEPSEEK_* / DOUBAO_* / QWEN_*` | 按需 | AI Provider 地址、模型与密钥 |
| `MPLCONFIGDIR` | 可选 | Matplotlib 缓存目录；启动脚本默认使用项目 `.cache` |
| `FEEDBACK_UPLOAD_ROOT` | 可选 | 用户反馈私有图片目录；默认 `private_media/feedback`，不能映射到公开静态 URL |
| `FEEDBACK_DAILY_LIMIT` | 可选 | 普通用户每日反馈上限，默认 5 |
| `FEEDBACK_MAX_IMAGES` | 可选 | 单条反馈图片数上限，默认 3 |
| `FEEDBACK_MAX_IMAGE_BYTES` | 可选 | 单张反馈图片字节上限，默认 5 MiB |
| `FEEDBACK_MAX_TOTAL_IMAGE_BYTES` | 可选 | 单条反馈图片总字节上限，默认 10 MiB |

完整示例见 `.env.example`。

## 启动检查

先激活项目虚拟环境；启停脚本使用当前 `PATH` 中的 `python`、`celery` 和 `gunicorn`，不要求虚拟环境位于项目目录。本地构建模式执行 `./start.sh`。服务器无 Node 环境执行 `./start.sh --no-build`，该模式直接使用版本库中的 `web/dist`。上线前至少确认：

```bash
bash -n start.sh
test -f web/dist/index.html
python manage.py check
python manage.py migrate --check
```

阶段 1 部署会新增 `account.0001_initial` 和 `core.0022_credittransaction_idempotency_key`。
部署 migration 后仍保持 `ACCOUNT_REGISTRATION_V2_ENABLED=false`，旧注册入口继续兼容；新链路完成预发布验证后再切换。账户限流启用前必须确认 `RATE_LIMIT_REDIS_URL` 可用，注册限流在 Redis 故障时会拒绝请求，登录限流则降级放行并告警。

部署前后可以执行只读账户审计；命令只输出数量，不输出完整邮箱：

```bash
python manage.py audit_accounts
python manage.py audit_accounts --json
python manage.py audit_accounts --fail-on-issues
```

MySQL 预发布环境使用独立测试库执行账户并发契约；不要把测试命令指向生产数据库：

```bash
python manage.py test core.account.tests.test_mysql_concurrency
```

## 在线状态与维护模式

管理员登录平台后，可从顶部「运维」入口查看：

- 最近 90 秒有页面心跳的在线用户及其当前页面；
- 最近 5 分钟活跃用户和未过期登录会话；
- 数据库中的 pending、queuing、running、stopping 任务；
- Celery active、reserved、scheduled 数量；
- 综合判断的「可以安全停机」状态。

登录会话只代表用户尚未退出，不代表用户正在操作。没有普通在线用户且没有活动业务任务时，即可开始停机；Celery、Gunicorn 和 Vite 正是 `stop.sh` 后续负责关闭的对象。管理员自己的心跳不会阻止停机。

运维页每 15 秒自动刷新一次，自动刷新不调用 Celery 远程检查。在线状态来自 Redis，任务查询只读取状态统计和最早 100 条活动任务的必要字段，不会载入任务的配置、结果或日志大字段。手工点击「刷新」时才会额外检查 Celery。

命令行也可以查看相同信息：

```bash
python manage.py operations_status
python manage.py operations_status --json
```

平台具有三种运行状态：

- `normal`：正常开放；
- `draining`：允许查看、下载和保存人工审阅，但禁止创建项目、上传文件以及启动或恢复任务；
- `maintenance`：普通用户业务 API 返回 503，仅管理员和健康检查可继续访问。

可以通过 Django 管理界面、平台运维页面或命令切换。平台运维页只修改运行状态，不会直接关闭 Gunicorn 或 Celery 进程：

```bash
python manage.py maintenance status
python manage.py maintenance draining --message "平台将在 20:30 升级"
python manage.py maintenance maintenance --message "平台正在升级"
python manage.py maintenance normal
```

## 优雅停机与升级

生产环境建议使用守护模式启动，服务器无 Node 环境继续使用已提交的 `web/dist`：

```bash
./start.sh -d --no-build
```

正常升级执行：

```bash
./stop.sh
git pull
pip install -r requirements.txt
python manage.py migrate
./start.sh -d --no-build
```

`stop.sh` 默认执行以下流程：

1. 进入 `draining`，停止接收新工作；
2. 等待在线用户离开和短任务自然完成；
3. 进入 `maintenance`；
4. 协作式暂停 AI 初筛和 AI 质量评价，并等待断点及状态写入完成；
5. 向 Celery 发送 TERM，执行 warm shutdown；
6. 向 Gunicorn 发送 TERM，等待正在处理的 HTTP 请求结束；
7. MySQL 和 Redis 保持运行。

默认等待时间可以调整：

```bash
./stop.sh --drain-timeout=600 --task-timeout=1200 --web-timeout=300
```

超过等待时间时，脚本会取消停机并保留维护状态，不会自动执行 `kill -9`。只有明确接受任务中断或中间文件损坏风险时才能使用：

```bash
./stop.sh --force
```

启动时会拒绝与旧 Gunicorn/Celery 进程并行运行，检查数据库迁移，修复异常退出遗留的孤儿任务；健康检查通过后恢复维护暂停的 AI 任务并重新开放平台。

AI 初筛通过 checkpoint 继续执行。AI 质量评价保留已经完成的文献，只重新处理未完成文献，避免重复评价和重复结算。解析、去重等没有断点能力的任务若因异常退出中断，会标记为失败并提示重新执行。

如需手工核对或恢复：

```bash
python manage.py reconcile_interrupted_tasks
python manage.py reconcile_interrupted_tasks --apply
python manage.py maintenance_tasks pause
python manage.py maintenance_tasks resume
```

健康检查接口：

```text
GET /api/health/live/
GET /api/health/ready/
```

`live` 只表示 Web 进程存活；`ready` 同时检查 MySQL、Redis及维护状态。

## 数据库备份与恢复

备份前停止写任务或进入维护窗口：

```bash
mysqldump --single-transaction --routines --triggers -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p "$DB_NAME" > backup.sql
```

恢复到空数据库后执行迁移检查：

```bash
mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p "$DB_NAME" < backup.sql
python manage.py migrate
python manage.py check
```

项目文件位于 `media/` 与任务工作目录中，反馈图片位于 `FEEDBACK_UPLOAD_ROOT`。数据库备份必须与这些目录的对应文件快照一起保存。删除项目按产品规则直接清空，不保留应用内回收站；用户反馈不会因关联项目或提交用户删除而自动丢失。

异常退出可能留下未完成数据库提交的孤立反馈图片。命令默认只预览，确认后再执行删除：

```bash
python manage.py cleanup_feedback_orphans
python manage.py cleanup_feedback_orphans --apply --older-than-hours=24
```
