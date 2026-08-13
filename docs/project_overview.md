# 科研数据提取平台 — 项目概览

> 版本：v1.0 | 更新时间：2026-08  
> 适用读者：新接手开发者、项目评审方、技术合作方  
> 代码仓库：[https://github.com/shaoweifeng/data_extraction](https://github.com/shaoweifeng/data_extraction)

---

## 一、项目简介

**科研数据提取平台**是一个面向系统综述（Systematic Review）研究场景的 Web 应用，帮助研究者完成从多个数据库导出的文献从**导入 → 去重 → 设定标准 → AI 初筛 → 结果导出**的全流程自动化处理，显著降低人工文献筛查的工作量。

### 核心价值
- 支持主流文献格式一键导入（RIS / BibTeX / NBIB / XML 等 8 种格式）
- 基于 LLM 的文献自动筛选，单次可处理数千篇
- 可配置纳排标准，AI 严格按标准输出包含/排除判断及理由
- 多用户、多项目隔离，支持团队协作

---

## 二、技术栈

| 层次 | 技术 |
|---|---|
| 前端 | Vue 3 + Vite + Pinia + TailwindCSS |
| 后端 | Django 5 + Django REST Framework |
| 异步任务 | Celery + Redis（线程池模式） |
| 数据库 | MySQL 8（主存储）+ Redis（任务队列/并发控制） |
| AI 接入 | OpenAI 兼容接口（DeepSeek / 豆包 / 千问） |
| 文件存储 | 本地 FileSystem（`media/` 目录） |
| 部署 | Gunicorn（生产）/ runserver（开发）+ WhiteNoise 静态托管，`start.sh` 一键启动 |

---

## 三、系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                        浏览器 (Vue 3 SPA)                    │
│  HomeView  WorkspaceView  ProfileView  LoginView             │
│  StepParse StepDedup StepCriteria StepFields StepAiScreen   │
│  StepExport                                                  │
└───────────────────┬─────────────────────────────────────────┘
                    │ HTTP / REST API
┌───────────────────▼─────────────────────────────────────────┐
│                   Django REST Framework                      │
│  auth_views  project_views  stage_views  step_views          │
│  file_views  task_views  billing_views  user_views           │
└───────┬───────────────────────────────────────┬─────────────┘
        │ ORM                                   │ Celery Task
┌───────▼──────────┐              ┌─────────────▼─────────────┐
│      MySQL       │              │    Celery Worker (threads) │
│  UserProfile     │              │  ParseHandler              │
│  Project         │              │  DedupHandler              │
│  ProjectStage    │              │  AiScreenHandler           │
│  StageStep       │              │  ExportHandler             │
│  DataFile        │              │                            │
│  Task            │              │  AI Providers:             │
│  CreditAccount   │              │  - DeepSeek                │
│  CreditTransaction│             │  - 豆包 (Doubao)           │
│  RechargeCode    │              │  - 千问 (Qwen)             │
└──────────────────┘              └───────────────────────────┘
                                              │
                                  ┌───────────▼───────────────┐
                                  │          Redis             │
                                  │  Celery Broker/Result      │
                                  │  并发槽计数（AI筛选限流）   │
                                  └───────────────────────────┘
```

---

## 四、核心业务流程

平台将文献处理拆分为**一个阶段（SCREEN_1）六个步骤**，每个步骤有独立状态和产物。

```
SCREEN_1 文献初筛
│
├── Step 1: parse（文献解析）        order=10  async
│     上传原始文献文件 → 解析为单篇 XML
│
├── Step 2: dedup（自动去重）         order=20  async  可跳过
│     基于标题规范化去重 → 生成去重报告
│
├── Step 3: criteria（纳排标准）      order=30  manual
│     手动录入纳入/排除标准
│
├── Step 4: field_extraction（提取字段）order=35  manual  可跳过
│     配置 AI 在筛选时额外提取的结构化字段
│
├── Step 5: ai_screen（AI 初筛）      order=40  async
│     调用 LLM 批量判断 included/excluded
│
└── Step 6: export（结果归纳）        order=50  async
      汇总筛选结果 → 生成 Excel + RIS 文件
```

### 每步骤执行模式说明

| 模式 | 含义 |
|---|---|
| `async` | 由 Celery Worker 后台执行，前端实时轮询进度 |
| `manual` | 纯前端交互，无后台任务，用户操作后调 API 标记完成 |

---

## 五、各模块详解

### 5.1 文献解析（parse_handler）

支持的输入格式：

| 格式 | 扩展名 | 来源数据库 |
|---|---|---|
| RIS | `.ris` | EndNote、Zotero、万方等 |
| BibTeX | `.bib` | LaTeX 工具链 |
| NBIB/Medline | `.nbib` | PubMed |
| XML | `.xml` | Web of Science 等 |
| CIW | `.ciw` | Web of Science 早期格式 |
| ENW | `.enw` | EndNote Web |
| DOCX | `.docx` | Word 文档手动整理 |
| TXT | `.txt` | 纯文本 |

处理结果：每篇文献生成一个独立 XML 文件，写入 `DataFile` 表，进度实时同步到前端（500ms 轮询）。

---

### 5.2 自动去重（dedup_handler）

算法：基于标题规范化（去除标点、大小写统一后对比），保留首次出现的记录。

输出：
- `dedup_xmls/`：去重后的文献 XML 文件
- `dedup_report.json`：去重统计（总数/保留数/重复数/重复率/具体重复组）

前端展示去重统计报告及可展开的重复文献列表，支持查看每组重复文献的来源、DOI。

---

### 5.3 纳排标准录入（criteria）

步骤 3，order=30，**manual 模式**，**不可跳过**。

用户在此步骤录入文献的纳入/排除标准，这些标准将直接注入 AI 初筛的 Prompt 中，AI 严格按照标准对每篇文献作出判断。

**录入方式：**

| 方式 | 说明 |
|---|---|
| 快捷预设勾选 | 内置 5 条系统综述常用排除标准，勾选即自动添加 |
| 自定义输入 | 手动输入一条标准后按回车或点击添加，支持任意数量 |

**内置预设标准（5 条）：**
1. 无法获取摘要的文献
2. 非中、英文发表的文献
3. 会议摘要、评论、社论、报道及学位论文
4. 研究类型为非原始研究（如综述研究等）
5. 未以人类为研究对象

**撰写指南：**  
界面内置"排除标准撰写指南"抽屉，基于 **PICOs / PEO 原则**引导用户从 4 个维度完整定义标准：
- **P（Population）**：研究人群
- **I/E（Intervention/Exposure）**：干预或暴露因素
- **C（Comparator）**：对照组
- **O（Outcome）**：结局指标

**存储方式：**  
标准列表以 JSON 数组形式保存在 `StageStep.metadata.criteria`，AI 筛选时由 `ai_screen_handler` 读取并格式化注入 Prompt 的 `{screening_criteria}` 占位符。

**注意：**
- 每条标准独立编号，AI 输出排除原因时会引用对应标准编号（`number_exclusion_reason`）
- 增删标准后无需重新保存，即时生效并同步到步骤状态
- 如需修改已开始筛选的项目的标准，需重新执行 AI 筛选步骤

---

### 5.4 自定义提取字段（field_extraction）

步骤 4，order=35，**manual 模式**，**可跳过**。

在 AI 筛选之前，用户可以定义一组自定义字段，要求 AI 在判断文献纳排的同时，从**纳入文献**的摘要/全文中额外提取这些结构化信息。

**字段结构：**
每个字段由两部分组成：

| 项 | 说明 | 示例 |
|---|---|---|
| 字段名称 | 简短的字段标签 | `年龄` |
| 字段定义 | 描述 AI 应该提取什么内容 | `研究中纳入患者的年龄情况` |

**工作原理：**
1. 用户在"设定提取字段"步骤添加若干字段，即时保存到 `StageStep.metadata.fields`
2. AI 筛选时，`ai_screen_handler` 读取这些字段，自动在 Prompt 末尾追加提取指令
3. AI 输出的 JSON 中额外包含 `extracted_fields` 对象，键为字段名，值为提取内容
4. 导出时，每个自定义字段作为独立列写入 Excel

**示例 Prompt 追加内容：**
```
=======字段提取任务=======
对于纳入的文献，请同时从全文内容中提取以下字段信息：
  - "年龄": 研究中纳入患者的年龄情况
  - "样本量": 研究的总样本量

输出JSON中的 extracted_fields 字段包含提取结果，格式：
{"extracted_fields": {"年龄": "提取值", "样本量": "提取值"}, ...}
```

**注意：**
- 字段提取仅对 AI **纳入**的文献生效，排除文献不执行提取
- 该步骤可跳过，跳过后 AI 筛选仅输出纳排判断，不含额外字段
- 已配置的字段在 AI 筛选结束前可随时增删，重新筛选时生效

---

### 5.5 AI 初筛（ai_screen_handler）

**核心能力：**
- 多模型支持（DeepSeek / 豆包 / 千问），通过 OpenAI 兼容接口统一接入
- 批量并发处理，每篇文献独立调用 AI，并发度由用户等级决定
- AI 严格按纳排标准输出 JSON 判断（纳入/排除 + 排除理由 + 违反标准编号）
- 支持"断点续筛"：重新筛选时已筛的文献自动跳过

**并发控制（计费+限流）：**
- 普通用户：2 线程并发
- 管理员账户：16 线程并发
- 全局最大线程槽：64（所有用户任务共享）
- 任务超出槽位时自动排队（最多等待 1 小时）

**计费规则：**
- 1 credit = 1000 tokens
- 筛选前预估并冻结（防透支），完成后按实际 token 消耗精确扣费
- 管理员账户免费，但仍记录等值 credit 的用量审计流水

---

### 5.6 结果导出（export_handler）

导出内容：
- **Excel**（`.xlsx`）：包含所有文献的标题、作者、年份、期刊、DOI、AI判断、排除理由、提取字段
- **RIS**（`.ris`）：仅纳入文献，可直接导入 EndNote / Zotero

导出模式：`all`（全部）/ `included`（仅纳入）/ `excluded`（仅排除），可在 Export 步骤配置。

---

## 六、用户与权限体系

### 用户角色

| 角色 | 标识 | 能力 |
|---|---|---|
| 超级管理员 | Django `is_superuser` | 后台管理全部数据 |
| 平台管理员 | `role=admin` | 管理用户、调整额度、免费使用 AI 筛选 |
| 普通用户 | `role=user` | 创建项目、使用所有功能、受 credits 限制 |

### 用户配额（UserProfile）

| 配额项 | 普通用户默认 | 说明 |
|---|---|---|
| 项目数 | 10 | 可由管理员调整 |
| 存储空间 | 5120 MB | 可由管理员调整 |
| AI 并发线程 | 2 | 可由管理员调整 |

### Credits 积分系统

- 新用户注册自动赠送 200 credits
- 支持兑换码充值（管理员后台生成兑换码）
- 管理员可手动调整用户额度
- 个人中心展示余额、交易流水（赠送/充值/消耗/退款/管理员用量）

---

## 七、项目管理

- 每个用户可创建多个**项目（Project）**，项目相互隔离
- 每个项目包含六个阶段（SEARCH / SCREEN_1 / SCREEN_2 / QUALITY / EXTRACT / META），当前实现 SCREEN_1
- 项目主页：卡片网格，显示项目名称、文献数、进度
- 工作台：左侧步骤导航，右侧内容区，步骤完成后变绿

---

## 八、任务系统

| 任务类型 | 触发场景 |
|---|---|
| `parse` | 上传文献文件后 |
| `deduplication` | 点击"开始去重" |
| `ai_screening` | 点击"开始筛选" |
| `export` | 点击"开始导出" |

任务状态：`pending` → `queuing`（等待槽位）→ `running` → `completed` / `failed`

所有异步任务支持：
- 前端实时进度轮询（500ms）
- 可停止（`/tasks/{id}/stop/` 接口）
- 失败时保留错误信息

---

## 九、系统安全

- Cookie-based 登录认证（Django Session）
- CSRF 保护（DRF + Django 双重）
- 注册防刷：同 IP 24 小时内最多注册 3 个账号（可配置）
- 用户封禁机制（is_banned）
- 所有文件路径隔离到各自项目的 workspace 目录

---

## 十、部署与运维

### 快速启动

| 命令 | 说明 |
|---|---|
| `./start.sh` | 前台生产模式，构建前端后用 **Gunicorn** 启动 |
| `./start.sh -d` | 后台守护模式，Gunicorn daemon，进程常驻 |
| `./start.sh --no-build -d` | 后台守护模式，跳过前端构建（服务器部署常用） |
| `./start.sh --dev` | 开发模式，使用 runserver + Vite dev server |
| `./start.sh --dev -d` | 开发模式后台守护 |
| `./stop.sh` | 停止所有后台进程 |

### 启动顺序
1. Redis（任务队列）
2. Celery Worker（后台任务处理，16 线程）
3. **Gunicorn**（生产 WSGI 服务器，4 workers × 2 线程，timeout 300s）
   - 开发模式（`--dev`）改用 Django runserver，支持热重载

### 日志文件

| 文件 | 内容 |
|---|---|
| `logs/gunicorn_access.log` | HTTP 访问日志 |
| `logs/gunicorn_error.log` | 错误日志 |
| `logs/celery.log` | Celery Worker 日志 |

### 服务器更新部署流程

```bash
git fetch --tags
git checkout v1.0.1           # 切到目标 tag 版本
./stop.sh                     # 停止旧服务
pip install -r requirements.txt   # 更新依赖（有新包时）
python manage.py migrate      # 更新数据库（有新迁移时）
./start.sh --no-build -d      # 重新启动
```

### 关键目录

```
data_extraction/
├── core/               # Django 主应用（模型/视图/执行器）
│   ├── api/            # REST API 视图层
│   ├── executors/      # 步骤执行器（handler + AI provider + parser）
│   ├── services/       # 业务逻辑层（billing/concurrency/project等）
│   └── migrations/     # 数据库迁移
├── platform_backend/   # Django 项目配置
├── web/                # Vue 3 前端
│   └── src/
│       ├── components/steps/  # 六个步骤组件
│       ├── views/             # 四个页面视图
│       └── stores/            # Pinia 状态管理
├── media/              # 用户上传文件 & 任务产物
├── workspaces/         # 各项目任务的工作目录
├── logs/               # Django / Celery 运行日志
├── docs/               # 开发文档
└── start.sh / stop.sh  # 一键启停脚本
```

### 环境变量（核心配置）

| 变量 | 说明 | 默认值 |
|---|---|---|
| `DB_NAME / DB_USER / DB_PASSWORD` | MySQL 连接 | `data_extraction / root / 123456` |
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | — |
| `DOUBAO_API_KEY` | 豆包 API 密钥 | — |
| `QWEN_API_KEY` | 千问 API 密钥 | — |
| `AI_SCREEN_ADMIN_CONCURRENCY` | 管理员并发线程数 | `16` |
| `AI_SCREEN_DEFAULT_CONCURRENCY` | 普通用户并发线程数 | `2` |
| `AI_SCREEN_MAX_GLOBAL_THREADS` | 全局最大线程数 | `64` |
| `BILLING_FREE_CREDITS_ON_REGISTER` | 新用户赠送 credits | `200` |
| `BILLING_CREDIT_TOKEN_RATIO` | 1 credit 对应 token 数 | `1000` |

---

## 十一、数据存储详解

### 11.1 数据库总览

所有表以 `plat_` 为前缀，分三大组：**用户权限组**、**项目业务组**、**计费组**，加上 Django 内置的 `auth_user`。

```
auth_user（Django 内置）
    │
    ├──1:1── plat_userprofile        用户扩展信息（角色/配额/封禁）
    ├──1:1── plat_creditaccount      积分账户
    ├──1:*── plat_credittransaction  积分流水
    ├──1:*── plat_tokenusagelog      AI token 用量明细
    ├──1:*── plat_userpermission     用户-权限关系（RBAC）
    ├──1:*── plat_project            拥有的项目
    └──1:*── plat_registrationlog   注册行为日志

plat_project（项目）
    │
    ├──1:*── plat_projectstage       阶段（SCREEN_1 / SCREEN_2 等）
    │            │
    │            ├──1:*── plat_stagestep    步骤（parse/dedup/ai_screen等）
    │            │            │
    │            │            └──1:*── plat_datafile    步骤产物文件
    │            │                         │
    │            │                         └──1:*── plat_datafileversion  文件历史版本
    │            │
    │            └──1:*── plat_task         后台任务
    │                         │
    │                         └──1:*── plat_credittransaction（关联 AI 筛选计费）
    │
    └──1:*── plat_activity_log       操作行为日志

plat_permission                      权限定义表
plat_roletemplate                    角色模板
plat_roletemplatepermission          角色模板-权限关联
plat_rechargecode                    充值兑换码
```

---

### 11.2 各表详解

#### `auth_user`（Django 内置）
Django 标准用户表。

| 字段 | 说明 |
|---|---|
| `id` | 主键 |
| `username` | 登录用户名 |
| `password` | 哈希密码 |
| `email` | 邮箱 |
| `is_superuser` | 是否超级管理员（超管自动获得 admin 权限） |
| `is_active` | 是否激活（false 则无法登录） |
| `date_joined` | 注册时间 |

---

#### `plat_userprofile`（用户配置）
与 `auth_user` 1:1，存储平台业务扩展字段。**User 创建时由信号自动生成。**

| 字段 | 类型 | 说明 |
|---|---|---|
| `user_id` | FK→auth_user | 关联用户（唯一） |
| `role` | varchar | 角色：`admin`（管理员）/ `user`（普通用户） |
| `quota_projects` | int | 最多可创建项目数，默认 10 |
| `quota_storage_mb` | int | 存储配额（MB），默认 5120 |
| `concurrency_limit` | int | AI 筛选并发线程数，默认 2 |
| `is_approved` | bool | 是否已审核（当前默认 true，免审） |
| `is_banned` | bool | 是否被封禁，true 则登录返回 403 |
| `approved_at/by` | datetime/FK | 审核时间和审核人 |

---

#### `plat_project`（项目）
每个研究课题对应一个项目，是所有业务数据的根。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | PK | 主键 |
| `name` | varchar | 项目名称 |
| `slug` | varchar(unique) | URL 友好标识，自动从 name 生成 |
| `description` | text | 项目描述 |
| `owner_id` | FK→auth_user | 项目所有者 |
| `status` | varchar | `active` / `archived` / `deleted` |
| `metadata` | JSON | 扩展元数据（预留） |

---

#### `plat_projectstage`（阶段）
一个项目有多个阶段（目前实现 SCREEN_1），每个阶段独立记录状态。

| 字段 | 类型 | 说明 |
|---|---|---|
| `project_id` | FK→plat_project | 所属项目 |
| `stage_key` | varchar | 阶段唯一标识：`SCREEN_1` / `SCREEN_2` / `QUALITY` / `EXTRACT` / `META` |
| `name` | varchar | 阶段名称 |
| `order` | int | 排序号 |
| `status` | varchar | `pending` / `in_progress` / `completed` / `skipped` |
| `started_at` / `completed_at` | datetime | 时间戳 |
| `metadata` | JSON | 扩展元数据 |

> **联合唯一**：`(project_id, stage_key)`，一个项目每个阶段只有一行。

---

#### `plat_stagestep`（步骤）
一个阶段下有多个步骤，对应实际处理工序。

| 字段 | 类型 | 说明 |
|---|---|---|
| `stage_id` | FK→plat_projectstage | 所属阶段 |
| `step_key` | varchar | 步骤标识：`parse` / `dedup` / `criteria` / `field_extraction` / `ai_screen` / `export` |
| `name` | varchar | 步骤名称 |
| `order` | int | 排序号（parse=10, dedup=20 ... export=50） |
| `status` | varchar | `pending` / `in_progress` / `completed` / `failed` / `skipped` |
| `can_skip` | bool | 是否允许跳过 |
| `metadata` | JSON | 步骤产出的统计信息（如去重报告的总数/重复数，AI 筛选的纳入/排除数） |

> **联合唯一**：`(stage_id, step_key)`

---

#### `plat_datafile`（数据文件）
记录每个步骤产出（或输入）的文件，物理文件存在 `media/` 目录。

| 字段 | 类型 | 说明 |
|---|---|---|
| `project_id` | FK→plat_project | 所属项目 |
| `stage_id` | FK→plat_projectstage | 所属阶段 |
| `step_id` | FK→plat_stagestep | 所属步骤（如 parse 步骤的输出文件） |
| `filename` | varchar | 文件名 |
| `file` | FileField | 物理文件路径（`media/projects/project_{id}/...`） |
| `file_size` | bigint | 文件大小（字节） |
| `file_type` | varchar | 扩展名（xml/json/xlsx/ris 等） |
| `data_category` | varchar | `input`（用户上传原始文件）/ `intermediate`（中间处理文件，如单篇 XML）/ `output`（最终产物，如 Excel） |
| `source` | varchar | `upload`（用户上传）/ `tool_generated`（工具生成） |
| `description` | text | 文件描述（如"单篇文献XML"/"去重后的文献XML"/"AI筛选结果JSON"） |
| `metadata` | JSON | 扩展信息 |

**典型数据流：**
```
用户上传 .ris 文件  → DataFile(category=input,  step=parse)
parse 生成单篇 XML  → DataFile(category=intermediate, step=parse, desc="单篇文献XML")
dedup 输出去重 XML  → DataFile(category=intermediate, step=dedup, desc="去重后的文献XML")
ai_screen 输出 JSON → DataFile(category=output, step=ai_screen, desc="AI筛选结果JSON")
export 输出 xlsx    → DataFile(category=output, step=export)
export 输出 .ris    → DataFile(category=output, step=export)
```

---

#### `plat_datafileversion`（文件版本历史）
DataFile 的历史版本，支持版本回溯（当前较少使用）。

| 字段 | 说明 |
|---|---|
| `data_file_id` | FK→plat_datafile |
| `version` | 版本号（整数，递增） |
| `file_path` | 历史版本物理路径 |
| `change_summary` | 变更说明 |

---

#### `plat_task`（后台任务）
每次触发异步操作（解析/去重/筛选/导出）创建一条记录，与 Celery 任务对应。

| 字段 | 类型 | 说明 |
|---|---|---|
| `project_id` | FK→plat_project | 所属项目 |
| `stage_id` | FK→plat_projectstage | 所属阶段 |
| `step_id` | FK→plat_stagestep | 所属步骤 |
| `task_type` | varchar | `parse` / `deduplication` / `ai_screening` / `export` |
| `celery_task_id` | varchar | Celery 分配的任务 ID |
| `status` | varchar | `pending`→`queuing`→`running`→`completed`/`failed`/`stopped` |
| `progress` | float | 进度 0.0~1.0（前端乘 100 显示百分比） |
| `config` | JSON | 任务配置参数（如 ai_model、file_ids；也存运行时进度信息如 `parse_progress`） |
| `result` | JSON | 任务完成后的统计结果（token 用量统计等） |
| `logs` | text | 实时运行日志（Celery Worker 定期同步） |
| `log_file` | varchar | 日志文件的磁盘路径 |
| `error_message` | text | 失败时的错误信息 |

---

#### `plat_activity_log`（操作行为日志）
记录用户的关键操作（不是系统日志，是审计日志）。

| 字段 | 说明 |
|---|---|
| `project_id` | FK→plat_project |
| `operation_type` | 操作类型枚举（共 14 种，如 file_add / criteria_add / task_start_ai_screen 等） |
| `operation_detail` | JSON，存操作的详细参数（如上传的文件名） |
| `created_by` | FK→auth_user，操作者 |
| `created_at` | 操作时间 |

---

#### `plat_permission`（权限定义）
系统预设的权限码，用于细粒度授权（当前主要通过 role 字段控制，本表为 RBAC 扩展预留）。

| 字段 | 说明 |
|---|---|
| `code` | 权限码（唯一），如 `project.view_all`、`user.ban` |
| `name` | 可读名称 |
| `category` | 分类：user/project/stage/task/file/system |
| `is_system` | 是否系统内置权限 |

---

#### `plat_userpermission`（用户-权限关系）
用户与权限的多对多中间表（支持有效期）。

| 字段 | 说明 |
|---|---|
| `user_id` | FK→auth_user |
| `permission_id` | FK→plat_permission |
| `granted_by_id` | 授权人 |
| `expires_at` | 权限过期时间（null=永久） |

---

#### `plat_roletemplate` / `plat_roletemplatepermission`（角色模板）
预置的角色权限组合，方便批量授权（当前为扩展预留，主要逻辑由 UserProfile.role 控制）。

---

#### `plat_creditaccount`（积分账户）
每个用户有且仅有一个账户，**User 创建时由信号自动生成并赠送 200 credits**。

| 字段 | 说明 |
|---|---|
| `user_id` | OneToOne→auth_user |
| `balance` | 当前余额（只减不增，充值/消耗都通过流水更新） |
| `total_granted` | 累计获得 credits（赠送+充值，只增不减） |
| `total_consumed` | 累计消耗 credits（只增不减） |

---

#### `plat_credittransaction`（积分流水）
每次额度变动写一条，余额历史可完整追溯。

| 字段 | 说明 |
|---|---|
| `account_id` | FK→plat_creditaccount |
| `txn_type` | `grant`（赠送）/ `recharge`（兑换码充值）/ `consume`（AI扣费）/ `refund`（退款）/ `adjust`（管理员手动）/ `admin_usage`（管理员用量审计，amount=0） |
| `amount` | 变动量，正数=增加，负数=扣减；`admin_usage` 时固定为 0 |
| `balance_after` | 操作后余额快照 |
| `task_id` | FK→plat_task（AI 筛选的 consume/refund 关联到具体任务） |
| `note` | 备注（如"注册赠送"、项目名+模型名） |
| `created_by` | 操作人（管理员手动调整时有值） |

---

#### `plat_tokenusagelog`（Token 用量明细）
AI API 每次调用的 token 明细，粒度比 CreditTransaction 更细。

| 字段 | 说明 |
|---|---|
| `task_id` | FK→plat_task |
| `user_id` | FK→auth_user |
| `model` | 模型名称（如 `deepseek-chat`） |
| `prompt_tokens` | 输入 token 数 |
| `completion_tokens` | 输出 token 数 |
| `total_tokens` | 合计 |
| `credits_consumed` | 折算 credits（total_tokens / BILLING_CREDIT_TOKEN_RATIO） |
| `ref_count` | 本批次处理文献篇数 |
| `transaction_id` | FK→plat_credittransaction（关联对应的扣费流水） |

---

#### `plat_rechargecode`（充值兑换码）
管理员在 Django Admin 后台创建，用户在个人中心兑换。

| 字段 | 说明 |
|---|---|
| `code` | 兑换码字符串（唯一，建议格式 `FREE-XXXX-XXXX`） |
| `credits` | 面值 |
| `is_used` | 是否已使用 |
| `used_by_id` | 使用者 |
| `used_at` | 使用时间 |
| `expires_at` | 过期时间（null=永不过期） |
| `created_by_id` | 创建者（管理员） |
| `note` | 备注（如发放对象说明） |

---

#### `plat_registrationlog`（注册行为日志）
每次注册请求（成功/失败）均记录，用于 IP 限流。

| 字段 | 说明 |
|---|---|
| `ip_address` | 注册来源 IP |
| `email` | 填写的邮箱 |
| `username` | 填写的用户名 |
| `success` | 是否注册成功 |
| `fail_reason` | 失败原因 |
| `email_verified` | 邮箱是否验证（当前默认 false，预留字段） |

---

### 11.3 表关系总图

```
auth_user ──1:1──► plat_userprofile
          ──1:1──► plat_creditaccount ──1:*──► plat_credittransaction ◄──FK── plat_task
          ──1:*──► plat_tokenusagelog ─────────────────────────────────────────────────┘
          ──1:*──► plat_project
                       │
                       ├──1:*──► plat_projectstage
                       │              │
                       │              ├──1:*──► plat_stagestep
                       │              │              │
                       │              │              └──1:*──► plat_datafile ──1:*──► plat_datafileversion
                       │              │
                       │              └──1:*──► plat_task
                       │
                       └──1:*──► plat_activity_log

plat_permission ◄──M:N──► auth_user  （通过 plat_userpermission）
plat_roletemplate ◄──M:N──► plat_permission  （通过 plat_roletemplatepermission）
plat_rechargecode ──FK──► auth_user（used_by / created_by）
```

---

### 11.4 关键数据流举例

**用户完成一次 AI 筛选的完整数据写入路径：**

```
1. 用户点击"开始筛选"
   → plat_task 新增一行（status=pending, task_type=ai_screening）

2. Celery 接到任务，开始处理
   → plat_task.status = running
   → plat_task.progress 持续更新（0→1）

3. 每篇文献筛选完成
   → plat_datafile 新增一行（category=output, step=ai_screen, desc="AI筛选结果JSON"）

4. 所有文献筛选完成，计算实际 token
   → plat_tokenusagelog 新增一行（token 明细）
   → plat_credittransaction 新增一行（txn_type=consume, amount=负数）
   → plat_creditaccount.balance 减少
   → plat_task.status = completed

5. 若预扣余额 > 实际消耗
   → plat_credittransaction 再新增一行（txn_type=refund, amount=正数）
   → plat_creditaccount.balance 恢复差额
```

## 十二、当前版本状态（v1.0）

### 已完成功能

- [x] 完整的六步骤文献初筛流程
- [x] 8 种文献格式解析
- [x] 标题规范化去重 + 去重报告
- [x] 可配置纳排标准（增删改）
- [x] 自定义 AI 提取字段
- [x] 三大 LLM 接入（DeepSeek / 豆包 / 千问）
- [x] 并发筛选 + 全局限流排队
- [x] 断点续筛（任务中断后可恢复）
- [x] Credits 积分计费系统
- [x] 兑换码充值
- [x] 管理员用量审计
- [x] 多用户 / 多项目隔离
- [x] 实时进度展示（解析/去重/筛选/导出）
- [x] Excel + RIS 双格式导出
- [x] 个人中心（余额/流水/配置）
- [x] 注册防刷 + 用户封禁

### 规划中功能

- [ ] **人工检查步骤**：AI 筛选后可人工复核并覆写判断结果（方案设计见 `docs/manual_review_plan.md`）
- [ ] SCREEN_2（全文复筛）阶段
- [ ] 文献质量评价（QUALITY）阶段
- [ ] 数据提取（EXTRACT）阶段
