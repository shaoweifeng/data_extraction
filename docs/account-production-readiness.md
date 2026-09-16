# 注册、账户与生产上线手册

> 状态：账户体系主体工程已完成，本地功能已经验收；正式域名、经营主体、发信身份、生产安全和法律终审尚未完成。  
> 最后更新：2026-09-16

本文档是注册与账户体系的唯一现行说明，同时集中记录所有必须由经营主体或部署人员完成的事项。

## 1. 当前已经实现

- Python 3.12、Django 5.2 LTS 运行基线。
- 新版注册：必填邮箱、用户名唯一性、8～128 位密码校验、请求体限制。
- 独立可信邮箱身份，支持用户名或已验证邮箱登录。
- 邮箱激活、验证邮件重发、过期 Token 和待激活账户清理。
- 邮箱验证成功后幂等发放欢迎积分；创建用户不再由信号直接赠送积分。
- Redis 原子限流，覆盖注册、登录失败、验证邮件、密码重置和邮箱变更。
- 忘记密码、登录态修改密码、修改可信邮箱和旧邮箱通知。
- 服务协议、隐私政策独立确认，保存协议版本、正文摘要和接受记录。
- Django Admin 汇总用户、可信邮箱、Profile、积分和协议记录。
- 封禁/解封二次确认、管理员操作原因及安全审计。
- 脱敏账户安全事件、保留期清理和异常阈值检查命令。

主要数据结构位于 `core.account`，继续使用 Django 内置 `auth.User`，不替换 `AUTH_USER_MODEL`。可信邮箱以 `AccountEmail` 为准，`auth.User.email` 仅作兼容展示。

## 2. 当前业务规则

| 项目 | 当前规则 |
|---|---|
| 登录标识 | 用户名或已验证邮箱 |
| 密码长度 | 最少 8 位，最多 128 位，并执行 Django 密码验证器 |
| 激活链接 | 24 小时有效，单次使用 |
| 密码重置链接 | 30 分钟有效，单次使用 |
| 邮箱变更链接 | 24 小时有效，验证成功前不替换旧邮箱 |
| 验证邮件重发 | 默认间隔 60 秒，单邮箱每日最多 10 次 |
| 待激活账户 | 默认保留 7 天，清理前必须预览 |
| 欢迎积分 | 邮箱验证成功后发放，使用幂等键防止重复 |
| 安全事件 | 默认保留 180 天，内容经过脱敏或摘要处理 |

功能开关关系：

- `REGISTRATION_ENABLED` 控制是否允许注册。
- `ACCOUNT_REGISTRATION_V2_ENABLED` 控制是否使用新版注册链路。
- `REQUIRE_EMAIL_VERIFICATION` 只能在新版注册链路开启后启用。
- `ACCOUNT_RATE_LIMIT_ENABLED` 在公开注册环境必须开启，并配置可用的 `RATE_LIMIT_REDIS_URL`。

## 3. 尚未完成的真实配置

以下各项未完成前，只能视为本地或受控环境通过，不能宣称已经满足公开商业运营条件。

### 3.1 经营主体与法律文本

- [ ] 确定实际经营主体，统一营业执照、域名实名、备案、支付商户、合同和开票主体。
- [ ] 填写 `LEGAL_OPERATOR_NAME`、`LEGAL_CONTACT_EMAIL`、`LEGAL_CONTACT_ADDRESS`。
- [ ] 由中国执业律师结合实际主体、客户类型、收费及退款规则终审服务协议和隐私政策。
- [ ] 确认是否面向个人消费者、是否提供自动续费、如何退款和开票。
- [ ] 决定存量用户是否需要重新确认新版本协议。
- [ ] 确认平台是否涉及临床决策、医疗器械、人体研究或其他强监管用途。

当前协议正文位于 `core/account/legal/`。正文发生实质变化时必须创建新版本文件并提升 `ACCOUNT_LEGAL_VERSION`，不能覆盖旧正文后继续使用原版本号。

### 3.2 域名、备案与 HTTPS

