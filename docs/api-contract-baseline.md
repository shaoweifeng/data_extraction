# API 契约

## 1. 用途

本文档记录当前前后端依赖的正式 HTTP 契约。`/api/qa/*` 和 `/api/review/*` 是现行公开路径；模块实现分别位于 `core/quality` 和 `core/screening`，路径名称不代表旧兼容入口。

## 2. 统一规则

- 认证：使用 Django Session。未登录请求返回 `401/403` 或跳转响应（依视图类型）。
- CSRF：`POST` / `PATCH` / `PUT` / `DELETE` 必须携带 `X-CSRFToken`。前端从 `csrftoken` Cookie 读取。
- 项目可见性：超级管理员和 `role=admin` 可见全部项目；普通用户只可见自己的项目。
- 不存在与无权访问项目级资源时，对外统一使用 `404`，避免泄露资源是否存在。
- QA 函数视图成功响应：`{"ok": true, "data": ...}`。
- QA 函数视图失败响应：`{"ok": false, "error": ...}`。
- 初筛复核视图保留原有顶层响应字段，错误为 `{"error": ...}`。
- 排空和维护期间被阻止的接口返回 `503`，并携带 `SYSTEM_DRAINING` 或 `SYSTEM_MAINTENANCE` 错误码。

## 3. 核心项目资源

| 方法 | 路径 | 核心契约 |
|---|---|---|
| GET/POST | `/api/projects/` | 列出可见项目 / 创建归属当前用户的项目 |
| GET/PATCH/DELETE | `/api/projects/{id}/` | 读写或直接删除可访问项目 |
| GET | `/api/projects/{id}/stages/` | 项目阶段和步骤 |
| GET | `/api/stages/`, `/api/steps/`, `/api/tasks/`, `/api/files/` | 仅返回可见项目的下级资源 |
| POST | `/api/tasks/` | `project`, `task_type`, `config`；项目必须可访问 |
| POST | `/api/files/` | 文件必须归属可访问项目，`stage/step/project` 关系必须一致 |

## 4. 初筛人工复核

| 方法 | 路径 | 输入 / 输出要点 |
|---|---|---|
| GET | `/api/review/list/?project=&step=&decision=&q=&page=&page_size=` | 分页文献，验证 `step` 属于可访问项目的 `review` 步骤 |
| POST | `/api/review/submit/` | `project`, `step`, `reviews[]` |
| PATCH | `/api/review/item/{source_xml}/` | `project`, `step`, `decision`, `reason` |
| GET | `/api/review/stats/?project=` | 统计；未人工审阅文献默认 AI 判断正确 |
| POST | `/api/review/complete/` | `project`, `step` |
| POST/GET | `/api/review/note(s)/{source_xml}/` | 追加 / 读取项目内文献备注 |

## 5. QA

| 方法 | 路径 | 输入 / 输出要点 |
|---|---|---|
| GET | `/api/qa/refs/?project_id=` | 项目 QA 文献列表 |
| POST | `/api/qa/refs/import/` | `project_id`, `source_stage`；每次导入先清空当前 QA 文献、评价结果、图表及其旧 ref_id 设置 |
| POST | `/api/qa/refs/upload/` | multipart PDF，单文件不超过 50MB |
| PATCH | `/api/qa/refs/{id}/` | 只允许 schema 中声明的文献字段 |
| POST | `/api/qa/refs/batch-method/` | `ref_ids[]`, `quality_method`；必须是同一可访问项目 |
| POST | `/api/qa/eval/start/` | `project_id`, `ref_ids[]`, `model_ids[]`；验证项目、文献、模型和积分 |
| GET | `/api/qa/eval/progress/?project_id=` | 项目评价进度 |
| GET/PATCH/POST | `/api/qa/signal-items/...` | 仅访问可见项目的 QA 文献和信号问题 |
| GET | `/api/qa/domain-results/?qa_ref_id=` | 文献领域汇总 |
| POST | `/api/qa/chart/preview/` | `project_id`, `quality_method`, `ref_ids[]` |
| POST | `/api/qa/chart/generate/` | 同上，另含 `study_labels`, `orientation`, `lang`；返回 `202` 和异步 `task_id` |
| GET/PATCH | `/api/qa/chart/settings...` | 读写项目图表标签设置 |
| POST | `/api/qa/export/excel/` | `project_id`, `quality_method`, `include_unconfirmed` |

## 6. 运维接口

| 方法 | 路径 | 核心契约 |
|---|---|---|
| GET | `/api/health/live/` | Web 进程存活检查 |
| GET | `/api/health/ready/` | MySQL、Redis和维护状态就绪检查 |
| GET | `/api/system/status/` | 公开的 normal/draining/maintenance 状态与通知 |
| POST | `/api/presence/heartbeat/` | 登录用户页面心跳 |
| GET | `/api/operations/status/` | 仅管理员；在线用户、任务、Celery和安全停机判断 |
| POST | `/api/operations/state/` | 仅管理员；切换系统运行状态 |
| POST | `/api/operations/tasks/pause/` | 仅管理员；协作式暂停可恢复的长任务 |
| POST | `/api/operations/tasks/resume/` | 仅管理员；恢复维护暂停任务 |

## 7. 用户反馈

| 方法 | 路径 | 核心契约 |
|---|---|---|
| POST | `/api/feedback/` | 仅普通登录用户；multipart，必须携带 UUID 格式的 `Idempotency-Key`；返回反馈编号和当日剩余次数 |
| GET | `/api/feedback/attachments/{uuid}/` | 仅附件所属用户或管理员；图片来自私有存储，不暴露真实文件路径 |

反馈正文、图片数量/大小、分钟频率和每日次数均由服务端校验。相同用户使用相同幂等键重试时返回原反馈且不重复计数。反馈提交接口在排空或维护模式下仍可用。

## 8. 自动化门禁

- Python 3.9、Django 4.2 兼容。
- `manage.py check`、迁移漂移检查和 `core.tests` 必须通过。
- 前端使用 Node 22 仅在本地/持续集成构建；服务器可继续使用 `--no-build` 和已提交的 `web/dist`。
- CI 检查构建后 `web/dist` 无差异，确保提交的产物与源码一致。

## 9. 机器可读 Schema

- OpenAPI 3.0 基线文件：`docs/openapi.json`。
- 运行时地址：`GET /api/schema/`。
- Schema 本身、前端关键路径覆盖和核心响应形状由持续集成中的契约测试校验。
