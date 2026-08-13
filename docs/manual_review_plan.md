# 人工检查步骤开发方案

> 状态：待确认  
> 位置：AI初筛（order 40）→ **人工检查（order 45）** → 结果归纳（order 50）

---

## 一、功能定位

AI 筛选完成后，研究者在正式导出前对 AI 判断结果进行人工复核，可以覆写任何一篇文献的 included/excluded 决定。最终 Export 步骤以人工覆写结果为准，未覆写的保留 AI 原始判断。

本步骤是**纯交互步骤**，不触发任何后台任务（execution_mode: manual），无需 Celery。

---

## 二、界面设计

参照 ResearchPilot 截图，左右分栏布局：

```
┌────────────────────────────────────────────────────────────────────┐
│  已审 42 / 共 156 篇         [完成人工审阅]  ←── 顶部进度条 + 完成按钮  │
├─────────────────────────┬──────────────────────────────────────────┤
│  🔍 搜索标题              │  标题 / 作者 / 年份 / 期刊 / DOI          │
│  [全部][待审][纳入][排除] │                                          │
│  ─────────────────────  │  Abstract                                │
│  1. 文献标题 A    AI:纳入 │  ────────────────────────────────────── │
│  2. 文献标题 B  ✎ 人工改  │  正文摘要内容...                          │
│  3. 文献标题 C    AI:排除 │                                          │
│  4. 文献标题 D    待审    │  AI 判断：排除  排除理由：不符合纳排标准3    │
│  ...                    │  ────────────────────────────────────── │
│                         │  [ ✓ 纳入 ]  [ ? 待定 ]  [ ✗ 排除 ]      │
│                         │  理由（可选）：___________________________  │
│                         │                              [ 确认 ]    │
└─────────────────────────┴──────────────────────────────────────────┘
```

### 左栏（文献列表）
- Tab 切换：全部 / 待审 / 已纳入 / 已排除（显示各 Tab 数量）
- 搜索框：按标题实时过滤
- 每行信息：序号、标题（截断）、年份、AI决定标签
- 有人工覆写时显示 `✎` 标志并高亮区分
- 点击条目高亮选中，右侧展示详情

### 右栏（文献详情）
- 文献基本信息（标题、作者、年份、期刊、DOI）
- Abstract 全文（支持折叠/展开）
- AI 判断结果展示（decision + exclusion_reason）
- 打标区：三个按钮 `纳入 / 待定 / 排除` + 理由输入框

---

## 三、数据架构

### 3.1 数据来源

AI 初筛已将每篇文献的筛选结果存为独立 JSON（DataFile），字段包括：
```json
{
  "title": "...",
  "authors": "...",
  "year": "...",
  "journal": "...",
  "doi": "...",
  "source_xml": "xxx.xml",
  "decision": "included | excluded | error",
  "include_or_not": "yes | no",
  "exclusion_reason": "...",
  "number_exclusion_reason": "3"
}
```

**注意：abstract 字段当前不在 AI 筛选结果 JSON 里**，需要在 API 层从原始 XML 文件中读取。

### 3.2 新增数据模型 ManualReview

```python
class ManualReview(models.Model):
    project     = ForeignKey(Project, on_delete=CASCADE)
    step        = ForeignKey(StageStep, on_delete=CASCADE)   # review 步骤
    source_xml  = CharField(max_length=255)     # 唯一对应 source_xml 字段
    ai_decision = CharField(max_length=20)      # 冗余存 AI 原始决定
    decision    = CharField(max_length=20)      # 人工最终: included/excluded/pending
    reason      = TextField(blank=True)
    reviewer    = ForeignKey(User, on_delete=SET_NULL, null=True)
    reviewed_at = DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('project', 'source_xml')
```

### 3.3 Export 步骤联动逻辑

```
对每篇文献：
  若 ManualReview 表中存在该 source_xml 的覆写记录
    → 使用人工 decision
  否则
    → 使用 AI 原始 include_or_not / decision
```

---

## 四、后端改动清单

| 文件 | 操作 | 内容 |
|---|---|---|
| `core/models.py` | 新增 | `ManualReview` 模型 |
| `core/migrations/` | 生成 | `makemigrations` |
| `core/step_config.py` | 修改 | `sub_steps` 加 `review`；steps list 插 order=45；新增 `review` 步骤配置 |
| `core/api/review_views.py` | 新建 | 列表/提交/更新/统计接口 |
| `core/urls.py` | 修改 | 注册 `/review/` 路由 |
| `core/executors/handlers/export_handler.py` | 修改 | `_is_included` 优先查 `ManualReview` |
| `core/admin.py` | 修改 | 注册 `ManualReviewAdmin` |

### API 接口设计