- [ ] 使用经营主体长期控制的账号购买并实名域名。
- [ ] 根据服务器所在地和收费性质确认 ICP 备案或经营许可要求。
- [ ] 如适用，完成公安联网备案及网络安全等级保护相关评估。
- [ ] 配置生产 DNS、TLS 证书和全站 HTTPS。
- [ ] 设置 `PUBLIC_BASE_URL=https://实际域名`。
- [ ] 设置 `DJANGO_ALLOWED_HOSTS` 和 `CSRF_TRUSTED_ORIGINS`，不使用通配符。
- [ ] 设置生产前端来源 `CORS_ALLOWED_ORIGINS`；同源部署时避免不必要的跨域来源。
- [ ] 确认 Nginx/CDN 正确传递 `X-Forwarded-Proto`。
- [ ] 填写 `TRUSTED_PROXY_IPS`，并验证外部请求不能伪造转发头绕过限流。
- [ ] 确认 HTTPS 稳定后开启 `SECURE_SSL_REDIRECT`，先以较短 HSTS 时间观察，再逐步提高。
- [ ] 只有所有子域名都会长期支持 HTTPS 时才开启 HSTS 子域名；谨慎使用 preload。

推荐域名结构可从单域名开始：

```text
https://example.com          官网与业务前端
https://example.com/api/     后端 API
https://example.com/admin/   Django Admin，仅授权人员访问
```

在流量或组织边界确有需要前，不必提前拆分 `www`、`app` 和 `api` 子域名。

### 3.3 正式邮件服务

- [ ] 选择事务邮件服务和自有发信域名，不使用个人邮箱作为长期生产方案。
- [ ] 配置 SMTP 主机、端口、账号和授权密钥。
- [ ] 配置 `DEFAULT_FROM_EMAIL` 与 `ACCOUNT_EMAIL_SENDER_NAME`。
- [ ] 完成 SPF、DKIM、DMARC，并验证 DNS 记录生效。
- [ ] 测试 QQ、163、企业邮箱等主要收件方的送达和垃圾箱表现。
- [ ] 建立退信、投诉和失效邮箱的处理方式。
- [ ] 确认 Celery worker 使用最新环境变量并能真实发信。
- [ ] 端到端验证激活、密码重置、新邮箱确认和旧邮箱通知。

生产环境必须使用 SMTP backend，不能继续使用 console 或 locmem backend。

### 3.4 Redis、MySQL 与生产安全

- [ ] 为账户限流配置稳定的 Redis 地址，建议与 Celery 使用不同逻辑库或独立实例。
- [ ] 在与生产版本一致的 MySQL 和 Redis 中执行注册及积分并发测试。
- [ ] 使用高强度随机 `DJANGO_SECRET_KEY`，不得提交到 Git。
- [ ] 设置 `APP_ENV=production`、`DJANGO_DEBUG=False`。
- [ ] 开启新版注册、强制邮箱验证和账户限流。
- [ ] 检查 Session/CSRF Secure Cookie、CSRF 来源和 HSTS。
- [ ] 限制 Admin 的网络入口和管理员账号，生产管理员使用独立强密码。
- [ ] 对数据库、用户文件和 `FEEDBACK_UPLOAD_ROOT` 建立一致性备份。
- [ ] 验证备份恢复、migration 前滚和应用回退流程。

### 3.5 第三方处理者与数据边界

生产开放前按实际供应商填写下表，并同步进隐私政策。不得保留“待填写”后直接上线。

| 类型 | 服务商/产品 | 处理数据 | 处理地域 | 保存期限 | 是否出境 | 审查状态 |
|---|---|---|---|---|---|---|
| 云主机/CDN | 待填写 | 账户、项目、访问日志 | 待填写 | 待填写 | 待评估 | 待完成 |
| 数据库/备份 | 待填写 | 平台业务数据 | 待填写 | 待填写 | 待评估 | 待完成 |
| 邮件服务 | 待填写 | 邮箱、事务邮件正文 | 待填写 | 待填写 | 待评估 | 待完成 |
| AI 模型 | DeepSeek（按实际） | 用户提交的任务内容 | 待填写 | 待填写 | 待评估 | 待完成 |
| AI 模型 | 豆包（按实际） | 用户提交的任务内容 | 待填写 | 待填写 | 待评估 | 待完成 |
| AI 模型 | 通义千问（按实际） | 用户提交的任务内容 | 待填写 | 待填写 | 待评估 | 待完成 |
| 监控/告警 | 待填写 | 错误、性能和脱敏安全日志 | 待填写 | 待填写 | 待评估 | 待完成 |

如存在个人信息出境，必须在启用相关供应商前完成必要告知、单独同意和适用的法定程序。

### 3.6 监控与运营

- [ ] 将 `account_security_status --json --fail-on-alert` 接入真实告警系统。
- [ ] 监控注册量、激活率、邮件失败、登录攻击、欢迎积分异常和 Redis 故障。
- [ ] 明确安全事件、操作日志、项目数据、备份、订单和协议记录的保存期限。
- [ ] 建立用户访问、更正、导出、注销和删除请求的人工处理流程。
- [ ] 准备客服说明、故障通知和数据安全事件响应联系人。

