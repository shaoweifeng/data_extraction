# AI 初筛模块代码地图

> 整理时间：2026-04-25  
> 仓库：https://github.com/shaoweifeng/data_extraction.git

---

## 目录

1. [整体流程概览](#整体流程概览)
2. [前端（index.html）](#前端indexhtml)
3. [后端 API 入口](#后端-api-入口)
4. [任务调度层](#任务调度层)
5. [Celery 任务封装](#celery-任务封装)
6. [异步执行器（核心）](#异步执行器核心)
7. [AI Provider 层](#ai-provider-层)
8. [数据模型](#数据模型)
9. [步骤配置](#步骤配置)
10. [断点续传机制](#断点续传机制)
11. [日志系统](#日志系统)
12. [API 路由汇总](#api-路由汇总)
13. [环境变量配置](#环境变量配置)
14. [已知 Bug 修复记录](#已知-bug-修复记录)

---

## 整体流程概览

```
前端点击"启动 AI 筛选任务"
    ↓
POST /api/tasks/  { task_type: 'ai_screening', config: { criteria: [...] } }
    ↓
core/views.py  TaskViewSet.perform_create()
    ↓  task_type_map 映射: 'ai_screening' → 'ai_screen'
core/scheduler.py  TaskScheduler.start_step('ai_screen', ...)
    ↓  step_config 判断 execution_mode = 'async'
    ↓  创建 Task 记录（status=pending），将 criteria 存入 task.config
TaskScheduler._execute_async()
    ↓  execute_async_step.delay(task_id, step_key, project_id)
core/executors/celery_tasks.py  execute_async_step（Celery Worker）
    ↓  读取 task.config，创建 AsyncExecutor
    ↓  executor.initialize() → executor.execute() → executor.finalize()
core/executors/async_executor.py  AsyncExecutor._execute_ai_screen()
    ↓  加载断点 → 批次处理 → 调用 AI API → 保存结果 → 更新进度
core/executors/ai_providers/deepseek.py  DeepSeekProvider.screen_batch()
    ↓  调用 DeepSeek API（OpenAI 兼容格式）
结果写入 DataFile（data_category='output'，description='AI筛选结果'）
    ↓
前端每 2 秒轮询 GET /api/tasks/{id}/ + GET /api/tasks/{id}/logs/
    ↓  每 5 次轮询刷新左侧文件列表
    ↓  任务完成后加载 screenedFiles
```

---

## 前端（index.html）

**文件路径：** `frontend/index.html`

### Vue 响应式变量

| 变量名 | 位置（行号） | 作用 |
|--------|-------------|------|
| `pendingFiles` | L814 | 待筛选文献列表（dedup/parse 的 intermediate 输出） |
| `screenedFiles` | L815 | 已筛选文献列表（ai_screen 的 output 输出） |
| `latestTask` | L818 | 当前最新任务对象 |
| `isProcessing` | L819 | 任务是否在运行中（控制按钮状态） |
| `aiScreenLogContent` | L821 | 控制台日志内容 |
| `criteriaList` | L823 | 纳排标准列表 |
| `screeningProgressValue` | L825 | 进度条百分比 |
| `processedCount` | L822 | 已处理文献数 |
| `screeningResults` | L820 | 任务完成后的汇总结果（纳入/排除/总计） |

### 核心函数

| 函数名 | 位置（行号） | 作用 |
|--------|-------------|------|
| `startScreening` | L1712 | 点击"启动 AI 筛选任务"，POST 创建任务，启动轮询 |
| `pollAiScreeningStatus` | L1543 | 每 2 秒轮询任务状态+日志，每 5 次刷新文件列表 |
| `loadAiScreenFiles` | L1490 | 加载待筛选文献（优先 dedup，fallback 到 parse） |
| `loadScreenedFiles` | L1518 | 加载已筛选文献（ai_screen step 的 output 文件） |
| `stopScreeningTask` | L1638 | 暂停任务，POST /api/tasks/{id}/stop/ |
| `resumeScreeningTask` | L1663 | 继续任务（断点续传），POST /api/tasks/{id}/resume/ |
| `abandonScreeningTask` | L1690 | 放弃任务，DELETE /api/tasks/{id}/ |

### 关键 UI 区域（行号）

| 区域 | 行号 | 说明 |
|------|------|------|
| 待筛选/已筛选文件列表 | L445–L507 | 左侧双 tab，每页 50 条分页 |
| 控制台日志区域 | L513–L517 | 显示 `aiScreenLogContent` |
| 进度条 | L520–L530 | 显示 `screeningProgressValue` |
| 操作按钮区 | L533–L566 | 根据任务状态切换：启动/暂停/继续/放弃 |
| 任务列表侧边栏 | L601–L661 | 右侧最近任务面板 |

### 前端请求示例

```js
// 启动筛选（frontend/index.html L1722-L1728）
POST /api/tasks/
{
    "project": <project_id>,
    "task_type": "ai_screening",
    "config": { "criteria": ["排除非英文文献", "..."] }
}

// 轮询状态（L1550）
GET /api/tasks/{taskId}/

// 获取日志（L1563）
GET /api/tasks/{taskId}/logs/

// 加载待筛选文件（L1499）
GET /api/files/?project={id}&step={dedup_step_id}&data_category=intermediate&limit=1000

// 加载已筛选文件（L1528）
GET /api/files/?project={id}&step={ai_screen_step_id}&data_category=output&limit=1000
```

---

## 后端 API 入口

**文件路径：** `core/views.py`  
**类名：** `TaskViewSet`（L825）

### `perform_create`（L845）

处理 `POST /api/tasks/` 请求：

1. 检查用户权限（`task.start`）
2. `task_type_map` 映射前端类型到内部 `step_key`：
   - `'ai_screening'` → `'ai_screen'`
3. 调用 `TaskScheduler(project_id).start_step(step_key, user.id, **config)`

### 其他 Action

| Action | 方法 | URL | 位置 |
|--------|------|-----|------|
| `stop` | POST | `/api/tasks/{id}/stop/` | L907 |
| `resume` | POST | `/api/tasks/{id}/resume/` | L931 |
| `logs` | GET | `/api/tasks/{id}/logs/` | L965 |
| `progress` | GET | `/api/tasks/{id}/progress/` | L957 |

**`logs` 接口逻辑（L965-L987）：**
- 优先读取 `task.log_file` 字段指向的物理日志文件（最后 200 行）
- fallback：返回 `task.logs` 文本字段

---

## 任务调度层

**文件路径：** `core/scheduler.py`  
**类名：** `TaskScheduler`（L53）

### `start_step`（L103）

```python
# 创建 Task 记录，将 criteria 等参数存入 task.config
task = Task.objects.create(
    project=self.project,
    task_type='ai_screen',
    status='pending',
    config=kwargs          # kwargs = { 'criteria': [...] }
)
# execution_mode='async' → 走 Celery
self._execute_async(task, step_key)
```

### `_execute_async`（L162）

```python
result = execute_async_step.delay(task_id, step_key, project_id)
task.celery_task_id = result.id
task.status = 'running'
task.save()
```

### `resume_task`（L200+）

断点续传：读取旧任务的 checkpoint 路径，存入新任务的 `config.resume_checkpoint_path`。

---

## Celery 任务封装

**文件路径：** `core/executors/celery_tasks.py`  
**函数名：** `execute_async_step`（L29）

```python
@shared_task(bind=True, max_retries=3)
def execute_async_step(self, task_id, step_key, project_id):
    task_obj = Task.objects.get(id=task_id)
    task_config = task_obj.config or {}

    executor = AsyncExecutor(task_id, step_key, project_id)
    executor.config.update(task_config)   # ← 合并 criteria 等配置

    executor.initialize()
    success = executor.execute()
    executor.finalize(success)
```

> **Bug 修复记录：** 原代码 `AsyncExecutor(..., config=task_config)` 传递了 `BaseExecutor.__init__` 不接受的 `config` 参数，导致 `TypeError`，任务根本无法启动。已修复为先创建实例，再 `executor.config.update(task_config)`。

---

## 异步执行器（核心）

**文件路径：** `core/executors/async_executor.py`  
**类名：** `AsyncExecutor`（L33）

### 主流程 `_execute_ai_screen`（L70）

```
1. _get_input_files()        → 从 dedup/parse 步骤读取待筛选 XML 文件列表
2. _get_criteria()           → 从 task.config > criteria_step > stage.metadata 依次读取纳排标准
3. 加载断点                  → self.load_checkpoint()（从 checkpoint.json 读取 processed_sources）
4. 清除旧的 output 文件      → 避免历史结果累加显示
5. 过滤已处理文献            → source_xml in processed_sources 则跳过
6. 批次循环处理              → 每批 10 篇，最多 5 并发
   ├── check_stop_signal()  → 检查 {step_key}.STOP 文件，发现则保存断点并退出
   ├── _process_batch()     → 调用 AI API
   ├── _save_result()       → 结果写入 workspace/screening_ai/results/
   ├── _save_batch_results_to_db() → 实时写入 DataFile 表，前端可查看
   └── save_checkpoint()    → 每 50 篇保存断点
7. _save_all_results()       → 兜底，将 workspace 结果批量同步到 DB
8. 更新 StageStep.metadata   → total_refs / included_refs / excluded_refs
```

### 关键方法

| 方法 | 行号 | 说明 |
|------|------|------|
| `_execute_ai_screen` | L70 | 主流程 |
| `_get_input_files` | L484 | 获取待筛选 XML：优先 dedup intermediate，fallback 到 parse |
| `_get_criteria` | L528 | 读取纳排标准（4 级 fallback） |
| `_process_batch` | L267 | 处理一批文献，调用 `_call_ai_api` |
| `_call_ai_api` | L311 | 调用真实 AI API（无 `AI_API_KEY` 时 fallback mock） |
| `_mock_api_call` | L361 | 模拟 AI 调用（随机结果，用于测试） |
| `_save_batch_results_to_db` | L408 | 每批完成后实时写 DataFile |
| `_save_result` | L388 | 单个结果写入 workspace 文件 |
| `_save_all_results` | L447 | 全部结果兜底写入 DB |
| `_send_heartbeat` | L55 | 每 5 批更新 Task.metadata，防止前端误判卡死 |
| `_get_prompt_template` | L297 | 读取 `structural_screening/02_screening_ai/prompts/prompt1.txt` |

### 工作区目录结构

```
workspaces/project_{project_id}/
└── ai_screen_{timestamp}/
    ├── logs/
    │   ├── task.log          ← 日志文件（TaskLogger 写入）
    │   ├── progress.json     ← 实时进度（current/total/percentage）
    │   └── checkpoint.json   ← 断点文件（processed_sources 列表）
    └── screening_ai/
        ├── datasets/
        └── results/
            └── {safe_title}/
                └── screening_result_{source_xml}.json
```

---

## AI Provider 层

**目录：** `core/executors/ai_providers/`

### 文件列表

| 文件 | 说明 |
|------|------|
| `__init__.py` | 工厂函数 `get_provider(name, config)`，默认 `deepseek` |
| `base.py` | 抽象基类 `BaseAIProvider`，数据类 `ScreeningResult` |
| `deepseek.py` | `DeepSeekProvider`，OpenAI 兼容格式调用 DeepSeek API |

### `ScreeningResult` 字段（base.py L14）

```python
@dataclass
class ScreeningResult:
    title: str
    decision: str               # "included" | "excluded" | "error"
    exclusion_reason: str       # 排除理由
    exclusion_criterion_no: str # 违反的标准编号（如 "3"）
    model: str                  # 模型名称
    raw_response: str           # 原始 AI 响应
    confidence: float           # 预留，当前不输出
    error: str                  # 出错信息
```

### `DeepSeekProvider`（deepseek.py L26）

- 每次调用构建：`Title + Abstract（截断500字） + 纳排标准 → prompt`
- 调用 `POST {AI_API_URL}/v1/chat/completions`
- 解析返回 JSON，提取 `exclusion_reason`、`include_or_not`、`number_exclusion_reason`

### 扩展新模型

1. 新建 `core/executors/ai_providers/xxx.py`，继承 `BaseAIProvider`，实现 `screen_single()`
2. 在 `__init__.py` 的 `registry` 注册
3. 设置环境变量 `AI_PROVIDER=xxx`

---

## 数据模型

**文件路径：** `core/models.py`

### `Task` 模型（L353）

| 字段 | 类型 | 说明 |
|------|------|------|
| `task_type` | CharField | `ai_screen` |
| `status` | CharField | `pending/running/completed/failed/stopped` |
| `progress` | FloatField | 0-1 进度值 |
| `config` | JSONField | 存储 `criteria`、`resume_checkpoint_path` 等 |
| `log_file` | CharField | 日志文件绝对路径 |
| `logs` | TextField | fallback 纯文本日志 |
| `celery_task_id` | CharField | Celery 任务 UUID |
| `metadata` | JSONField（通过 heartbeat 写入） | `processed_refs/total_refs` |

### `DataFile` 模型（L274）

AI 筛选结果写入字段：

| 字段 | 值 |
|------|-----|
| `data_category` | `'output'` |
| `description` | `'AI筛选结果'` |
| `metadata` | `{'decision': 'included' | 'excluded'}` |
| `step` | `ai_screen` 步骤对象 |

### `StageStep` 元数据（完成后写入）

```json
{
    "total_refs": 495,
    "processed_refs": 495,
    "included_refs": 210,
    "excluded_refs": 285,
    "error_refs": 0,
    "criteria_count": 5
}
```

---

## 步骤配置

**文件路径：** `core/step_config.py`（L161）

```python
"ai_screen": {
    "name": "AI初筛",
    "stage_key": "SCREEN_1",
    "execution_mode": "async",      # ← 决定走 Celery
    "timeout": 7200,                # 2小时超时
    "batch_size": 10,               # 每批10篇
    "concurrency": 5,               # 最多5并发
    "resume_capability": True,      # 支持断点续传
    "checkpoint_interval": 50,      # 每50篇保存断点
    "retry_policy": {
        "max_retries": 3,
        "retry_delay": 10,
        "retry_on": ["timeout", "rate_limit", "api_error", "network_error"]
    }
}
```

---

## 断点续传机制

### 保存断点

**位置：** `core/executors/base.py` `BaseExecutor.save_checkpoint()`（L501）

```python
def save_checkpoint(self, data):
    self.logger._save_checkpoint(data)        # 写 checkpoint.json
    self.logger.add_checkpoint("manual_checkpoint", data)  # 写 progress.json
```

触发时机：
- 用户点击"暂停"（收到 STOP 信号，`async_executor.py` L193）
- 每处理 50 篇自动保存（L228）

### 加载断点

**位置：** `BaseExecutor.load_checkpoint()`（L508）→ 读 `checkpoint.json`

断点内容：
```json
{
    "processed_sources": ["file1.xml", "file2.xml", ...],
    "progress": { "current": 40, "total": 495 }
}
```

### 跨任务续传

`scheduler.resume_task()` 将旧任务的 `checkpoint.json` 路径写入新任务的 `config.resume_checkpoint_path`，`_execute_ai_screen` 优先从此路径加载。

> **Bug 修复记录：** 原 `save_checkpoint` 只调用 `logger.add_checkpoint()`，数据写入 `progress.json`；而 `load_checkpoint` 从 `checkpoint.json` 读取，两个不同文件导致 `processed_sources` 永远为空。修复：同时调用 `logger._save_checkpoint()` 写入 `checkpoint.json`。

---

## 日志系统

**文件路径：** `core/executors/base.py` `TaskLogger` 类

### 日志写入

- 物理文件：`workspaces/project_{id}/ai_screen_{timestamp}/logs/task.log`
- 路径存入 `Task.log_file`（`initialize()` 时写入）

### 前端读取日志

`GET /api/tasks/{id}/logs/` → `TaskViewSet.logs()`（`views.py` L965）：
- 读取 `task.log_file` 文件的**最后 200 行**
- fallback：返回 `task.logs` 字段

---

## API 路由汇总

**路由文件：** `core/urls.py`

| HTTP方法 | URL | 说明 |
|----------|-----|------|
| POST | `/api/tasks/` | 创建并启动 AI 初筛任务 |
| GET | `/api/tasks/{id}/` | 获取任务状态（含 progress_percentage） |
| GET | `/api/tasks/{id}/logs/` | 获取任务日志（最后200行） |
| GET | `/api/tasks/{id}/progress/` | 获取详细进度 |
| POST | `/api/tasks/{id}/stop/` | 暂停任务 |
| POST | `/api/tasks/{id}/resume/` | 继续任务（断点续传） |
| DELETE | `/api/tasks/{id}/` | 放弃任务 |
| GET | `/api/files/` | 查询文件列表（`?step=&data_category=&limit=`） |
| GET | `/api/tasks/?project={id}` | 获取项目任务列表 |

---

## 环境变量配置

| 变量名 | 必填 | 默认值 | 说明 |
|--------|------|--------|------|
| `AI_API_KEY` | ✅ | — | AI API 密钥（未配置时 fallback mock） |
| `AI_API_URL` | ❌ | `https://api.deepseek.com/v1` | API 接口地址 |
| `AI_MODEL` | ❌ | `deepseek-chat` | 模型名称 |
| `AI_TIMEOUT` | ❌ | `120` | 单次请求超时秒数 |
| `AI_PROVIDER` | ❌ | `deepseek` | Provider 名称（扩展多模型时使用） |

配置方式（在 Django 启动环境中设置）：
```bash
export AI_API_KEY="sk-xxxx"
export AI_API_URL="https://api.deepseek.com/v1"
export AI_MODEL="deepseek-chat"
```

---

## 已知 Bug 修复记录

### Bug 1：任务无法启动（TypeError）

- **现象：** 点击"启动 AI 筛选任务"后控制台无日志，左侧文件列表不更新
- **根因：** `celery_tasks.py` L64 `AsyncExecutor(..., config=task_config)` 传了 `BaseExecutor.__init__` 不接受的参数
- **修复：** `core/executors/celery_tasks.py` — 先创建实例，再 `executor.config.update(task_config)`

### Bug 2：断点续传不生效（processed_sources 为空）

- **现象：** 日志显示"检测到断点，已处理 40 篇"，但仍从第 1 篇开始处理
- **根因：** `save_checkpoint` 写入 `progress.json`，`load_checkpoint` 读取 `checkpoint.json`，文件不同导致 `processed_sources` 永远是空列表 `[]`
- **修复：** `core/executors/base.py` `BaseExecutor.save_checkpoint()` — 同时调用 `logger._save_checkpoint(data)` 写入 `checkpoint.json`
