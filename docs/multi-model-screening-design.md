# 多 AI 交叉验证筛选功能设计文档

> 版本：v1.0  
> 状态：待实现  
> 涉及阶段：AI 初筛（SCREEN_1 → ai_screen）

---

## 一、背景与目标

当前 AI 筛选存在三个核心问题：

| 问题 | 表现 |
|------|------|
| 稳定性差 | 同一篇文献多次筛选可能得到不同结论 |
| 准确率偏低 | 约 20% 误差率 |
| 模型间偏差 | 不同模型对同一文献的判断可能截然相反 |

**目标**：允许用户同时选择多个 AI 模型对全部文献进行筛选，汇总各模型结论，形成一致性共识（`included` / `excluded`）或分歧标记（`conflict`），以大幅提高筛选可信度。

---

## 二、核心逻辑

### 2.1 筛选结果合并规则

```
所有模型均认为"纳入"  →  consensus = included
所有模型均认为"排除"  →  consensus = excluded
模型结论存在分歧       →  consensus = conflict（新状态）
```

### 2.2 conflict 文献处理策略

**当前版本（v1）**：强制进入人工审阅队列，不可直接导出。

**预留扩展点（v2 可选）**：
```python
# core/services/consensus_service.py
CONSENSUS_STRATEGY = "manual"  # "manual" | "majority_vote"

def resolve_consensus(model_results: list[dict]) -> str:
    if CONSENSUS_STRATEGY == "majority_vote":
        included_count = sum(1 for r in model_results if r["decision"] == "included")
        return "included" if included_count > len(model_results) / 2 else "excluded"
    # manual: 任何分歧都记为 conflict
    decisions = {r["decision"] for r in model_results}
    if len(decisions) == 1:
        return decisions.pop()
    return "conflict"
```

### 2.3 积分计算

多模型筛选时，积分按**实际调用次数**累加：

```
总消耗 credits = sum(每个模型各自的 token 消耗折算)
```

预检时也按模型数量乘以单模型预估值：

```
预估消耗 = 单模型预估 × 选中模型数量
```

---

## 三、需要修改的模块

### Phase 1：数据层（0.5 天）

#### 3.1 `core/models.py` — ManualReview 扩展

```python
class ManualReview(models.Model):
    # 新增字段
    multi_model_results = models.JSONField(
        default=list, blank=True,
        verbose_name="多模型筛选结果",
        help_text='[{"model_id": "gpt-4o", "model_name": "GPT-4o", "decision": "included", "reason": "...", "tokens": 1200}, ...]'
    )
    consensus = models.CharField(
        max_length=20,
        choices=[
            ('included',  '一致纳入'),
            ('excluded',  '一致排除'),
            ('conflict',  '存在分歧'),
            ('pending',   '待处理'),
        ],
        default='pending',
        verbose_name="共识结论",
    )
    # ai_decision 字段含义升级：当单模型时 = 该模型决定；多模型时 = consensus 值
    # 字段本身不变，兼容现有代码
```

**新建 migration**。

---

### Phase 2：后端执行层（1.5 天）

#### 3.2 `core/executors/handlers/ai_screen_handler.py` — 核心改造

**改动点 1：读取多模型配置**

```python
# 原
model_id = self.config.get("ai_model") or os.environ.get("AI_PROVIDER", "deepseek")

# 新（向后兼容）
model_ids = self.config.get("ai_models") or []
if not model_ids:
    single = self.config.get("ai_model") or os.environ.get("AI_PROVIDER", "deepseek")
    model_ids = [single]
```

**改动点 2：execute() 主循环 — 多模型并行调用**