```
GET  /api/review/list/?project=&step=&decision=&q=&page=&page_size=
     → 分页返回文献列表（含 abstract，从原始 XML 读）

POST /api/review/submit/
     { project, step, reviews: [{source_xml, decision, reason}, ...] }
     → 批量提交/更新人工决定

PATCH /api/review/{source_xml}/
     { decision, reason }
     → 单条即时更新

GET  /api/review/stats/?project=&step=
     → { total, reviewed, pending, included, excluded, ai_included, ai_excluded }

POST /api/review/complete/
     { project, step }
     → 标记 review 步骤为 completed
```

---

## 五、前端改动清单

| 文件 | 操作 | 内容 |
|---|---|---|
| `web/src/components/steps/StepReview.vue` | 新建 | 主组件，左右分栏布局 |
| `web/src/stores/screening.js` | 修改 | 新增 review 相关状态 |
| `web/src/views/WorkspaceView.vue` | 修改 | 注册 `step_key=review` 渲染 `StepReview` |

---

## 六、步骤配置

```python
"review": {
    "name": "人工检查",
    "stage_key": "SCREEN_1",
    "execution_mode": "manual",   # 纯前端交互，不触发后台任务
    "description": "对 AI 筛选结果进行人工复核，可覆写 AI 判断",
    "can_skip": True,             # 可跳过，直接进 export
    "timeout": None,
    "inputs": ["results/*/*.json"],
    "outputs": [],                # 无产物文件，结果存 ManualReview 表
}
```

Steps list 插入：
```python
{"step_key": "review", "name": "人工检查", "order": 45, "can_skip": True}
```

---

## 七、已知技术细节

### Abstract 读取
当前 AI 筛选结果 JSON **不包含 abstract**，列表接口需要从原始 XML 文件中实时读取。
读取路径：`source_xml` → 在 `DataFile` 表中找对应的去重后 XML 文件 → 解析 `<Abstract>` 标签。
性能影响：每次分页请求读取约 50 条 XML，可接受；若文献量很大可考虑缓存到 Redis。

### 既有数据兼容
对于已经跑完 ai_screen 并直接 export 的旧项目，review 步骤会显示为 pending 状态，不影响已完成的 export 结果。

### 步骤跳过逻辑
review 步骤 `can_skip: True`，用户可以不审直接点 export，此时 export 完全用 AI 原始结果。

### 进度定义
"完成" = 用户主动点击"完成人工审阅"按钮，不要求每篇都打标。
步骤进度条显示：已覆写篇数 / 总篇数（反映人工参与度，不作为完成门槛）。

---

## 八、待明确问题

> 请逐条确认后，开始开发。

**Q1. 打标保存方式**
- **方案A（即时保存）**：点击"纳入/排除"按钮后立即发 PATCH 请求保存，无需额外确认
- **方案B（手动保存）**：操作后先在本地暂存，点"确认"才保存到后端

推荐方案 A，体验更流畅，但需要网络可用。

---

**Q2. 默认展示顺序**
- **A. AI 排除优先**：将 AI 判断为 excluded 的排在前面，方便人工重点复查
- **B. 原始顺序**：按 AI 筛选时处理的顺序
- **C. AI 纳入优先**：将 AI 纳入的排在前面

推荐方案 A，因为人工复查的主要目的是"找回被 AI 误排除的文献"。

---

**Q3. 是否展示 AI 排除理由**
AI 筛选结果中包含 `exclusion_reason`（如"不符合纳排标准3，该研究未涉及..."），是否在右侧详情中展示？
- **是**：帮助人工判断 AI 是否排除有误
- **否**：避免先入为主影响人工判断（盲审模式）

---

**Q4. 步骤完成后是否锁定**
人工审阅完成并点击"完成"后：
- **A. 锁定**：步骤变为 completed，不允许再修改，需要点"重新审阅"才能解锁
- **B. 不锁定**：completed 只是标记，随时可以继续修改覆写记录

---

**Q5. 重新 AI 筛选后人工记录如何处理**
如果用户重新跑了一次 AI 筛选（点"重新筛选"），之前的 ManualReview 记录：
- **A. 清空**：旧记录失效，人工检查步骤重置为 pending
- **B. 保留**：保留人工覆写记录，新的 AI 结果与旧的人工记录合并展示（标注"AI重新筛选"）

---

**Q6. 待定（pending）状态**
打标时是否需要"待定"这个中间状态（对应截图中的 `? Maybe`）？
- **有待定**：三态（纳入/待定/排除），方便分批审阅，未处理完的先标待定
- **无待定**：只有纳入/排除二择一，以及"未审"（未打标）

---

**Q7. 批量操作**
是否需要批量打标功能（如"将所有 AI 排除的批量标为排除"或"全选后批量纳入"）？
- 有批量操作可以提高效率，但增加实现复杂度
- 可以作为后续迭代，当前版本不做

---

**Q8. 导出时人工覆写的标识**
Export 步骤生成 Excel 时，是否需要单独一列标识"此条为人工覆写"？
- **是**：增加 `manual_override: yes/no` 列，方便后续追溯
- **否**：只输出最终决定，不区分来源
