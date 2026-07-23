# 项目架构演进方案

> 文档创建时间：2026-04-18  
> 适用范围：当前分支 / 当前代码结构  
> 目标：在不推翻现有 `Django + Celery + 工作区文件` 方案的前提下，为后续多个大功能扩展建立稳定骨架

---

## 1. 背景

当前项目已经完成 AI 初筛这一条核心链路，但从代码组织上看，系统仍处于“第一个大功能驱动出的可用结构”阶段：

- 后端 API、调度、执行、日志、文件管理耦合较高
- 运行态元数据分散在数据库字段和本地文件之间
- 步骤能力以字符串分支驱动，新增能力需要同时改多个入口
- 前端仍是单文件页面，难以承载第二个、第三个复杂模块

如果后续继续增加复筛、质量评价、Meta 分析、报告生成、人工复核等能力，而不先整理骨架，后面一定会进入“每加一个功能都要改一串共享代码”的状态，最终触发一次代价更高的大重构。

本方案的目标不是立刻重写，而是做一次中等规模、可渐进推进的架构整理。

---

## 2. 架构判断

### 2.1 当前可以保留的部分

- 技术栈方向是对的：`Django + DRF + Celery + MySQL + 本地工作区文件`
- 任务调度与执行分离的方向是对的
- `Project / Stage / Step / Task / DataFile` 这套基本实体有继续演进的基础
- 以步骤为单位编排科研流程的方向是对的

### 2.2 当前最需要收敛的问题

- `core/views.py` 职责过重，继续扩功能会越来越难维护
- `sync_executor.py` / `async_executor.py` 逐渐成为“大型步骤容器”
- 任务运行态缺少单一事实来源，状态落在多个位置
- 文件系统与数据库各自存了一部分元数据，边界不清晰
- 前端 `frontend/index.html` 继续增长会直接拖慢后续功能开发

---

## 3. 演进目标

未来架构整理的核心目标有 5 个：

1. **新增一个步骤或能力时，主要是新增模块，而不是修改多个巨型文件**
2. **任务运行态、步骤摘要、产物记录各自有明确职责**
3. **前后端对任务状态、进度、日志、结果的理解保持一致**
4. **文件系统只负责大文件和中间产物，结构化状态尽量归一**
5. **允许未来继续扩展 SCREEN_2、QUALITY、META，而不触发二次大改**

---

## 4. 设计原则

### 4.1 单一事实来源

同一类信息只应有一个主存储位置：

- 任务运行状态以 `Task` 为主
- 步骤业务摘要以 `StageStep.metadata` 为主
- 产物信息以 `DataFile` 为主
- 大日志和大中间文件保存在工作区
- checkpoint 作为恢复机制，可以先保留文件方案，但其职责要明确

### 4.2 调度与业务分离

- `scheduler` 只负责启动、停止、恢复、状态编排
- 每个步骤的业务逻辑由独立 handler/executor 负责
- `views` 只做 API 输入输出，不直接承载复杂业务

### 4.3 模块增量式扩展

新增一个步骤时，理想操作应接近：

- 新增一个 handler 文件
- 注册到步骤注册表
- 补一份步骤配置
- 前端新增一个对应模块

而不是继续改 `views.py`、`scheduler.py`、`sync_executor.py`、`index.html` 四五个大文件。

### 4.4 工作区是执行介质，不是主业务模型

工作区目录可以继续保留，但职责应收敛为：

- 保存任务日志
- 保存进度文件
- 保存 checkpoint
- 保存大体积中间产物和导出文件

不应让业务核心状态过度依赖工作区文件存在与否。

---

## 5. 目标结构

### 5.1 后端目录结构

建议在保持 `core/` 单应用前提下，逐步整理为：

```text
core/
  api/
    __init__.py
    project_views.py
    stage_views.py
    step_views.py
    task_views.py
    file_views.py
    prompt_views.py
    user_views.py
    activity_log_views.py

  services/
    __init__.py
    project_service.py
    task_service.py
    artifact_service.py
    prompt_service.py
    progress_service.py

  executors/
    __init__.py
    base.py
    registry.py
    sync_base.py
    async_base.py
    handlers/
      __init__.py
      parse_handler.py
      dedup_handler.py
      criteria_handler.py
      field_extraction_handler.py
      ai_screen_handler.py
      export_handler.py
    ai_providers/
      __init__.py
      base.py
      deepseek.py

  domain/
    __init__.py
    task_state.py
    artifact_types.py
    step_types.py

  models.py
  serializers.py
  scheduler.py
  monitoring.py
  step_config.py
```

