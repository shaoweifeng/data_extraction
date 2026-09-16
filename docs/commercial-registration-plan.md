# 商业化注册与账户体系改造方案

> 文档状态：阶段 0～2 已完成验收；阶段 3 已完成开发、本地自动化回归与 MySQL 并发验证，真实 SMTP 人工验收待执行
> 修订日期：2026-09-16
> 适用范围：运行时安全基线、平台注册、邮箱验证、注册防刷、注册赠送、登录保护、密码找回、协议接受及账户后台管理  
> 关联文档：[`architecture.md`](./architecture.md)、[`operations.md`](./operations.md)、[`commercialization-plan-2026-09-10/report.html`](./commercialization-plan-2026-09-10/report.html)

## 1. 结论摘要

当前注册功能适合内部使用或小范围受控测试，不适合直接开放商业注册。Python 3.12、Django 5.2 LTS、阶段 1 注册安全基础均已完成本地验证；阶段 2 已实现邮箱验证 Token、待激活账户、异步邮件、激活与重发、欢迎积分幂等发放和安全清理能力，并已通过真实 SMTP 本地端到端验收。阶段 3 已实现用户名或已验证邮箱登录、密码找回、登录态改密和可信邮箱变更闭环，并通过本地自动化与 MySQL 并发验证；真实 SMTP 人工验收仍待执行。生产域名发信身份、SPF/DKIM/DMARC、MySQL/Redis 生产同类环境与正式部署，以及协议能力仍需在阶段 4 完成。

本方案作出以下核心决策：

1. 先升级到 Python 3.12 和 Django 5.2 LTS，再开发商业账户体系。
2. 继续使用 Django 内置 `auth.User`，不在现有项目中替换 `AUTH_USER_MODEL`。
3. 新增独立 `core.account` Django app，账户领域代码不继续堆积到 `core/api/auth_views.py`、`core/models.py` 或通用工具文件中。
4. 不直接修改 Django 自带 `auth_user.email` 的数据库约束；新增独立 `AccountEmail` 模型作为可信邮箱身份来源。
5. 第一版不引入完整账户状态机，继续以 `User.is_active`、`UserProfile.is_banned` 和邮箱验证状态表达当前所需状态。
6. 注册、激活、密码重置和积分赠送由显式 Service 负责，关键写操作使用事务、行锁、幂等键和数据库约束兜底。
7. 用户完成邮箱验证后才激活账户并领取注册赠送积分。
8. Redis 原子限流、代理层限流和数据库约束共同防护；不能把 DRF 默认 Throttle 当作完整安全措施。
9. 所有表结构变化通过新的增量 migration 实现，不修改任何已经部署的历史 migration。
10. 公开收费上线必须完成本文阶段 0～4；完成阶段 0～1 后仅适合内部或邀请制测试。

| 完成范围 | 适用场景 | 判断 |
|---|---|---|
| 当前状态 | 内部使用、小范围受控测试 | 基本可用 |
| 阶段 0～1 | 邀请制测试、有限用户试用 | 可用 |
| 阶段 0～4 | 小规模公开注册与收费 | 最低上线标准 |
| 后续增强项 | 规模化运营、机构客户 | 按实际业务增长实施 |

## 2. 当前实现基线

### 2.1 当前运行时

- Python 固定为 3.12。
- Django 固定为 5.2 LTS 最新补丁版本。
- Django REST Framework 为 3.16.1。
- 生产数据库为 MySQL，自动化测试默认使用内存 SQLite。
- Redis 已用于 Celery Broker、在线状态和 AI 并发控制。
- Celery 已接入账户验证邮件任务，本地默认使用控制台邮件后端。

运行时升级已独立完成，后续账户功能以 Python 3.12 和 Django 5.2 为唯一开发、测试和部署基线。

### 2.2 当前注册链路

1. 用户输入用户名、必填邮箱、密码和确认密码。
2. 前端向 `POST /api/auth/register/` 提交 JSON。
3. V2 后端执行邮箱规范化与唯一性、Django 密码规则、请求体和 Redis 多维限流校验。
4. `REQUIRE_EMAIL_VERIFICATION=false` 时创建已激活零余额账户，用于兼容和受控测试。
5. `REQUIRE_EMAIL_VERIFICATION=true` 时原子创建未激活用户、Profile、零余额积分账户、邮箱身份和单次验证 Token。
6. 事务完成后通过 Celery 投递验证邮件；数据库只保存 Token 摘要。
7. 用户通过验证页面激活账户，激活 Service 使用行锁和幂等键发放欢迎积分。
8. 重发邮件会废弃旧 Token；未激活账户不能登录，历史用户不被自动停用。