```python
# 对每篇文献，依次（或并行）调用各模型
all_model_results = {}  # source_xml -> [{"model_id": ..., "decision": ..., "reason": ..., "tokens": ...}]

for model_id in model_ids:
    provider = get_provider(model_id)
    results = provider.screen_batch(batch, criteria, prompt_template, concurrency=concurrency)
    for entry, result in zip(batch, results):
        all_model_results.setdefault(entry["source_xml"], []).append({
            "model_id": model_id,
            "model_name": get_model_display_name(model_id),
            "decision": "included" if result.is_included else "excluded",
            "reason": result.exclusion_reason or "",
            "tokens": result.token_usage or {},
        })

# 合并共识
for source_xml, model_results in all_model_results.items():
    consensus = resolve_consensus(model_results)
    # 写入 JSON 文件 + ManualReview
```

**改动点 3：_save_result() 写入多模型数据**

```python
# ManualReview 记录写 multi_model_results + consensus
ManualReview.objects.update_or_create(
    project=..., source_xml=...,
    defaults={
        "multi_model_results": model_results,
        "consensus": consensus,
        "ai_decision": consensus,
        "ai_reason": _build_summary_reason(model_results),
    }
)
```

**改动点 4：_save_token_stats() 多模型累加**

```python
# token_stats 按模型分别记录，总量累加
token_stats["by_model"] = {
    model_id: {"tokens": ..., "credits": ...}
    for model_id in model_ids
}
token_stats["total_tokens"] = sum(...)
credits_estimate = sum(v["credits"] for v in token_stats["by_model"].values())
```

#### 3.3 `core/services/consensus_service.py`（新文件）

```python
CONSENSUS_STRATEGY = "manual"  # 预留多数表决扩展点

def resolve_consensus(model_results: list[dict]) -> str:
    ...

def build_summary_reason(model_results: list[dict]) -> str:
    """为 ai_reason 生成多模型摘要，用于人工审阅展示"""
    ...
```

#### 3.4 `core/services/billing_service.py` — 预估乘以模型数

```python
def estimate_credits(ref_count: int, model_count: int = 1) -> int:
    return base_estimate(ref_count) * model_count
```

---

### Phase 3：API 层（0.5 天）

#### 3.5 `core/api/review_views.py` — 接口补充多模型数据

```python
items.append({
    ...
    "consensus":           r.consensus,
    "multi_model_results": r.multi_model_results,  # 前端需要展示各模型判断
    ...
})
```

#### 3.6 `core/api/project_views.py` — 启动任务时传 ai_models 列表

```python
# 接收前端传来的 ai_models 列表，写入 Task.config
config["ai_models"] = request.data.get("ai_models", [config.get("ai_model")])
```

#### 3.7 `core/api/billing_views.py` — estimate 接口支持 model_count 参数

```python
model_count = int(request.GET.get("model_count", 1))
estimated = estimate_credits(ref_count, model_count)
```

---

### Phase 4：前端 StepAiScreen.vue 重构（1.5 天）

#### 4.1 模型选择：从单选改为多选

```
当前：单个 chip 选中（radio 语义）
新版：多个 chip 可同时选中（checkbox 语义），至少选 1 个
```

选中态：紫色勾选图标 + 深色背景  
多选后右侧显示：`已选 3 个模型，预估消耗 ×3`

#### 4.2 整体布局重构

**废弃**：
- 左侧"待筛选 / 已筛选"文献列表（无法以单模型为准，意义不明）
- 右侧日志控制台（文字日志信息密度低，视觉噪音）

**新布局**：

```
┌──────────────────────────────────────────────────────┐
│  顶部栏：标题 + 多模型 chip 选择 + Prompt 折叠        │
├──────────────────────────────────────────────────────┤
│  [进度/状态区]                                        │
│  ┌─────────────────────────────────────────────────┐ │
│  │ 总进度条（每个模型一行，或合并展示）             │ │
│  │ 模型A: ████████████░░░░  72% ✓ 完成            │ │
│  │ 模型B: ████████████░░░░  72% ⟳ 进行中          │ │
│  │ 模型C: ░░░░░░░░░░░░░░░░   0% ⏳ 等待中          │ │
│  └─────────────────────────────────────────────────┘ │
│                                                      │
│  [结果统计区]（有结果时展示）                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐  │
│  │  ✅ 纳入  │ │  ❌ 排除  │ │ ⚠️ 分歧  │ │ ⏳ 待筛 │  │
│  │   142    │ │   356    │ │    28    │ │   74   │  │
│  └──────────┘ └──────────┘ └──────────┘ └────────┘  │
│                                                      │
│  [操作区]                                             │
│  余额栏 | 启动/暂停/继续/重新筛选 按钮                │
└──────────────────────────────────────────────────────┘
```