说明：

- `api/` 负责对外接口
- `services/` 负责可复用业务逻辑
- `executors/handlers/` 负责步骤执行逻辑
- `domain/` 放状态枚举、类型定义、通用常量
- `scheduler.py` 逐步缩小为“任务编排器”

### 5.2 前端目录结构

短期不强制迁移技术栈，但建议先形成模块结构：

```text
frontend/
  index.html
  js/
    api/
      http.js
      project.js
      task.js
      file.js
      prompt.js
    state/
      auth.js
      project.js
      screening.js
      task.js
    modules/
      screening/
        project-panel.js
        criteria-panel.js
        dedup-panel.js
        ai-screen-panel.js
        export-panel.js
      common/
        task-log-panel.js
        progress-bar.js
        modal.js
```

如果后续确认前端功能继续快速增长，再迁到 `Vite + Vue SFC`。

---

## 6. 核心职责边界

### 6.1 `Task`

`Task` 应只承担任务运行态：

- 当前状态：`pending/running/completed/failed/stopped/...`
- 进度数值
- 当前错误
- 启动配置
- 结果摘要
- 关联日志路径
- 关联执行器信息

不建议继续把过多“步骤业务摘要”写进 `Task.config` 或临时塞入额外字段。

### 6.2 `StageStep.metadata`

`StageStep.metadata` 应只承担步骤级摘要，适合存：

- 去重统计汇总
- 纳排标准列表
- 字段定义列表
- AI 初筛最终总数、纳入数、排除数
- 导出结果汇总

不适合长期承载高频运行态信息。

### 6.3 `DataFile`

`DataFile` 是统一产物记录入口，建议继续强化：

- 输入文件
- 中间文件
- 输出文件
- 文件来源任务
- 文件类型
- 文件业务标签
- 文件元数据摘要

未来如果能力变多，建议显式引入 `artifact_type` 或更强的分类体系，而不是继续依赖松散 `description + metadata`。

### 6.4 工作区文件

工作区保留这些内容：

- `task_*.log`
- `progress_*.json`
- `checkpoint.json`
- 运行过程中的临时数据
- 体积较大的结果文件

工作区不应成为前端判断主要业务状态的唯一依据。

---

## 7. 步骤执行模型改造

### 7.1 当前问题

当前新增步骤通常需要同时改：

- `step_config.py`
- `scheduler.py`
- `sync_executor.py` 或 `async_executor.py`
- 前端页面逻辑

这会导致功能越多，公共入口越脆弱。

### 7.2 目标模型

将步骤实现改成 handler 注册式结构。

示例：

```python
class BaseStepHandler:
    step_key = ""
    stage_key = ""
    execution_mode = "sync"

    def validate_inputs(self):
        ...

    def execute(self):
        ...

    def stop(self):
        ...

    def resume(self):
        ...

    def summarize(self):
        ...
```

具体步骤示例：

```python
class AIScreenHandler(BaseStepHandler):
    step_key = "ai_screen"
    stage_key = "SCREEN_1"
    execution_mode = "async"
```

### 7.3 注册表机制

建议增加统一注册表：

```python
STEP_HANDLER_REGISTRY = {
    "parse": ParseHandler,
    "dedup": DedupHandler,
    "criteria": CriteriaHandler,
    "field_extraction": FieldExtractionHandler,
    "ai_screen": AIScreenHandler,
    "export": ExportHandler,
}
```

这样 `scheduler` 不再关心步骤内部细节，只做：

- 根据 `step_key` 找 handler
- 创建任务
- 分发到同步或异步执行
- 处理停止和恢复入口

---

## 8. 任务状态与进度通道整理

### 8.1 当前问题

当前任务相关信息分散在：

- `Task.progress`
- `Task.logs`
- `Task.config`
- `Task.result`
- `StageStep.metadata`
- `progress.json`
- `checkpoint.json`

前端如果不看源码，很难知道该信哪个字段。

### 8.2 建议方案

建议定义一套稳定的任务返回契约：

#### 任务主对象

- `id`
- `project`
- `step_key`
- `status`
- `progress`
- `started_at`
- `completed_at`
- `error_message`
- `result_summary`
- `log_ref`

#### 任务进度接口

- 当前计数
- 总数
- 百分比
- 当前阶段说明
- 最后更新时间

#### 任务日志接口

- 日志内容分页或 tail
- 日志来源文件路径

#### 任务结果接口

