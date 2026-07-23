# 架构演进落地方案（可执行清单）

> 文档创建时间：2026-04-18  
> 适用范围：当前分支 / 当前代码结构  
> 依赖文档：`docs/architecture-evolution-plan.md`  
> 目标：把“架构演进方案”拆成可分批合并的改造任务，尽量做到每一步可验证、可回滚

---

## 1. 总体实施策略

### 1.1 改造原则

- 先做结构整理，再做能力扩展
- 每次变更尽量“小步可合并”：一次 PR/一次提交只做一个主题
- 尽量保持 API 向后兼容（前端先不大改接口），必要时提供短期兼容层
- 所有“行为改变”必须有可验证的验收标准

### 1.2 分批交付结构

建议按 4 个批次推进，每批都能独立落地：

- 批次 A：后端 API 层拆分（不改业务逻辑）
- 批次 B：服务层抽取（把复杂逻辑从 ViewSet 和 Executor 中抽离）
- 批次 C：步骤 handler 注册机制（把步骤实现从大执行器中拆出）
- 批次 D：前端模块化（先拆 API/轮询/模块，不强制迁 Vite）

本文件重点把批次 A 和 B 拆到“可以直接做”的粒度；批次 C/D 给出落地路径和拆分边界。

---

## 2. 当前关键入口与依赖图（用于改造时对照）

### 2.1 后端核心入口

- 路由入口：`core/urls.py`
- API 聚合：`core/views.py`
- 调度编排：`core/scheduler.py`
- 同步执行：`core/executors/sync_executor.py`
- 异步执行：`core/executors/async_executor.py`
- Celery 入口：`core/executors/celery_tasks.py`
- 监控读取：`core/monitoring.py`

### 2.2 关键对象职责（改造时保持不变）

- `Project / ProjectStage / StageStep / Task / DataFile` 的基本模型字段不做大改
- 工作区目录仍保持 `workspaces/project_{id}/...` 结构
- AI Provider 层 `core/executors/ai_providers/` 不动

---

## 3. 批次 A：`views.py` 拆分（低风险，立刻做）

### 3.1 目标

- 把 `core/views.py` 拆成多个文件
- 不改变路由、不改变行为、不改变权限校验语义
- `core/views.py` 最终只保留兼容导入或彻底替换为 `core/api/` 下的模块

### 3.2 目标目录

新增目录：

```text
core/api/
  __init__.py
  auth_views.py
  project_views.py
  stage_views.py
  step_views.py
  task_views.py
  file_views.py
  prompt_views.py
  activity_log_views.py
  user_views.py
  ai_model_views.py
```

备注：如果你希望命名更贴近 DRF（例如 `project.py`），也可以，但建议在 `core/api/` 里保持一致风格。

### 3.2.1 文件命名规范（建议统一采用）

本项目建议将“后缀”作为层次含义的一部分：

- `*_views.py`：API 层（DRF ViewSet / function-based API）。只做入参校验、权限校验、调用 service、返回 Response。
- `*_service.py`：业务服务层。放跨 View/Executor 的业务规则与复用逻辑。
- `*_handler.py`：步骤执行层（后续批次 C）。每个步骤一个 handler，负责执行与产物落地。
- `*_provider.py`：第三方能力适配层（例如 AI provider），只做对外 API 的适配与最小封装。

如果未来模块数量继续增多，建议用“包 + 简短文件名”的方式进一步收敛：

```text
core/api/project/
  __init__.py
  views.py
  serializers.py
  selectors.py
```

目前阶段维持 `project_views.py` 这种命名更直观、也更方便 grep 与定位。

### 3.3 拆分映射清单（从 `core/views.py` 迁移到哪里）

- 认证相关：登录、注册、当前用户、登出 → `auth_views.py`
- 项目相关：ProjectViewSet + 其 actions（stages、clear_ai_screen_results、ai_screen_stats、prompt 等） → `project_views.py` 与 `prompt_views.py`
- 阶段相关：ProjectStageViewSet → `stage_views.py`
- 步骤相关：StageStepViewSet + update_metadata/skip/reset → `step_views.py`
- 任务相关：TaskViewSet（启动/停止/恢复/进度/日志/tail） → `task_views.py`
- 文件相关：DataFileViewSet（上传、列表、删除、下载） → `file_views.py`
- 活动日志：ActivityLogViewSet → `activity_log_views.py`
- 用户管理：UserViewSet → `user_views.py`
- AI 模型：模型列表、配置相关接口 → `ai_model_views.py`

### 3.4 具体实施步骤（按顺序做）

1. 新建 `core/api/__init__.py`，并在其中导出各 ViewSet
2. 先迁移“无依赖/低耦合”的 ViewSet：ActivityLog、AIModel、User
3. 迁移 Project（含 prompt actions）
4. 迁移 Stage/Step
5. 迁移 Task/File（这两个引用最多，放最后）
6. 修改 `core/urls.py`：从 `core.api` 导入 ViewSet，而不是从 `core.views` 导入
7. 保留 `core/views.py` 的兼容层（可选）：只做 import re-export，避免其它模块 import 失效

### 3.5 验收标准

- `./start.sh` 启动后，页面可正常登录、创建项目、上传、启动任务、暂停、继续、导出
- 所有 API 路由不变（路径与方法不变）
- 后端不出现导入错误、循环依赖

---

## 4. 批次 B：抽出 `services/`（中风险，但收益最大）

### 4.1 目标

- 让 ViewSet 只做：参数校验、权限校验、调用 service、返回 Response
- 让 Executor 只做：流程执行、调用 service、写入产物
- 把“业务规则”集中到可测试的 service 中

