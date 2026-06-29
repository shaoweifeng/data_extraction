# 项目重构方案

> 文档创建时间：2026-05-14  
> 适用分支：develop

---

## 背景

当前项目已完成 AI 初筛（SCREEN_1）阶段的核心功能开发，但随着功能持续迭代，代码结构已出现多处高技术负债点。为保障后续复筛、质量评价、Meta 分析等功能的可持续开发，需要在下一阶段功能开发前完成本次重构。

---

## 重构清单

### 🔴 P0 — 必须优先处理（安全/基础问题）

#### 1. 环境配置与密钥管理

**问题**
- `SECRET_KEY` 硬编码在 `platform_backend/settings.py`，已进入 git 历史
- `DEBUG = True`、`ALLOWED_HOSTS = ['*']` 无环境区分，上生产忘改即高危
- 所有敏感配置（数据库密码、AI API Key）均依赖 `start.sh` 手动注入，无统一管理

**目标结构**
```
platform_backend/
  settings/
    __init__.py
    base.py       ← 公共配置
    dev.py        ← 开发环境（DEBUG=True 等）
    prod.py       ← 生产环境（DEBUG=False、ALLOWED_HOSTS 等）
.env              ← 本地密钥（已在 .gitignore）
.env.example      ← 提交到 git 的示例文件（无真实值）
```

**复杂度**：⭐ 低  
**影响范围**：`settings.py`、`manage.py`、`wsgi.py`、`asgi.py`、`start.sh`

---

### 🟠 P1 — 严重影响长期可维护性

#### 2. `views.py` 拆分（当前 47KB）

**问题**  
认证、项目管理、任务控制、文件管理、导出、活动日志全部堆在 `core/views.py` 一个文件中，每个新功能继续往里追加，将来变成没人敢动的黑盒。

**目标结构**
```
core/views/
  __init__.py       ← 统一 import 入口
  auth.py           ← 登录、注册、登出、当前用户
  project.py        ← ProjectViewSet（含 clear_ai_screen_results 等 action）
  stage.py          ← StageViewSet、StageStepViewSet
  task.py           ← TaskViewSet（启动/停止/恢复）
  file.py           ← DataFileViewSet（上传、列表、下载）
  export.py         ← 导出相关 action
  log.py            ← ActivityLogViewSet
  ai_model.py       ← AI 模型列表接口
```

**复杂度**：⭐⭐ 中  
**影响范围**：`core/views.py` → `core/views/`、`core/urls.py`

---

#### 3. `sync_executor.py` 拆分（当前 48KB）

**问题**  
parse、dedup、export、criteria 四个步骤的执行逻辑全部堆在 `sync_executor.py`，靠 `if step_key == 'parse': ...` 分支区分。每新增步骤继续往里堆，违反单一职责原则。

**目标结构**
```
core/executors/
  base.py                 ← 保持不变（BaseExecutor）
  async_executor.py       ← 保持不变（AI 初筛异步执行）
  celery_tasks.py         ← 保持不变（Celery 入口）
  steps/
    __init__.py
    parse_executor.py     ← 文献解析
    dedup_executor.py     ← 自动去重
    criteria_executor.py  ← 纳排标准
    export_executor.py    ← 结果归纳/导出
  ai_providers/           ← 保持不变
```

每个 step executor 继承 `BaseExecutor`，实现 `execute()` 方法，`scheduler.py` 通过注册表动态查找对应类，不再依赖字符串分支。

**复杂度**：⭐⭐⭐ 高  
**影响范围**：`sync_executor.py`、`scheduler.py`、`step_config.py`

---

#### 4. 删除 `structural_screening/` 旧代码

**问题**  
`structural_screening/` 目录下保留了旧版脚本（parser、screener、aggregator），与 `core/executors/` 下的现役代码存在功能重叠，两套逻辑并存导致认知混乱。修 bug 时可能只改了一套，另一套悄悄残留旧行为。

**操作**
- 确认 `structural_screening/scripts/` 下所有功能已被 `core/executors/` 覆盖
- 删除 `structural_screening/01_reference_parsing/`、`structural_screening/scripts/`
- 保留 `structural_screening/02_screening_ai/prompts/`（prompt 文件仍被引用）

**复杂度**：⭐ 低  
**影响范围**：`structural_screening/`、确认无其他 import

---

#### 5. 前端重构：`index.html` → Vite + Vue3 SFC

**问题**  
当前所有前端代码（2900 行、190KB）集中在单个 `frontend/index.html`，使用 CDN Vue 无构建工具。随着复筛、Meta 分析等功能加入，代码量将翻倍，无法拆分组件、无法复用逻辑、无法进行类型检查。

**目标结构**
```
frontend/
  index.html            ← Vite 入口（仅挂载点）
  src/
    main.js
    App.vue
    router/
      index.js          ← Vue Router（各阶段作为路由 view）
    stores/
      auth.js           ← Pinia：用户/登录态
      project.js        ← Pinia：当前项目、阶段数据
      task.js           ← Pinia：任务状态、轮询
    composables/
      useApi.js         ← apiRequest / fetchWithTimeout
      useTask.js        ← pollParsingStatus / pollAiScreenStatus
    views/
      Screen1.vue       ← 初筛主界面
      Screen2.vue       ← 复筛（待开发）
      Meta.vue          ← Meta 分析（待开发）
    components/
      LoginModal.vue
      ProjectList.vue
      StageNav.vue
      ProgressBar.vue
      TaskLogPanel.vue
      FileUploader.vue
      DeduplicationPanel.vue
      AiScreenPanel.vue
      ExportPanel.vue
      CriteriaPanel.vue
```