- 最终统计
- 相关产物列表

### 8.3 过渡策略

短期内不一定新增模型，但要先统一约定：

- `Task.config` 只存输入配置
- `Task.progress` 只存进度
- `Task.result` 只存结果摘要
- `Task.logs` 只作为日志内容缓存或日志元信息，不要反复切换语义

如果后续任务种类明显增多，再考虑新增 `TaskProgress` / `TaskEvent` 等专用结构。

---

## 9. 产物模型演进建议

### 9.1 当前问题

现在很多业务语义靠：

- `data_category`
- `description`
- `metadata`

组合出来，短期灵活，长期容易失控。

### 9.2 建议增强方向

在不立刻大改表结构的前提下，先建立统一约定：

- `source`: `upload/tool_generated/imported`
- `data_category`: `input/intermediate/output`
- `metadata.artifact_type`: 例如 `parsed_xml/dedup_report/ai_screen_result/export_excel/export_ris`
- `metadata.source_task_id`
- `metadata.source_step_key`
- `metadata.business_tag`

未来如果能力明显增多，再考虑显式新增 `artifact_type` 字段。

---

## 10. 前端演进建议

### 10.1 当前问题

`frontend/index.html` 同时承担：

- 页面模板
- 响应式状态
- API 请求
- 任务轮询
- 业务判断
- 多步骤 UI

这对第一个大功能还能接受，但不适合继续扩模块。

### 10.2 短期方案

先不强行迁移到 Vite，先完成职责拆分：

- `http.js`：统一请求和超时处理
- `task.js`：任务启动/停止/恢复/轮询
- `screening.js`：文献初筛模块状态
- `project.js`：项目与阶段状态
- `components`：日志面板、进度条、上传器、结果列表

### 10.3 中期方案

在第二个大功能正式开发前，迁移到：

- Vue 3 SFC
- Vite
- 路由化页面
- Pinia 状态管理

这一步建议在后端任务接口稳定后再做，避免前后端同时大改。

---

## 11. 分阶段实施计划

### 阶段 A：2 周内，先做骨架收口

目标：不改业务能力，只整理结构。

范围：

- 拆分 `core/views.py`
- 抽出 `services/`
- 明确 `Task / StageStep.metadata / DataFile / 工作区文件` 职责边界
- 统一任务接口返回契约
- 修正前后端对任务字段的偏差

交付标准：

- 新功能不再必须进 `views.py`
- 前端不再直接猜任务对象字段

### 阶段 B：2 到 4 周，步骤执行插件化

目标：让新增步骤主要通过注册和新增 handler 完成。

范围：

- 建立 handler 注册表
- 将 `parse/dedup/ai_screen/export` 拆为独立 handler
- 收缩 `scheduler.py`
- 收缩 `sync_executor.py` / `async_executor.py`

交付标准：

- 新增步骤不再修改大分支文件

### 阶段 C：2 到 4 周，前端模块化

目标：为后续多个业务页面铺路。

范围：

- 抽 API 层
- 抽任务轮询层
- 抽文献初筛模块
- 拆 UI 组件

交付标准：

- 第二个大功能可以作为独立模块接入

### 阶段 D：按需推进，增强可观测性与可靠性

范围：

- 任务监控页
- checkpoint 持久化增强
- 工作区清理策略
- 自动化测试补齐
- API 文档整理

---

## 12. 推荐优先级

### P0：现在就值得排期

- `views.py` 拆分
- 任务状态职责统一
- 步骤 handler 注册机制设计
- 前端 API / 任务轮询模块化

### P1：后续大功能开发前完成

- 旧执行器瘦身
- 产物分类约定统一
- 前端迁移到组件化结构

### P2：功能继续增长后再做

- checkpoint 数据库存储
- 更完整的监控和事件流
- 前端完整工程化升级

---

## 13. 不建议现在做的事

- 不建议现在拆成微服务
- 不建议现在推翻现有工作区机制
- 不建议现在大规模重写模型
- 不建议前后端同时做彻底重写

当前最合适的是一次“中等力度、可回退、分阶段”的结构整理。

---

## 14. 最终建议

对于当前项目，我的建议是：

1. 保留现有总体技术路线
2. 立即开始做骨架收口
3. 在第二个大功能正式进入开发前，完成步骤插件化
4. 在第三个复杂功能前，完成前端模块化

一句话总结：

> 当前项目不是“结构错了”，而是“已经到了必须把第一阶段产物整理成可扩展骨架的时候”。

