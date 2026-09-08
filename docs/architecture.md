# 当前架构说明

本文档是项目重构完成后的结构基线。历史方案、阶段实施记录和已失效的代码地图不再随仓库维护；接口细节见 `api-contract-baseline.md`，部署与恢复见 `operations.md`。

## 总体边界

项目采用 Django 模块化单体与 Vue 3 feature 结构。数据库表和正式 HTTP 路径保持稳定，Python 实现按业务领域组织，不保留旧模块的转发或 re-export 兼容层。

```text
core/
├── ai/                 # AI Provider、额度预检、用量记录与结算
├── api/                # 账户、项目、文件、任务等公共 API
├── artifacts/          # 产物类型与产物服务
├── screening/          # 初筛 API、领域规则、执行器、解析器、导出器与服务
├── quality/            # 质量评价 API、方法配置、执行器、图表与导出
├── workflow/           # 状态机、任务启动边界与执行运行时
├── executors/          # 通用执行框架和 AI Provider 适配
├── services/           # 跨功能的访问策略、项目、任务与并发服务
└── tests/              # 长期回归、契约、边界和迁移测试

web/src/
├── features/
│   ├── account/        # 登录与个人账户
│   ├── billing/        # 额度接口
│   ├── projects/       # 项目列表和工作区
│   ├── screening/      # 初筛组件、API、Store 与交互控制器
│   ├── quality/        # 质量评价组件、API 与能力 Store
│   └── workflow/       # 任务状态
├── shared/             # HTTP、轮询、下载和无业务归属的布局组件
├── router/             # 路由装配
└── utils/              # 无状态工具
```

## 依赖方向

- `core/api` 负责公共资源接口；初筛和质量评价接口分别由 `core/screening/api`、`core/quality/api` 实现，并在 `core/urls.py` 统一装配。
- `core/screening` 与 `core/quality` 可依赖 `core/ai`、`core/artifacts`、`core/workflow` 和公共服务；公共层不得反向依赖具体前端 feature。
- AI 初筛与 AI 质量评价共用 Provider、额度预检、Token 用量累计和结算基础设施，但保留各自的 Prompt、响应解析和领域结果。
- 前端 feature 通过自身 API 模块访问后端；`shared` 不直接读取初筛或质量评价 Store。跨 feature 的页面级重置由应用装配层处理。
- 异步任务由统一任务启动服务创建，由 Worker 认领和执行；解析、去重、AI 初筛、图表生成等轮询在组件卸载或项目切换时可取消。

## 正式接口与旧代码判定

- `/api/qa/*` 和 `/api/review/*` 是当前正式契约，前端仍直接使用，不能按目录名误判为旧 API。
- 已删除的旧 Python 入口包括 `core/api/qa_views.py`、`core/api/review_views.py`、`core/views.py`、`core/tasks.py`，以及旧 Handler、Parser、Serializer、质量方法和服务的转发模块。
- `web/src/api`、`web/src/stores`、`web/src/views`、`web/src/components` 下不再保留源码；代码统一从 `features` 或 `shared` 导入。

## 已确认的产品语义

- 管理员可以访问所有项目；普通用户只能访问自己的项目。
- 暂不实现成员协作。
- QA 从初筛导入时先清空该项目当前 QA 文献、评价结果、图表和关联设置。
- 未人工审阅的初筛文件默认采用 AI 判断。
- 删除项目为直接清空，不保留软删除或回收站。
- 图表由 Python/Matplotlib 异步生成，不依赖 R 或 robvis。
- 兼容 Python 3.9；服务器可使用 `./start.sh --no-build`，前端 `web/dist` 必须提交。

## 验证入口

```bash
MPLCONFIGDIR=/tmp/data-extraction-mpl venv/bin/python manage.py check
MPLCONFIGDIR=/tmp/data-extraction-mpl venv/bin/python manage.py test core.tests --settings=platform_backend.test_settings
cd web && npm test && npm run lint -- --quiet && npm run build
```