**迁移策略（渐进式，降低风险）**
1. 搭 Vite 框架，`index.html` 内容原样移入 `App.vue`，验证功能等价
2. 抽 composables（useApi、useTask、useProject），不改模板
3. 逐步拆组件，每拆一个组件验证一次
4. 开发复筛时直接用 SFC 新建 `Screen2.vue`

**后端配套改动**
- `settings.py` 的 `TEMPLATES` 改为 serve Vite 构建产物 `dist/index.html`
- 开发时配置 Vite proxy 转发 `/api/` 到 Django（解决 CSRF 跨域问题）
- `CORS_ALLOWED_ORIGINS` 增加 `http://localhost:5173`

**复杂度**：⭐⭐⭐⭐ 很高  
**影响范围**：整个 `frontend/`、`settings.py`、`platform_backend/urls.py`

---

### 🟡 P2 — 中期处理

#### 6. `workspaces/` 文件清理机制

**问题**  
每次执行 parse 步骤都生成新的 `parse_<timestamp>/` 目录，并将完整 input 文件复制进去。当前已有 8+ 个 parse 目录，每个都包含 600KB+ 的 input 副本，且没有任何清理策略，磁盘空间无限膨胀。

**方案**
- 在 `BaseExecutor` 或 `scheduler.py` 中增加旧工作区清理逻辑：每个项目每个步骤最多保留最近 N 个（建议 3 个）工作区
- input 文件改为软链接或只记录原始文件路径，不复制
- 提供 management command `python manage.py cleanup_workspaces --keep 3`

**复杂度**：⭐⭐ 中

---

#### 7. 任务进度信息与 `Task.config` 解耦

**问题**  
运行时进度（`parse_progress.current/total/message`）直接写入 `Task.config` JSONField，前端轮询 `/tasks/<id>/` 读取。`config` 本应是任务的输入参数，不应作为运行时状态的传输通道，将来上 WebSocket/SSE 实时推送时需要重写整个进度通道。

**方案**
- 新增 `TaskProgress` 模型（或用 Redis 存临时进度）：`task_id / phase / current / total / message / updated_at`
- 前端轮询改为 `/api/tasks/<id>/progress/`
- 长远：改为 WebSocket 或 SSE 推送，消除轮询

**复杂度**：⭐⭐⭐ 高

---

#### 8. `step_config.py` 与执行器的注册机制

**问题**  
新增一个步骤需要同时修改 `step_config.py`（配置）、`scheduler.py`（分发逻辑）、`sync_executor.py`（执行逻辑）三处，靠字符串匹配关联，容易漏改，没有编译期检查。

**方案**  
改为注册表模式，每个步骤 executor 自声明配置：

```python
# core/executors/steps/parse_executor.py
class ParseExecutor(BaseExecutor):
    step_key = "parse"
    name = "导入文献索引"
    execution_mode = "threaded"
    stage_key = "SCREEN_1"
    ...
```

`scheduler.py` 通过注册表 `EXECUTOR_REGISTRY = {cls.step_key: cls for cls in all_executors}` 动态查找，不再有字符串分支。

**复杂度**：⭐⭐⭐ 高

---

### 🟢 P3 — 低优先级（清理/规范类）

#### 9. 删除未启用的权限模型

**问题**  
`models.py` 中的 `Permission`、`UserPermission`、`RoleTemplate` 三张表已建库但无业务代码使用，是过度设计留下的死代码，增加理解成本。

**操作**：确认无引用后删除模型类，生成迁移删除对应数据表。

**复杂度**：⭐ 低

---

#### 10. 补充自动化测试

**问题**  
`core/tests.py` 几乎为空，关键链路（文献解析、去重、AI 初筛、断点续传）全靠手动验证，每次重构都有隐患。

**目标覆盖范围**
```
core/tests/
  test_parse.py         ← 各格式文件解析正确性
  test_dedup.py         ← 去重逻辑
  test_scheduler.py     ← 任务启动/停止/恢复
  test_checkpoint.py    ← 断点续传
  test_export.py        ← Excel/RIS 导出字段正确性
  test_api.py           ← API 接口契约测试
```

**复杂度**：⭐⭐⭐ 高

---

#### 11. API 文档

**问题**：无接口文档，前端/外部开发者只能读源码猜字段。

**方案**：接入 `drf-spectacular` 自动生成 OpenAPI 文档，挂载 `/api/docs/` Swagger UI。

**复杂度**：⭐ 低

---

## 推荐执行顺序

```
① P0-1  环境配置与密钥管理          （安全基础，立刻做）
    ↓
② P1-4  删除 structural_screening 旧代码  （清理干扰，成本低）
    ↓
③ P1-2  views.py 拆分               （稳定 API 层）
    ↓
④ P1-3  sync_executor.py 拆分       （稳定执行层，配合注册机制）
    ↓
⑤ P2-6  workspaces 清理机制         （避免磁盘问题）
    ↓
⑥ P1-5  前端重构（Vite + Vue3 SFC）  （后端稳定后前端不再大改）
    ↓
⑦ P2-7  进度信息解耦（TaskProgress） （配合前端重构一起做）
    ↓
⑧ P3    测试 / 文档 / 死代码清理     （持续补充）
```

> ⑤ 前端重构放在后端结构稳定之后，避免前端组件的 API 调用逻辑因后端重构而二次修改。

---

## 各阶段新功能开发建议

| 功能 | 建议在重构哪步完成后再开发 |
|------|--------------------------|
| 文献复筛（SCREEN_2） | ④ executor 拆分完成后 |
| 质量评价（QUALITY） | ⑥ 前端重构完成后（直接用 SFC 开发新 view） |
| Meta 分析（META） | ⑦ 进度解耦完成后（Meta 分析耗时长，需要实时进度） |