主要实现位置：

- `core/account/api/views.py`：V2 注册入口。
- `core/account/api/verification_views.py`：邮箱验证与重发入口。
- `core/account/api/authentication_views.py`、`security_views.py`：统一登录、密码与邮箱自助安全入口。
- `core/account/services/registration.py`、`verification.py`、`password_reset.py`、`email_change.py`：注册、Token、激活及账户安全事务。
- `core/account/tasks.py`：验证邮件异步投递与重试。
- `core/api/auth_views.py`：旧注册兼容链路及 `me/logout/csrf` 等既有认证接口。
- `core/models.py`：`UserProfile`、`RegistrationLog` 和 Profile 创建信号。
- `core/models_billing.py`：积分账户、流水和注册赠送信号。
- `core/services/billing_service.py`：积分账户兜底创建与积分服务。
- `web/src/features/account/`：登录、注册、账户状态和认证 API。
- `platform_backend/settings.py`：密码验证器、注册限制、积分和运行环境配置。

### 2.3 已具备的基础

- 使用 Django 密码散列机制，不存储明文密码。
- 用户名具有数据库唯一约束。
- 普通用户默认角色、项目配额、存储配额和 AI 并发档位明确。
- 积分账户与用户为一对一关系。
- 登录失败使用统一提示。
- Session、CSRF 和同源 API 调用链路已经建立。
- 注册日志、Redis、Celery 和 Django Admin 均可复用。

### 2.4 当前主要风险

| 问题 | 当前表现 | 风险等级 |
|---|---|---:|
| 生产邮件链路尚未验收 | 真实 SMTP 本地验收已通过，但生产域名发信身份、SPF/DKIM/DMARC、退信和送达率尚未验证 | 中高 |
| 强制邮箱验证默认关闭 | 打开 `REQUIRE_EMAIL_VERIFICATION` 前，新注册仍直接激活 | 高 |
| 账户自助安全待生产验收 | 密码找回、改密和邮箱变更已实现，但仍需在生产同类环境验证邮件、Redis 和 MySQL 并发行为 | 中高 |
| 邮件投递缺少 Outbox | Broker 在事务提交后瞬时不可用时依赖用户重发恢复 | 中 |
| 历史邮箱存在脏数据 | 空邮箱、非法邮箱和重复邮箱需管理员依据审计报告处理 | 中 |
| 测试数据库不同 | SQLite 测试不能证明 MySQL 并发和锁语义 | 中高 |
| 协议接受无记录 | 商业注册缺少协议和隐私闭环 | 中高 |
| 认证日志无留存策略 | 邮箱、IP 等个人信息可能长期保留 | 中 |

## 3. 目标边界与关键决策

### 3.1 保留 Django 内置 User

当前项目已有大量数据关联 `auth.User`，中途替换会涉及外键、权限、ContentType、历史 migration 和现有数据迁移，风险远大于收益。

```text
auth.User
├── username
├── password
├── email              # 兼容展示，不作为唯一性真相来源
├── is_active          # 待验证=False，激活=True
├── is_staff
└── is_superuser

AccountEmail
├── user               # OneToOne
├── email
├── normalized_email   # Unique，登录/找回/验证的真相来源
└── verified_at

UserProfile
├── role
├── is_banned
├── quota_projects
├── quota_storage_mb
└── concurrency_limit

CreditAccount
├── balance
├── total_granted
└── total_consumed
```

Django Admin 继续操作全部用户。后续通过自定义 `UserAdmin` 和 Inline 将邮箱、Profile、积分和协议信息汇总到同一用户页面。

### 3.2 第一版不建立完整账户状态机

| 条件 | 含义 | 是否允许登录 |
|---|---|---:|
| `is_active=False` 且邮箱未验证 | 等待邮箱验证 | 否 |
| `is_active=True` 且未封禁 | 正常账户 | 是 |
| `UserProfile.is_banned=True` | 封禁账户 | 否 |

