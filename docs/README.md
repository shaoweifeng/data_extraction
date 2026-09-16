# 文档导航

本目录只保留当前仍需维护的说明。已经完成的设计稿、阶段性报告和被现行文档替代的清单不再保留，历史过程通过 Git 查看。

## 开发入口

| 文档 | 用途 | 维护时机 |
|---|---|---|
| [architecture.md](./architecture.md) | 当前代码边界、依赖方向和产品语义 | 模块边界或核心流程变化时 |
| [api-contract-baseline.md](./api-contract-baseline.md) | 人工可读 API 契约 | 接口字段、权限或错误语义变化时 |
| [openapi.json](./openapi.json) | 机器可读 API 基线 | API 契约变化时 |
| [frontend-integration-test-plan.md](./frontend-integration-test-plan.md) | 部署后的完整前端验收用例 | 功能模块或主流程变化时 |
| [performance-todo.md](./performance-todo.md) | 尚未完成的性能改造 | 完成基准测试或性能任务后 |

## 部署与商业化

| 文档 | 用途 | 维护时机 |
|---|---|---|
| [operations.md](./operations.md) | 启停、维护模式、备份和故障恢复 | 部署方式或运维命令变化时 |
| [account-production-readiness.md](./account-production-readiness.md) | 注册与账户现状、全部外部配置、生产上线验收 | 账户功能、域名、邮件、主体或上线状态变化时 |
| [commercialization-roadmap.md](./commercialization-roadmap.md) | 收费试点、自助支付和机构化路线 | 商业模式、价格或支付范围确定后 |

## 文档维护规则

1. 已经实现的功能只描述当前行为，不继续保留开发阶段流水账。
2. 域名、邮件、法律主体、第三方处理者和账户生产验收统一维护在 `account-production-readiness.md`。
3. `.env.example` 是环境变量模板；本文档只说明用途和验收标准，不复制真实密钥。
4. API 变更同时更新 Markdown 契约和 `openapi.json`。
5. 历史设计和旧结论需要追溯时使用 Git，不在 `docs/` 中维护多个相互冲突的版本。