### 4.2 建议新增目录

```text
core/services/
  __init__.py
  task_service.py
  progress_service.py
  artifact_service.py
  prompt_service.py
  project_service.py
```

### 4.3 服务拆分建议（先做 4 个最关键的）

#### 4.3.1 `task_service.py`

职责：

- 统一任务创建：创建 `Task`、绑定 stage/step、填充 config
- 统一任务状态变更：running/stopped/completed/failed
- 统一 resume/superseded 逻辑
- 封装 ActivityLog 写入（避免散落）

输入输出建议：

- 输入：project_id、user_id、step_key、config
- 输出：Task 对象

#### 4.3.2 `progress_service.py`

职责：

- 统一获取进度：优先读 `progress_*.json`，回退 `Task.progress`
- 统一日志读取：优先读 `task_*.log`，回退 `Task.logs`
- 把“文件路径推导规则”集中，避免散落到 monitoring/scheduler/view

#### 4.3.3 `artifact_service.py`

职责：

- 封装 `DataFile` 的创建、删除、查询过滤
- 统一产物分类约定：`data_category/source/metadata.artifact_type`
- 提供常用查询：按项目/步骤/类别/标签取列表

#### 4.3.4 `prompt_service.py`

职责：

- get/save/reset 自定义 prompt 的读写逻辑
- 统一 prompt 校验规则（例如必须包含占位符）

### 4.4 实施顺序

1. 先抽 `progress_service`（最少侵入，只是整理读取逻辑）
2. 再抽 `prompt_service`（改动面小）
3. 抽 `artifact_service`（会影响较多调用点，但收益大）
4. 最后抽 `task_service`（影响最大，但完成后可大幅降低耦合）

### 4.5 验收标准

- `TaskViewSet`、`ProjectViewSet`、`DataFileViewSet` 中的复杂逻辑显著减少
- `core/services` 内部可独立被单元测试调用
- 行为不变（接口结果字段不变，任务流不变）

---

## 5. 批次 C：步骤 handler 注册机制（中高风险，需分批）

### 5.1 目标

- 新增/修改步骤，不再改大执行器文件
- `scheduler` 根据注册表定位步骤 handler

### 5.2 实施建议（分 3 次完成）

1. 引入 `core/executors/registry.py` 作为注册表，但先不改现有执行器
2. 先把 `parse` 从 `sync_executor.py` 抽出成 handler，验证链路等价
3. 再依次抽 `dedup`、`export`，最后抽 `ai_screen`

### 5.3 验收标准

- 每抽一个步骤都能跑通“从前端启动到完成”的全链路
- 不出现“新增步骤要同时改 3 个入口文件”的情况

---

## 6. 批次 D：前端模块化（低风险拆分优先）

### 6.1 目标

- 先拆“逻辑层”，不立刻换工程化
- 减少 `index.html` 内的耦合与重复

### 6.2 拆分优先级

1. 抽 `apiRequest` / 超时 / 错误处理 → `frontend/js/api/http.js`
2. 抽任务轮询（通用）→ `frontend/js/api/task.js`
3. 抽文件查询/上传/删除 → `frontend/js/api/file.js`
4. 抽文献初筛模块状态与流程 → `frontend/js/state/screening.js`

### 6.3 验收标准

- 页面功能不变，但 `index.html` 中的函数和状态显著减少
- 新增第二个大功能时可以直接新增 module，而不是继续堆 `index.html`

---

## 7. 目录迁移清单（按批次提交）

### 7.1 批次 A（API 拆分）

- 新增：`core/api/` 目录与文件
- 修改：`core/urls.py` 的导入路径
- 可选：`core/views.py` 变成兼容 re-export 文件

### 7.2 批次 B（Services）

- 新增：`core/services/` 目录与文件
- 修改：`core/api/*_views.py` 中的逻辑下沉到 service
- 修改：`core/monitoring.py` / `core/scheduler.py` 中读取逻辑聚合到 `progress_service`

### 7.3 批次 C（Handlers）

- 新增：`core/executors/registry.py`
- 新增：`core/executors/handlers/` 目录
- 修改：`core/scheduler.py` 的步骤执行分发
- 逐步收缩：`sync_executor.py`、`async_executor.py`

### 7.4 批次 D（前端拆分）

- 新增：`frontend/js/` 目录（不影响后端）
- 修改：`frontend/index.html` 的 script 引用与代码组织

---

## 8. 风险与回滚策略

### 8.1 主要风险

- 导入循环：views 拆分后相互引用导致循环
- 路由漂移：core/urls.py 引用对象变了但路由名不一致
- 前后端契约漂移：接口字段被“顺手整理”导致前端报错

### 8.2 回滚策略

- 批次 A 结束时保留 `core/views.py` re-export：随时可切回老导入
- 每批次都保持接口不变：任何不兼容修改单独拆到后续批次
- 只在批次结束后做一次“行为性小优化”，避免改造和优化混在一起

---

## 9. 第一阶段（批次 A）任务拆分建议

以下是“可以直接开干”的子任务列表：

1. 新建 `core/api/` 与 `__init__.py`  
2. 迁移 `ActivityLogViewSet`  
3. 迁移 AI 模型相关 ViewSet  
4. 迁移 `UserViewSet`  
5. 迁移 `ProjectViewSet` 与 prompt actions  
6. 迁移 `ProjectStageViewSet`、`StageStepViewSet`  
7. 迁移 `TaskViewSet`、`DataFileViewSet`  
8. 修改 `core/urls.py` 导入，跑通启动  
9. 可选：保留 `core/views.py` 兼容 re-export

每个子任务都建议单独提交，便于回滚与审阅。