`is_approved` 作为历史兼容字段保留，但不再承担新的注册审批语义。欠费暂停、注销冷静期、匿名化和组织账户出现实际需求后，再设计统一状态机，避免现在形成多字段双写和状态漂移。

### 3.3 独立邮箱身份模型

不直接向 Django 自带 `auth_user.email` 添加自定义唯一约束。新增：

```text
AccountEmail
├── user_id             OneToOne + Unique
├── email               规范展示值
├── normalized_email    Unique
├── verified_at         Nullable
├── created_at
└── updated_at
```

邮箱规则：

- 新商业注册邮箱必填，长度不超过 254 个字符。
- 去除首尾空格，域名部分统一小写，首期按完整邮箱大小写不敏感比较。
- 不擅自删除 Gmail 点号或 `+tag`。
- `normalized_email` 使用数据库唯一约束。
- `User.email` 与 `AccountEmail.email` 由账户 Service 同步。
- 登录、找回和验证不得绕开 `AccountEmail` 判断可信邮箱。

### 3.4 登录标识兼容策略

允许原有用户名或已验证邮箱登录。这样既不破坏历史用户习惯，也符合商业软件以邮箱作为恢复渠道的使用方式。邮箱查询必须通过 `AccountEmail.normalized_email`。

### 3.5 密码规则

- 最少 8 个字符，最多 128 个字符。
- 允许空格、Unicode 和常见特殊字符。
- 不静默去除首尾空格，不静默截断。
- 不强制大写、小写、数字和符号的机械组合。
- 调用 Django `validate_password(password, user)`。
- 启用相似度、常见密码和纯数字密码验证。
- 前端提供确认密码、显示/隐藏和规则说明。
- 允许密码管理器自动填充和粘贴。

如果决定严格对齐 NIST SP 800-63B 的单因素密码长度要求，应把最小长度提高到 15；当前默认 8 是兼容性与注册体验优先的产品选择，不应宣称完全符合该项 NIST 要求。商业化开放注册前应结合邮箱验证、登录限流和弱密码检查重新评估是否提高该值。

### 3.6 时限和默认值

| 用途 | 默认有效期/限制 |
|---|---:|
| 注册激活链接 | 24 小时 |
| 密码重置链接 | 30 分钟 |
| 验证邮件重发间隔 | 60 秒 |
| 单邮箱验证邮件 | 24 小时最多 10 封 |
| 待激活账户保留 | 7 天 |
| Token | 单次使用，数据库只保存摘要 |

重发邮件时废弃同用途旧 Token。待激活用户超过 7 天后，仅在没有业务数据、积分和管理员标记时清理。

## 4. 目标业务流程

### 4.1 注册提交

```json
{
  "username": "researcher01",
  "email": "user@example.com",
  "password": "a sufficiently long passphrase",
  "password_confirm": "a sufficiently long passphrase",
  "terms_version": "2026-09-01",
  "privacy_version": "2026-09-01"
}
```

1. 校验注册开关、Content-Type 和请求体大小。
2. 获取经过可信代理规则处理的客户端 IP。
3. 执行 IP、邮箱和全局请求速率限制，成功与失败均计数。
4. Serializer 规范化并验证全部字段和协议版本。
5. 构造临时 User 并执行 Django 密码验证器。
6. 在事务中创建 `is_active=False` 的 User、Profile、零余额积分账户、邮箱身份、验证记录和协议接受记录。
7. 捕获用户名或邮箱唯一冲突，返回稳定字段错误。
8. 事务提交后投递验证邮件任务。
9. 返回“请查收激活邮件”，不自动登录。

首期不要求 `client_request_id`。用户和邮箱唯一约束已能避免重复账户；有经济价值的积分赠送必须使用独立幂等键。

### 4.2 邮箱验证与激活

1. 使用密码学安全随机 Token，数据库只保存摘要、用途、用户、过期和使用时间。
2. 激活服务在事务中锁定用户、邮箱身份和验证记录。
3. 校验 Token 未过期、未使用、用途正确且属于当前用户。
4. 写入 `verified_at`，将 `User.is_active` 更新为 `True`。
5. 使用 `welcome_grant:{user_id}` 作为唯一业务键发放欢迎积分。
6. 将 Token 标记为已使用并写审计事件。
7. 重复访问已成功链接返回幂等成功，不重复赠送。