**单模型时**：进度区只显示 1 行，统计区不显示"分歧"卡片；整体与当前视觉一致，无割裂感。

#### 4.3 结果统计卡片

| 卡片 | 颜色 | 单模型时 | 多模型时 |
|------|------|---------|---------|
| ✅ 纳入 | 绿色 | 显示 | 显示 |
| ❌ 排除 | 红色 | 显示 | 显示 |
| ⚠️ 分歧 | 橙色 | 不显示 | 显示 |
| ⏳ 待筛 | 灰色 | 显示 | 显示 |

#### 4.4 进度展示逻辑

多模型并行时，后端每个模型独立上报进度，前端通过 `task.config.model_progress` 字段读取：

```json
{
  "model_progress": {
    "gpt-4o":    {"current": 200, "total": 500, "status": "running"},
    "deepseek":  {"current": 500, "total": 500, "status": "completed"},
    "qwen-plus": {"current":   0, "total": 500, "status": "waiting"}
  }
}
```

单模型时此字段只有一个 key，逻辑统一。

---

### Phase 5：人工审阅 StepReview.vue 扩展（0.5 天）

#### 3.8 conflict 文献展示

- 顶部 Tab 新增"分歧文献"过滤项，优先展示
- 文献行显示各模型判断图标（如 `✅GPT ❌DeepSeek`）
- conflict 状态以橙色边框 + `⚠️ 分歧` 徽章标识
- 点击文献后的详情区域新增"各模型判断"折叠面板：

```
┌─────────────────────────┐
│ 各模型判断              │
│ GPT-4o      [纳入] ──── │
│ DeepSeek-R1 [排除] ──── │
│   排除理由：...          │
│ Qwen-Plus   [纳入] ──── │
└─────────────────────────┘
```

---

## 四、工作量估算

| 阶段 | 模块 | 工作量 |
|------|------|--------|
| Phase 1 | 数据库模型 + migration | 0.5 天 |
| Phase 2 | ai_screen_handler 核心改造 + consensus_service | 1.5 天 |
| Phase 3 | API 层（review_views / project_views / billing_views） | 0.5 天 |
| Phase 4 | StepAiScreen.vue 整体重构 | 1.5 天 |
| Phase 5 | StepReview.vue conflict 扩展 | 0.5 天 |
| 测试调试 | 单/多模型流程联调 | 1 天 |
| **合计** | | **约 5.5 天** |

---

## 五、执行步骤顺序

```
Step 1  数据库 models.py + migration
Step 2  consensus_service.py（新文件）
Step 3  ai_screen_handler.py 改造（读多模型 → 并行调用 → 合并共识 → 写 DB）
Step 4  billing_service.py + project_views.py + billing_views.py 联动
Step 5  StepAiScreen.vue 重构（多选 chip + 新布局 + 分模型进度 + 统计卡片）
Step 6  StepReview.vue conflict 过滤 + 多模型判断详情
Step 7  联调测试
```

---

## 六、向后兼容说明

- 旧项目（单模型筛选的历史数据）中 `multi_model_results` 为空列表，`consensus` 等于原 `ai_decision`，前端按单模型模式渲染，不影响已有数据
- `ai_models` 配置为空时降级读 `ai_model`，执行器行为与现有完全一致
- 前端多选区"只选 1 个模型"时渲染效果与现在单选完全相同，无割裂感