## 4. 生产环境关键变量

真实值写入服务器的受限环境文件或 Secret Manager，不要写进仓库。

```dotenv
APP_ENV=production
DJANGO_DEBUG=False
DJANGO_SECRET_KEY=<随机长密钥>
DJANGO_ALLOWED_HOSTS=example.com
CSRF_TRUSTED_ORIGINS=https://example.com
CORS_ALLOWED_ORIGINS=https://example.com

REGISTRATION_ENABLED=true
ACCOUNT_REGISTRATION_V2_ENABLED=true
REQUIRE_EMAIL_VERIFICATION=true
ACCOUNT_RATE_LIMIT_ENABLED=true
RATE_LIMIT_REDIS_URL=redis://:<密码>@127.0.0.1:6379/2
TRUSTED_PROXY_IPS=<实际反向代理 IP 或 CIDR>

PUBLIC_BASE_URL=https://example.com
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=<SMTP 主机>
EMAIL_PORT=465
EMAIL_HOST_USER=<SMTP 用户>
EMAIL_HOST_PASSWORD=<SMTP 授权密钥>
EMAIL_USE_TLS=false
EMAIL_USE_SSL=true
DEFAULT_FROM_EMAIL='循证智筛 <account@example.com>'

ACCOUNT_LEGAL_VERSION=<律师审核后的版本日期>
LEGAL_OPERATOR_NAME=<营业执照主体全称>
LEGAL_CONTACT_EMAIL=<客服或隐私联系邮箱>
LEGAL_CONTACT_ADDRESS=<有效联系地址>

SECURE_SSL_REDIRECT=true
SECURE_HSTS_SECONDS=<先小后大>
SECURE_HSTS_INCLUDE_SUBDOMAINS=false
SECURE_HSTS_PRELOAD=false
```

SMTP 的 TLS/SSL 和端口必须以邮件服务商文档为准，`EMAIL_USE_TLS` 与 `EMAIL_USE_SSL` 不能同时开启。完整变量及开发默认值以仓库根目录 `.env.example` 为准。

## 5. 部署与验收顺序

1. 确认经营主体、域名和法律文本。
2. 备份 MySQL、用户文件、任务目录和反馈附件。
3. 部署代码和依赖，保持公开注册关闭。
4. 查看并执行增量 migration。
5. 配置 HTTPS、可信代理、SMTP 和 Redis。
6. 运行 Django 系统检查。
7. 在预发布环境完成全流程和并发验收。
8. 开启新版注册、强制邮箱验证及限流。
9. 小流量观察邮件、登录、积分和告警后再公开入口。

```bash
python manage.py check
python manage.py migrate --plan
python manage.py migrate
python manage.py showmigrations account
python manage.py check --deploy
python manage.py audit_accounts --fail-on-issues
python manage.py account_security_status --minutes 15 --json --fail-on-alert
```

预发布验收至少覆盖：

- 注册、重复用户名/邮箱、弱密码和限流。
- 激活邮件重发、过期、单次使用和欢迎积分幂等。
- 用户名/邮箱登录、错误凭据与攻击限流。
- 忘记密码、旧会话失效、登录态修改密码。
- 新邮箱确认后切换、旧邮箱通知。
- 协议页面、独立勾选、版本和摘要记录。
- 管理员封禁/解封、审计、用户删除及兑换码展示。
- Redis 故障策略、MySQL 并发、备份恢复和应用回退。

## 6. 例行维护命令

所有删除命令先不带删除参数预览。

```bash
# 账户数据审计
python manage.py audit_accounts
python manage.py audit_accounts --json

# 清理过期待激活账户
python manage.py cleanup_pending_accounts
python manage.py cleanup_pending_accounts --delete

# 清理到期安全事件
python manage.py cleanup_account_security_events
python manage.py cleanup_account_security_events --delete

# 查看账户安全状态
python manage.py account_security_status --minutes 15 --json --fail-on-alert
```

平台进程启停、维护模式、数据库备份与恢复详见 [operations.md](./operations.md)。

## 7. 暂不实现

以下内容按真实业务需求另行立项，不作为当前账户体系的上线阻塞项：

- 替换 Django `AUTH_USER_MODEL`。
- 完整账户状态机。
- 强制 MFA、Passkey 和恢复码。
- 微信、企业微信或其他第三方登录。
- 组织、成员、席位和 SSO。
- 复杂设备指纹和外部商业风控。
- 事务 Outbox。

支付、套餐、机构版和后续商业化顺序见 [commercialization-roadmap.md](./commercialization-roadmap.md)。