### 4.3 邮件可靠性

- 在数据库事务提交后投递 Celery 邮件任务。
- 邮件任务允许安全重试，但不重新创建用户或赠送积分。
- 发送失败时保留待激活账户，用户可通过重发接口恢复。
- 记录发送状态、错误分类和最后尝试时间，不记录原始 Token。
- 如果后续出现 Broker 投递丢失，再引入事务 Outbox；首期不提前实现完整 Outbox。

### 4.4 密码找回

1. 用户提交邮箱，无论是否存在都返回一致响应。
2. 对 IP 和规范化邮箱分别限流。
3. 仅向已验证邮箱异步发送短时、单次重置链接。
4. 重置页要求输入两次新密码并执行与注册相同的规则。
5. 更新后使其他有效会话失效并发送通知邮件。
6. 成功后返回常规登录页，不自动登录。

### 4.5 修改邮箱

- 重新验证当前密码。
- 新邮箱通过唯一性校验和邮件验证后才替换可信邮箱。
- 旧邮箱收到变更通知。
- 未来启用 MFA 后，高风险账户可要求更强验证。

## 5. 积分安全与信号改造

1. User 创建信号只用零余额兜底创建 Profile 和 CreditAccount。
2. 信号不得发放任何有经济价值的积分。
3. `billing_service.get_or_create_account()` 缺失兜底时创建零余额账户。
4. 欢迎积分只能由激活服务调用 Billing Service 发放。
5. `CreditTransaction` 增加可为空、数据库唯一的 `idempotency_key`。
6. 欢迎赠送键固定为 `welcome_grant:{user_id}`。
7. 历史流水不强制回填幂等键，新增字段允许 `NULL`。
8. 管理员人工调整继续记录操作者和原因。

初始默认邮箱验证后赠送 200 credits。上线前应结合真实模型成本复核额度，必要时降低额度或限制免费账户可用模型。

## 6. 防刷、限流与可信 IP

### 6.1 推荐初始限流

| 维度 | 建议初始值 | 失败策略 |
|---|---:|---|
| IP 注册请求 | 10 分钟 20 次 | 通用 429 |
| IP 成功账户 | 24 小时 3 个 | 拒绝注册 |
| 邮箱注册/激活请求 | 24 小时 5 次 | 通用 429 |
| 验证邮件发送 | 60 秒 1 次、24 小时 10 次 | 展示大致等待时间 |
| Token 校验失败 | 10 分钟 10 次 | 暂时拒绝 |
| 登录失败：单标识 | 10 分钟 10 次 | 临时延迟或限流 |
| 登录失败：单 IP | 10 分钟 50 次 | 通用 429 |

登录必须分别检查账号/邮箱桶和 IP 桶，不能只使用 `IP + username` 组合键。

### 6.2 Redis 原子性和故障策略

- 使用 Redis Lua、原子 `INCR`/过期时间或成熟的原子限流实现。
- DRF 默认 Throttle 不作为注册和登录安全边界。
- 初期可复用 Redis 实例，但生产使用独立逻辑库和 `account:` Key 前缀。
- 新增 `RATE_LIMIT_REDIS_URL`；生产环境必须显式配置。
- 注册、邮件重发和积分领取在 Redis 不可用时默认拒绝并告警。
- 登录限流 Redis 不可用时可暂时放行，但依赖代理层基础限流并产生高优先级告警，避免故障造成全员无法登录。

### 6.3 可信代理

- 只有 `REMOTE_ADDR` 属于可信代理时才读取转发头。
- Nginx、负载均衡或 CDN 必须覆盖外部请求自带的同名头。
- 明确代理层级、真实 IP 头和取值顺序。
- 测试直连、单层代理、伪造头和多层代理。
- Nginx/CDN 同时配置基础限流，应用限流不是 DoS 防护的唯一层级。

### 6.4 暂缓的风控能力

- 复杂设备指纹。
- 强制所有用户完成 CAPTCHA。
- 外部商业风控评分。
- 手机号或实名身份绑定。
- 按 ASN、地理位置或支付工具建立复杂关联图谱。

CAPTCHA 只保留适配接口和功能开关，实际数据表明普通限流不足时再启用。

## 7. 协议、隐私与数据治理

注册页面至少提供《用户服务协议》《隐私政策》以及主动确认且默认不勾选的必要条款。营销订阅必须独立、可选且默认不勾选。

```text
AgreementAcceptance
├── user_id
├── agreement_type
├── agreement_version
├── accepted_at
├── ip_address
├── user_agent_digest
└── source
```

约束 `user + agreement_type + agreement_version` 唯一。正式文本需要由具备资质的专业人员结合实际运营主体、支付方式、邮件服务、AI 服务和数据处理活动审核。

数据治理要求：

- 不保存密码、原始 Token 或完整 Cookie。
- Admin 默认脱敏展示邮箱和 IP。
- 为失败日志、验证记录和邮件日志设置保存期限与清理命令。
- 跨境邮件、监控、分析或 AI 服务需单独评估个人信息处理要求。
- 注销和业务数据匿名化不属首期注册开发，但规模化运营前需另行形成方案。

## 8. 后台管理与审计

自定义 Django `UserAdmin`，在一个页面展示：

- 用户名、启用状态、管理员权限和最近登录时间。
- 可信邮箱、验证状态和验证时间。
- 平台角色、封禁状态和资源配额。
- 积分余额、累计赠送、累计消耗和最近流水。
- 注册时间、协议版本和接受时间。

人工激活、修改可信邮箱、封禁、积分调整、管理员权限和配额变更必须二次确认并写审计日志。第一版使用 Django Admin，不单独开发运营工作台。

## 9. 代码组织

```text
core/account/
├── __init__.py
├── apps.py
├── admin.py
├── urls.py
├── api/
│   ├── serializers.py
│   ├── responses.py
│   ├── verification_views.py
│   └── views.py
├── models/
│   ├── email.py
│   ├── verification.py
│   └── agreements.py
├── services/
│   ├── registration.py
│   ├── verification.py
│   ├── authentication.py
│   ├── password_reset.py
│   ├── rate_limit.py
│   └── client_ip.py
├── selectors.py
├── tasks.py
├── migrations/
├── management/commands/
└── tests/
```

```text
web/src/features/account/
├── api.js
├── store.js
├── validation.js
├── components/
│   ├── LoginForm.vue
│   ├── RegisterForm.vue
│   ├── PasswordField.vue
│   └── PasswordRequirements.vue
└── views/
    ├── LoginView.vue
    ├── VerifyEmailView.vue
    ├── ForgotPasswordView.vue
    └── ResetPasswordView.vue
```

边界要求：

- API View 只处理 HTTP、权限、限流入口和响应映射。
- Serializer 负责格式、规范化和字段级校验。
- Service 负责事务、幂等、锁和跨模型规则。
- Selector 负责可复用只读查询。
- Task 只负责异步投递，不决定账户激活或积分赠送。
- Billing Service 是积分增减的唯一入口。
- 前端校验只改善体验，后端校验才是安全边界。
- 不创建新的大型 `views.py`、`services.py` 或无业务边界的 `utils.py`。

## 10. Migration 方案

新增 `core.account` 是独立 app，因此第一条 migration 正常命名为：

```text
core/account/migrations/0001_initial.py
```

这不是重写 `core/migrations/0001_initial.py`。修改现有 `core` 积分模型时从当前版本继续：

```text
core/migrations/0022_credittransaction_idempotency_key.py
```

禁止修改任何已经部署的 migration，包括 `core/migrations/0001_initial.py`、`0005...0021` 和 `core.feedback/migrations/0001_initial.py`。

推荐迁移顺序：

1. 只读数据审计。
2. 备份 MySQL 并验证恢复方式。
3. 新增允许 `NULL` 且唯一的积分流水幂等键。
4. 创建基础邮箱身份模型。
5. 创建验证 Token 模型。
6. 为合法历史邮箱回填未验证的 `AccountEmail`。
7. 输出空邮箱、非法邮箱和重复邮箱报告，不自动合并。
8. 管理员处理冲突后开放历史用户邮箱验证。
9. 新注册切换至 `AccountEmail`，保留旧字段兼容读取。

历史用户不会因迁移立即失去登录能力，继续允许用户名登录，并在个人中心提示绑定和验证邮箱。

Migration 只能使用历史模型或稳定纯数据函数；MySQL 唯一约束必须验证字符集、排序规则和锁表影响。

## 11. 环境变量与外部依赖

```dotenv
REGISTRATION_ENABLED=true
ACCOUNT_REGISTRATION_V2_ENABLED=true
REQUIRE_EMAIL_VERIFICATION=true
ACCOUNT_PASSWORD_MIN_LENGTH=8
ACCOUNT_PASSWORD_MAX_LENGTH=128
ACCOUNT_PENDING_RETENTION_DAYS=7

EMAIL_VERIFICATION_TTL_HOURS=24
PASSWORD_RESET_TTL_MINUTES=30
EMAIL_RESEND_INTERVAL_SECONDS=60
EMAIL_DAILY_SEND_LIMIT=10
EMAIL_RESEND_IP_LIMIT=20
EMAIL_TOKEN_FAILURE_LIMIT=10
EMAIL_TOKEN_FAILURE_WINDOW_SECONDS=600

ACCOUNT_RATE_LIMIT_ENABLED=true
RATE_LIMIT_REDIS_URL=redis://127.0.0.1:6379/2
REGISTRATION_IP_REQUEST_LIMIT=20
REGISTRATION_IP_ACCOUNT_LIMIT=3
REGISTRATION_WINDOW_HOURS=24
LOGIN_IDENTIFIER_FAILURE_LIMIT=10
LOGIN_IP_FAILURE_LIMIT=50
TRUSTED_PROXY_IPS=127.0.0.1

EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=
EMAIL_PORT=587
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
EMAIL_USE_TLS=true
EMAIL_USE_SSL=false
ACCOUNT_EMAIL_SENDER_NAME=循证智筛
DEFAULT_FROM_EMAIL='循证智筛 <account@example.com>'
PUBLIC_BASE_URL=https://example.com

SESSION_COOKIE_SECURE=true
CSRF_COOKIE_SECURE=true
SECURE_SSL_REDIRECT=true
SECURE_HSTS_SECONDS=31536000
DJANGO_SECURE_PROXY_SSL_HEADER=HTTP_X_FORWARDED_PROTO,https
```

实现时沿用项目环境变量规范，并同步更新 `.env.example` 与 `docs/operations.md`。任何密钥不得提交到仓库。

## 12. 测试与上线验收

### 12.1 后端与接口测试

- 用户名、邮箱和密码边界及非法格式。
- Django 密码验证器被真实调用。
- 确认密码不一致时不创建数据。
- 邮箱规范化和唯一性。
- 任一步失败不留下半成品账户。
- 信号和积分兜底不赠送免费积分。
- 激活成功只赠送一次。
- 过期、篡改、已使用和被替代 Token 均被拒绝。
- 邮件重试不重新创建验证记录。
- 未激活和封禁用户不能登录。
- 用户名和已验证邮箱均可登录。
- 密码找回不泄露邮箱是否存在。
- 修改密码后旧会话失效。
- 可信代理和伪造转发头。
- 协议版本缺失或过期时拒绝注册。

### 12.2 MySQL、Redis 与并发测试

SQLite 继续用于快速回归，但不能作为并发正确性的唯一证据。生产同类 MySQL 环境必须验证：

- 并发同名请求最多创建一个用户。
- 并发同邮箱请求最多创建一个邮箱身份。
- 重复激活最多产生一条欢迎赠送流水。
- 并发请求不能绕过 Redis 配额。
- Redis 故障时各接口符合预定策略。
- Worker 重启和邮件重试不重复发放积分。

### 12.3 前端测试

- 前后端字段限制一致。
- 确认密码、显示密码和规则提示正常。
- 提交期间禁止重复点击。
- 字段错误、限流和邮件错误正确展示。
- 注册成功进入“查收验证邮件”状态。
- 重发邮件倒计时正常。
- 验证和重置页面处理成功、过期和无效链接。
- 协议可访问且必要确认不默认勾选。

### 12.4 商业上线门槛

- Python 3.12 与 Django 5.2 LTS 环境完整运行。
- 前后端全量测试通过，`manage.py check --deploy` 无关键警告。
- 生产域名全站 HTTPS，Cookie、CSRF 和 HSTS 配置正确。
- 真实 IP 在 CDN、负载均衡和 Nginx 链路下验证正确。
- SPF、DKIM、DMARC、退信和垃圾邮件表现经过真实测试。
- 注册、激活、重发、登录、找回和积分赠送具备端到端测试。
- MySQL/Redis 并发压测不能突破唯一性、限流和赠送幂等。
- 可以监控注册量、激活率、邮件错误、登录攻击和赠送异常。
- 迁移备份、回退步骤、清理命令和客服说明齐备。

## 13. 分阶段实施计划

### 阶段 0：运行时升级与数据审计，3～5 个工作日（已完成）

- Python 3.9 升级至 Python 3.12。
- Django 4.2.30 升级至 Django 5.2 LTS 最新补丁。
- 核对 DRF、Celery、django-celery-results、WhiteNoise、PyMySQL 等依赖。
- 在新虚拟环境中重建依赖锁定文件。
- 修复弃用和兼容问题。
- 运行全部后端、前端、启停和迁移测试。
- 增加账户与积分只读审计命令。
- 完成生产数据库备份与恢复演练。

交付门槛：现有平台在新运行时完整回归，部署文档同步更新。本阶段独立提交，不混入账户功能。

### 阶段 1：注册安全基础与积分解耦，3～5 个工作日（已完成本地验证）

- 创建 `core.account` app 和模块边界测试。
- 创建基础 `AccountEmail` 模型和唯一邮箱身份约束。
- 实现注册 Serializer、统一错误码和请求体限制。
- 实现用户名、邮箱、密码和确认密码校验。
- 调用 Django 密码验证器。
- 建立 Registration Service 和原子创建事务。
- 将 Profile、CreditAccount 创建和欢迎赠送从信号关键路径中解耦。
- 积分账户缺失兜底改为零余额。
- 新增积分流水幂等键。
- 实现可信客户端 IP 获取。
- 实现 Redis 原子注册和登录限流。
- 捕获数据库唯一冲突。
- 增加事务和 MySQL 并发测试。

交付门槛：适合内部或邀请制试用，不建议公开收费。

### 阶段 2：邮箱验证与账户激活，5～7 个工作日（已完成本地及真实 SMTP 验收）

- 在已有 `AccountEmail` 基础上创建验证 Token 模型。
- 完成历史邮箱审计与安全回填。
- 新用户邮箱改为必填。
- 创建待激活用户和单次 Token。
- 接入 SMTP/事务邮件服务及 Celery 重试。
- 实现验证、激活、重发和过期处理。
- 验证后幂等发放欢迎积分。
- 增加待激活账户清理命令。
- 实现前端查收邮件和验证结果页面。

本地已完成增量迁移、真实 SMTP 投递、验证链接激活、未激活登录拦截和欢迎积分幂等发放验收，并已开启 `REQUIRE_EMAIL_VERIFICATION`。生产部署仍应先迁移表结构并保持功能开关关闭，完成生产邮件与域名配置验证后再开启强制邮箱验证。

### 阶段 3：密码找回与账户自助安全，3～5 个工作日（开发及自动化验证已完成）

- 忘记密码申请接口和页面。
- 单次、短时密码重置 Token。
- 通用响应和抗账户枚举处理。
- 密码重置后的会话失效与通知邮件。
- 个人中心修改密码。
- 用户名或已验证邮箱登录。
- 可信邮箱修改与重新验证。
- 旧邮箱变更通知。

已实现对应后端 Service/API、增量 migration、邮件模板、前端找回/重置/邮箱确认页面及个人中心安全组件。密码重置会使既有会话失效；登录态修改密码保留当前会话；邮箱在新地址验证成功前不替换，成功后通知旧邮箱。后端全量测试、前端测试/Lint/构建、迁移漂移检查和 MySQL 并发契约均已通过；使用真实 SMTP 对密码重置、新邮箱确认和旧邮箱通知进行人工端到端验收后，即可将本阶段标记为完整本地验收通过。

交付门槛：形成注册、登录、找回和邮箱维护闭环。

### 阶段 4：协议、Admin、生产安全与上线验收，4～6 个工作日

- 上线经审核的服务协议和隐私政策。
- 创建协议接受模型及对应增量 migration。
- 注册协议确认和版本记录。
- 自定义 Django UserAdmin 与账户 Inline。
- 敏感管理员操作确认和审计。
- 认证日志脱敏、留存和清理。
- 完成生产 Cookie、HTTPS、CSRF、HSTS 和可信代理配置。
- 配置 SPF、DKIM、DMARC 和退信处理。
- 建立注册、邮件、登录攻击和积分异常告警。
- 运行真实域名端到端验收、并发压测、迁移和回退演练。

交付门槛：满足小规模公开商业运营的最低技术条件。

### 工期汇总

| 阶段 | 工期 |
|---|---:|
| 阶段 0 | 3～5 天 |
| 阶段 1 | 3～5 天 |
| 阶段 2 | 5～7 天 |
| 阶段 3 | 3～5 天 |
| 阶段 4 | 4～6 天 |
| 合计 | 18～28 个工作日 |

按一名熟悉项目的全栈开发者估计约 4～6 周。邮件服务审核、发信域名、法律文本、经营主体和支付渠道准备不计入开发工期，应与开发并行推进。

## 14. 发布与回退策略

1. 单独升级 Python/Django，确认现有功能稳定。
2. 部署新增表和可空字段，保持旧注册行为可回退。
3. 部署新的注册 Service，但先关闭强制邮箱验证。
4. 部署邮件、激活和重发能力，在测试域名验证。
5. 开启强制邮箱验证，仅影响新注册用户。
6. 部署密码找回、邮箱修改、协议和 Admin 增强。
7. 完成上线门槛后开放公开注册和收费入口。

回退原则：

- 优先使用向前兼容的增量字段和新表。
- 使用功能开关，不依赖回滚删除表或字段。
- 关闭邮箱验证时不得重新启用信号自动赠送积分。
- 待激活账户和验证记录保留，由恢复后的服务继续处理。
- 欢迎赠送依赖数据库幂等键，部署重试也不会重复发放。

## 15. 开工前默认决策

以下默认值允许阶段 0～1 先行开发：

1. 登录方式：用户名或已验证邮箱均可。
2. 新用户邮箱：必填并验证；历史用户暂不强制，登录后提示绑定。
3. 密码：最少 8 位、最多 128 位，不设机械组合规则。
4. 注册赠送：邮箱验证后赠送 200 credits。
5. 激活链接：24 小时有效。
6. 密码重置链接：30 分钟有效。
7. 待激活账户：7 天后安全清理。
8. Redis：复用实例，使用独立逻辑库和 `account:` Key 前缀。
9. CAPTCHA：默认关闭，仅保留后续接入点。
10. 邮件：优先选择国内事务邮件服务并使用自有域名发信。
11. 协议版本：以最终审核通过的法律文本发布日期为准。

## 16. 暂不纳入本轮实现

- 替换 Django `AUTH_USER_MODEL`。
- 完整六状态账户状态机。
- 强制普通用户 MFA、Passkey 和恢复码。
- 微信、企业微信或其他第三方登录。
- 企业组织、成员席位和 SSO。
- 复杂设备指纹和外部商业风控系统。
- 手机号、身份证或实名身份强绑定。
- 完整注册漏斗数据仓库和独立运营后台。
- 事务 Outbox；只有现有 Celery 投递可靠性不足时再引入。

这些能力应由实际客户类型、攻击数据、付费模式和运营规模驱动，避免一次性过度设计。

## 17. 参考基线

- [Django 官方支持版本](https://www.djangoproject.com/download/)
- [Django 5.2 与 Python 版本要求](https://docs.djangoproject.com/en/5.2/faq/install/)
- [Django：Password management](https://docs.djangoproject.com/en/5.2/topics/auth/passwords/)
- [Django：Customizing authentication](https://docs.djangoproject.com/en/5.2/topics/auth/customizing/)
- [Django REST Framework：Throttling](https://www.django-rest-framework.org/api-guide/throttling/)
- [NIST SP 800-63B：Passwords](https://pages.nist.gov/800-63-4/sp800-63b/passwords/)
- [OWASP Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)
- [OWASP Forgot Password Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html)
- [OWASP Email Validation and Verification Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Email_Validation_and_Verification_Cheat_Sheet.html)
- [中华人民共和国个人信息保护法](https://www.npc.gov.cn/npc/c2/c30834/202108/t20210820_313088.html)
