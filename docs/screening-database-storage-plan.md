# 文献初筛数据库化与上传安全改造方案

> 文档基线：`v1.5.0`（2026-09-23）
>
> 本次更新已纳入文献解析诊断、Elsevier/Embase XML、索引删除统计同步、质量评价结果维度修复，以及自动去重详情分页需求。

## 当前实施状态（2026-09-29）

本轮已完成阶段 12 本地工程验收；下一步进入阶段 13 目标服务器复验和上线切换：

- **第一步已完成：真实样本与字段契约基线。** 根目录 `meta_project/Screen_input` 的 9 个索引文件和 `meta_project/QA_input` 的 38 个全文样本已形成 SHA-256、格式签名、字段覆盖、文件级诊断和标题去重基线。当前索引样本稳定解析 3,170 条，按 `v1.5.0` 标题规范化规则得到 814 个重复组、933 条重复记录、2,237 条保留记录。
- 基线文件位于 `core/tests/fixtures/regression/meta_project_baseline.json`；通过 `python manage.py build_screening_regression_baseline` 可显式重建。自动化测试会在样本存在时逐项比较，样本或解析语义意外变化会直接失败。
- **第二步已完成：核心数据库结构。** 已新增文献集、导入批次/文件/诊断、标准化文献、去重运行/重复组/成员、AI 初筛运行/结果模型，并为 `ManualReview` 和 `QAReference` 增加真实文献外键。
- 使用新增迁移 `core/migrations/0023_screening_database_storage.py`，未修改任何历史迁移；关键唯一约束、修订可见性和 Admin 注册已有自动化测试。
- **阶段 11 已完成：旧文件主数据路径清理。** `ManualReview.source_xml` 与 `QAReference.source_ref_id` 已由迁移 `0030_remove_legacy_screening_file_keys` 删除；审阅、导出和质量评价只接受数据库运行及真实文献外键。
- **第三步已完成：上传入口和批次状态机。** 初筛索引改为一次请求原子上传多个文件，统一执行文件数/大小/格式签名/哈希/权限/并发/频率校验；原文件进入不可公开访问的私有目录，并在事务提交后投递仅包含本批 `file_ids` 的解析任务。
- 批次支持取消、失败、重试、派发失败保留原文件和超期失败文件清理；删除已发布来源会创建独立 `remove` 操作并递增文献集修订号，其他来源的文件级统计和解析产物保持不变。前端会展示上传、解析及批次发布状态。
- 新增索引已不会重新解析旧索引；专项回归覆盖原子上传、越权、并发、限流边界、任务派发失败、取消/重试、清理及连续新增/删除来源，共 10 个场景。
- **第四步已完成：统一迭代解析器。** NBIB、ENW/TXT、CIW、RIS、BibTeX 和 XML 均改为逐记录产出；XML 同时拒绝 DTD/实体并限制嵌套深度。DOCX 已消除 `lines/full_text/records` 多份副本，上传入口继续限制压缩成员数和解压后总量。
- 解析 Worker 使用单遍记录流完成统一字段上限校验、诊断汇总及兼容 XML 写出；错误样例受 `SCREENING_IMPORT_MAX_REPORTED_ERRORS` 限制，但总错误/警告计数不截断。乱码不再通过 `errors=ignore` 静默丢弃。
- 真实样本回归仍稳定解析 3,170 条，字段覆盖、文件级诊断、814 个重复组和 933 条重复记录均与 `v1.5.0` 基线一致。
- **第五步已完成：数据库批量导入与原子发布。** 新解析记录按配置批次写入 `ScreeningReference`，保存稳定来源位置、规范化 DOI、题名哈希和记录哈希；写入行在 `target_revision` 发布前对当前文献集不可见。
- 发布前同时核对文件报告、批次汇总、逐文件数据库行数、当前文献集缓存计数和数据库实际计数；最终短事务只锁定批次/文献集并切换修订号。失败、取消、容量超限和修订冲突均清理未发布文献。
- 删除来源文件会在新修订号下批量标记该来源文献的 `removed_revision`，不会重写其他来源。项目总篇数上限同时计算既有文献与本次新增文献。
- **第六步已完成：数据库化去重与详情分页。** 去重器按当前文献集修订从 `ScreeningReference` 游标读取规范化题名哈希候选，并使用完整规范化题名二次校验；不再复制或打开解析阶段的单篇 XML 来判断重复。
- 每次去重创建绑定 `corpus_revision` 的 `DedupRun`，重复组与成员完整保存到数据库，不物理删除重复文献；发布前再次校验修订号、文献总数和结果计数，失败、取消或修订冲突会清理本次未发布关系。
- 步骤 metadata 只保存统计摘要和 `dedup_run_id`，不再包含 `duplicate_details`，也不再截断为前 100 组。重复组默认每页 20、最大 100，成员默认每页 50、最大 200；前端按需加载、支持翻页并取消过期请求，第 101 组可以正常访问。
- 解析和去重任务均不再生成单篇或合并兼容 XML；AI 待筛列表直接按数据库分页读取题名，AI 结果不再写单篇 JSON。
- **第七步已完成：AI 初筛结果数据库化。** AI 运行绑定当前 `corpus_revision` 和 `dedup_run`，直接从 `ScreeningReference` 分批领取文献；每篇结果通过 `(screening_run, reference)` 唯一约束写入 `ScreeningResult`，不再生成单篇结果 JSON。
- Worker 停止后会释放处理中记录并恢复到同一次运行；失败记录更新原行并按 `SCREENING_AI_MAX_ATTEMPTS`（默认 3）重试。模型未配置或调用失败时保存明确错误，不再用随机 mock 结论冒充真实结果。
- 运行结束前再次校验文献集修订和去重指针；计费流水使用运行级幂等键，并与运行完成处于同一事务，重复完成不会重复扣费，修订冲突不会留下孤立账单。
- **第八步已完成：人工审阅 API 和前端切换。** 新链路以 `(screening_run, reference)` 作为审阅身份，并由 MySQL 可实际执行的唯一约束保证同一批次同一文献只有一条人工审阅；决定和备注写入均锁定对应结果行，避免并发覆盖。
- 人工审阅列表、检索、筛选、排序和统计均在数据库完成；列表只返回轻量字段，摘要、作者、链接、AI 理由和多模型明细在用户选中文献后按 `reference_id` 单独加载。分页不再打开单篇 XML/JSON。
- 列表、详情、统计、决定、备注和完成操作均绑定明确的 `screening_run` 与 `corpus_revision`。文献集变化后旧批次仍可查看，但后端以 `409 screening_run_stale` 拒绝决定、备注及完成操作，前端同步显示历史版本只读提示。
- 新人工审阅操作日志记录项目、运行 ID、文献 ID 及决定变更前后值；备注日志只记录长度和条数，不复制备注正文。数据库列表及导出查询已按运行隔离，跨项目猜测运行或文献 ID 返回 404。
- `source_xml` 审阅端点、Serializer 字段、文件扫描 Selector、旧输入选择器和旧结果仓储已删除，不再维护数据库/文件双读。
- **第九步已完成：导出和质量评价衔接。** 当前数据库初筛运行通过同一个有界批次迭代器解析最终决定，Excel、RIS 和 XML 在单次遍历中流式生成；XML 已加入前端历史下载区。
- 质量评价导入只接受与当前文献集修订、当前去重结果匹配的最新已完成初筛运行。人工决定按运行隔离并优先于 AI；待定、分歧和排除项不会进入质量评价。`QAReference` 保存文献快照、`source_reference`、来源运行及导入时最终决定，后续新运行不会改写既有来源语义。
- 去重语义由 `ScreeningRun` 输入集保证：被判为重复的成员没有本次 `ScreeningResult`，不会在质量评价导入中再次出现。多次 AI 运行按“当前修订下最新完成运行”选择，不混合不同运行结果。
- 质量评价图表和 Excel 已复用统一的动态方法 schema 与结果映射；偏倚风险和适用性独立取值，`pending` 与 `na` 分别表达“待确认”和“不适用”，QUADAS-2、NOS 及无适用性领域方法均有专项回归。
- 执行器生成产物统一通过产物服务分块写入私有存储；工作区过期清理由同一服务处理，保留期使用 `TASK_WORKSPACE_RETENTION_DAYS`（默认 30 天）。文件下载继续经过项目鉴权接口。
- **阶段 12 本地工程验收已完成。** 已补齐限制边界、恶意输入、真实 RIS 流式解析、10 万篇数据库写入/去重/分页/统计，以及 XLSX、RIS、XML 单遍流式导出的可重复基准。目标服务器并发、故障和备份恢复演练作为阶段 13 的上线门禁保留，不用本地开发机数据替代生产结论。

## 1. 文档目的

本文用于指导“文献初筛从单篇 XML/JSON 文件存储改为数据库存储”的完整改造，并同时补齐大批量上传、异常文件、并发、回滚和资源滥用保护。

本方案按以下前提设计：

- 不迁移、不兼容现有项目中的单篇 XML、单篇 AI 结果 JSON 和既有人工审阅数据。
- 数据库迁移仍必须通过新增 Django migration 完成，不修改历史 migration。
- 新流程启用前，可以清空开发/测试环境中的旧业务数据；生产执行时必须先备份。
- 单次导入最多 100 个文件、总上传量 200 MiB、最多 100,000 篇文献。
- 100,000 篇是容量上限，不代表所有格式都可以继续使用全量内存解析。
- 后续重构不为当前单篇 XML/DataFile 方案建设长期兼容层；但必须保留当前已验证的解析字段、诊断语义和用户可见统计。

## 2. 核心结论

### 2.1 哪些内容进入数据库

以下内容应成为数据库中的结构化主数据：

- 每一篇文献的题名、作者、摘要、年份、期刊、DOI、URL 等标准字段。
- 文献来源文件、来源序号、规范化哈希和去重关系。
- 文献集修订版本、导入操作、文件级解析统计和结构化诊断问题。
- 去重运行、重复组、保留项和重复成员，支持数据库分页查看完整详情。
- 每次 AI 初筛运行及其模型配置快照。
- 每篇文献的 AI 判断、理由、多模型明细、用量和错误状态。
- 人工复核结论、理由、备注和操作人。
- 文献集修订、导入操作的状态、文件级统计和错误报告。

完成后，运行时查询不再依赖逐篇打开 XML/JSON 文件，列表、筛选、统计、分页和导出均直接查询数据库。

数据库化后的项目文献集使用单调递增的 `revision` 表达内容变化。新增或删除一个索引只处理受影响的来源文件和文献，并递增修订号；不能再因为新增个位数文献而重新解析、重新编号和重新落库全部既有文献。

### 2.2 哪些内容仍然存文件

以下内容不适合直接作为数据库大字段保存：

| 内容 | 推荐存储 | 原因 |
| --- | --- | --- |
| 用户上传的 RIS、NBIB、XML、BibTeX 等原始索引文件 | 私有文件存储或对象存储，数据库保存 `DataFile` 元数据 | 便于审计、重放、下载和生命周期管理 |
| 单篇 XML | 不再生成 | 已由结构化文献表替代 |
| 单篇 AI 结果 JSON | 不再生成 | 已由筛选运行表和结果表替代 |
| 合并 XML、RIS、Excel 等导出文件 | 按需生成到私有文件存储 | 它们是导出产物，不是查询主数据 |
| 质量评价全文 PDF | 私有文件存储或对象存储，数据库保存关联与元数据 | 大二进制会放大数据库、备份和复制成本 |
| PDF 提取文本 | 独立私有文本产物，或在有严格长度上限时放专用表 | 避免把不受控全文塞入核心业务表 |

因此，“初筛结构化数据进数据库”并不等于“所有文件二进制都进数据库”。数据库负责关系、状态和可查询字段；文件/对象存储负责原始文件与大体积产物。

### 2.3 本次复审确定的关键决策

- 删除原方案中“每次上传形成完整新数据批次并切换 `active_reference_batch`”的设计，改为“项目文献集修订号 + 增量导入操作”。
- 新增索引只解析和写入本次来源；删除索引只软移除该来源文献，其他来源的文献和解析统计不重建。
- 单篇 XML 的全局流水号不再承担身份或排序职责；文献主键稳定，排序是独立字段。
- 解析诊断从输入 `DataFile.metadata + JSON` 迁移为导入文件统计和结构化问题记录，保留 `v1.5.0` 的用户体验。
- 去重详情从步骤 metadata 中移出，使用去重运行、重复组和成员表；前端通过独立接口分页加载全部结果。
- 去重分页默认值和最大值属于 API 产品契约，固化在代码并测试，不增加可被随意放大的环境变量。
- 质量评价 PDF 仍然留在私有文件/对象存储；本次数据库化只改变结构化文献、筛选、去重和关联数据。

## 3. `v1.5.0` 当前基线与剩余问题

### 3.1 已完成且新方案必须保留的能力

截至 `v1.5.0`，现有文件存储链路已经具备以下能力，数据库化不能造成回退：

1. 支持 RIS、BibTeX、NBIB/Medline、CIW、ENW/TXT、DOC/DOCX、EndNote XML、内部 XML，以及 Elsevier/Embase `bibdataset/item` XML。
2. XML 解析能够处理命名空间；Embase 能提取题名、作者、期刊、年份、摘要、DOI、PUI、卷期页码等字段，并按作者序号消除不同机构分组造成的重复作者。
3. 解析诊断能够分别统计源文件检测条目数、成功解析数、异常跳过数、摘要缺失数、错误数和警告数。
4. 诊断问题能够记录文件、条目位置、行号、来源标识、题名、错误码和修复建议；BibTeX 非法 citation key 等问题可以定位到具体条目。
5. 未解析出任何可用文献时任务会明确失败，不再以“成功 0 篇”进入去重步骤。
6. 文件级摘要保存在输入文件 metadata，完整诊断报告作为独立产物按需读取。
7. 删除一个输入索引时，仅删除该索引的诊断报告并保留其他索引的文件级统计；解析/去重产物仍按旧架构整体失效。
8. 质量评价已经区分偏倚风险和适用性维度，并根据评价方法动态生成图表与 Excel 字段；`pending` 表示“待定”而不是“不适用”。

### 3.2 仍需通过数据库化解决的问题

当前初筛流程仍包含如下文件级依赖：

1. 解析任务为每篇文献生成一个 XML，并为每个 XML 创建一条 `DataFile`。
2. 去重任务复制并逐个打开 XML，再为保留文献生成新 XML。
3. AI 初筛以 XML 文件名 `source_xml` 作为文献标识。
4. 每篇 AI 结果保存为一个 JSON 文件和一条 `DataFile`。
5. `ManualReview` 使用字符串 `source_xml` 关联文献，而不是数据库外键。
6. 人工审阅列表和统计仍需扫描、打开大量 JSON/XML 后才能分页。
7. 导出和质量评价导入仍然通过 `source_xml` 拼装数据。

自动去重详情还存在独立的展示与数据契约问题：

- 去重任务把详情直接放进 `StageStep.metadata`，项目接口会随步骤信息一次性返回。
- 前端点击“展开”不请求接口，而是一次性 `v-for` 渲染已返回的所有详情。
- 列表只有 `max-height: 24rem` 的内部滚动，没有页码或加载更多。
- 后端通过 `duplicates[:100]` 只保留前 100 个重复组；标题显示实际总组数，但第 101 组以后无法查看，去重报告本身也已经丢失这些详情。
- 单个重复组的成员数量没有上限，极端情况下仍会形成大响应和大量 DOM。

在 100,000 篇规模下，即使 XML 解析本身可以流式进行，单篇 XML 加单篇 JSON 也会产生约 200,000 个业务文件，带来目录遍历、inode、备份、部署同步、查询、清理和并发一致性问题。因此本次改造必须同时处理文献主数据、去重详情和 AI 结果，不能只把 XML 换成数据库后继续保留单篇结果 JSON 或截断的去重报告。

### 3.3 已冻结的旧存储依赖清单

后续阶段迁移消费者时以此清单逐项清零，避免只改主流程而遗漏导出、质量评价或前端：

| 依赖类型 | 当前主要位置 |
| --- | --- |
| 单篇 XML 生成、复制和读取 | `core/screening/executors/parse_handler.py`、`dedup_handler.py`、`ai_screen_handler.py`、`input_selector.py`、`selectors.py` |
| 单篇 AI JSON 与 `screening_result_*` | `core/screening/services/result_repository.py`、`review_query.py`、`review_service.py`、`selectors.py` |
| `source_xml` 人工审阅身份 | `core/screening/api/review_views.py`、`api/serializers.py`、`review_service.py`、`core/models.py` |
| 文件式导出 | `core/screening/executors/export_handler.py`、`exporters/excel.py`、`exporters/ris.py` |
| 质量评价导入关联 | `core/quality/services/reference_service.py` |
| 索引上传/删除后的产物失效 | `core/api/file_views.py`、`core/artifacts/types.py` |
| 去重详情一次性 metadata | `core/screening/executors/dedup_handler.py`、`web/src/features/screening/components/steps/StepDedup.vue` |
| AI/人工审阅前端的文件名契约 | `StepAiScreen.vue`、`StepReview.vue` 及对应 screening API |

自动化测试、历史 migration 和 Admin 中出现相同关键词不属于运行时消费者，但在最终删除旧字段时仍需同步更新。

## 4. 目标数据模型

模型名可以在实现时按现有模块规范调整，但职责和关联关系应保持清晰。

### 4.1 `ScreeningCorpus`：项目文献集与修订号

每个文献初筛项目拥有一个文献集状态对象，不再把“某次上传批次”直接等同于完整文献集。

建议字段：

- `project`：一对一关联项目。
- `revision`：从 0 开始单调递增的当前修订号。
- `active_reference_count`、`active_source_file_count`。
- `last_import_batch`、`last_dedup_run`。
- `created_at`、`updated_at`。

设计要求：

- 新增或删除索引成功发布时，在短事务内递增 `revision`。
- AI 初筛、人工审阅、去重和导出运行都必须记录其读取的 `corpus_revision`。
- 任务开始时记录基准修订号，发布前再次校验；期间文献集发生变化时，旧任务不得覆盖新状态。
- 解析失败不能递增修订号，也不能破坏当前可用文献集。

修订号只表达业务可见数据版本，不要求复制全部文献。文献使用引入/移除修订号判断在某一版本是否有效，从而避免新增个位数文献时复制或重建全部数据。

### 4.2 `ReferenceImportBatch`：导入操作

每次新增、删除或完整重建索引对应一个可审计操作，而不是完整数据快照。

建议字段：

- `project`、`corpus`、`created_by`。
- `operation`：`add`、`remove`、`rebuild`。
- `status`：`uploaded`、`validating`、`importing`、`ready`、`publishing`、`completed`、`failed`、`cancelled`。
- `base_revision`、`target_revision`、可空 `published_revision`。
- `file_count`、`total_bytes`。
- `discovered_count`、`accepted_count`、`rejected_count`。
- `missing_abstract_count`、`warning_count`、`error_count`。
- `config_snapshot`、`parser_version`。
- `started_at`、`finished_at`、`published_at`、`created_at`、`updated_at`。

设计要求：

- 同一项目同一时刻只能有一个会修改文献集的活动批次。
- 新增批次只解析本次文件；删除批次只处理被删除来源对应的文献。
- 状态切换由服务层统一处理，支持取消、审计和幂等重试。
- 失败批次保留有限期诊断，但其暂存文献不可进入当前文献集。

### 4.3 `ReferenceImportFile` 与 `ReferenceImportIssue`：文件级诊断

`ReferenceImportFile` 连接导入操作与原始 `DataFile`，承接 `v1.5.0` 已经验证的文件级统计语义。

建议字段：

- `import_batch`、`source_file`、`original_filename`、`sha256`。
- `source_format`：明确区分 `ris`、`bibtex`、`nbib`、`enw`、`ciw`、`docx`、`endnote_xml`、`embase_xml`、`internal_xml` 等。
- `parse_status`：`pending`、`validating`、`parsing`、`parsed`、`warning`、`failed`。
- `introduced_revision`、可空 `removed_revision`、可空 `removed_by_batch`。
- `detected_count`、`parsed_count`、`skipped_count`、`missing_abstract_count`。
- `warning_count`、`error_count`、`issues_truncated`。
- `started_at`、`finished_at`、`created_at`、`updated_at`。

`ReferenceImportIssue` 建议字段：

- `import_file`、`severity`、`code`。
- `record_position`、`line_number`、`source_identifier`。
- `title_preview`、`message`、`suggestion`。
- `created_at`。

要求：

- 每个文件最多持久化配置允许的错误样例数，但必须保存真实总错误数和 `issues_truncated`。
- 删除一个来源文件只写入其 `removed_revision/removed_by_batch` 及其文献的移除修订，不覆盖原始解析状态，也不得清除其他文件的统计和诊断。
- 文件列表汇总直接聚合当前有效 `ReferenceImportFile`，不再读取最近一次 Task 的旧总数。
- 解析得到 0 条可用文献时文件必须为 `failed`；整个批次是否失败由 `ALLOW_PARTIAL` 和其他文件结果共同决定。

### 4.4 `ScreeningReference`：标准化文献

每篇导入文献对应一行。

建议字段：

- 归属：`project`、`corpus`、`import_batch`、`import_file`、`source_file`。
- 定位：稳定 `id`、`source_record_index`、`source_record_key`、`source_identifier`。
- 版本：发布前可空、发布后必填的 `introduced_revision`，以及可空 `removed_revision`。
- 主要字段：`title`、`abstract`、`authors`、`journal`、`publication_year`、`publication_date`。
- 标识字段：`doi`、`pmid`、`pmcid`、`isbn`、`url`。
- 其他字段：`publication_type`、`volume`、`issue`、`pages`、`keywords`、`language`、`address`。
- 规范化与校验：`normalized_title_hash`、`normalized_doi`、`record_hash`。
- 时间字段：`created_at`、`updated_at`。

建议约束和索引：

- 唯一约束：`(import_file, source_record_index)`。
- 索引：`(project, introduced_revision, removed_revision)`。
- 索引：`(corpus, source_file, removed_revision)`。
- 索引：`(project, normalized_title_hash)`、`(project, normalized_doi)`。
- 为常用搜索字段设计数据库索引；不要对超长摘要建立普通 B-Tree 索引。

`authors`、`keywords` 等多值字段可以使用 JSON 保存，接口层仍返回数组。Embase PUI 等数据库来源标识进入 `source_identifier`，不应被丢在 XML 兼容层。不要继续把 XML 文件名或全局顺序号当业务主键；排序使用数据库字段，新增索引不得导致旧文献重新编号。

原始字段不再保存在该高频主表中，避免 AI 初筛、导出等完整对象查询被迫读取和反序列化大 JSON。各解析器读取到的完整来源字段进入独立冷表 `ScreeningReferenceRawMetadata`；标准字段与原始字段必须一对一写入并在发布前核对数量。

当前有效文献查询条件为：`introduced_revision <= corpus.revision` 且 `removed_revision IS NULL OR removed_revision > corpus.revision`。删除来源文件优先软移除，已有 AI、人工审阅或质量评价关系继续可审计。

### 4.4.1 `ScreeningReferenceRawMetadata`：完整原始元数据

每篇标准化文献对应一条按需读取的原始元数据记录，数据库表为 `plat_screening_reference_raw`。

- `reference`：与标准化文献一对一关联，文献删除时级联清理。
- `import_file`、`source_format`：保留来源和格式，支持按导入文件审计。
- `raw_fields`：解析器读取到的完整原始字段；XML 使用当前记录节点的 XML 片段保存层级和属性。
- `raw_size_bytes`、`raw_hash`：容量审计和完整性校验。
- `parser_version`、`created_at`、`updated_at`。

导入时先分批写入标准文献，再按 `(import_file, source_record_index)` 查回主键并批量写入原始元数据。不得依赖 MySQL `bulk_create()` 在所有版本上返回自增主键。发布前两表数量必须一致；重试或失败回滚删除标准文献时，原始元数据随之一并清理。

单条原始元数据受 `SCREENING_IMPORT_MAX_RAW_METADATA_BYTES` 限制，默认 512 KiB。超限时不截断，而是生成 `raw_metadata_too_large` 诊断并拒绝该记录。

### 4.5 `DedupRun`、`ReferenceDuplicateGroup`、`ReferenceDuplicateMember`

去重结果必须结构化保存，不能继续把完整详情塞入 `StageStep.metadata` 或截断为前 100 组。

`DedupRun` 建议字段：

- `project`、`corpus`、`corpus_revision`、`task`、`created_by`。
- `status`、`rule_version`、`rule_snapshot`。
- `total_count`、`kept_count`、`duplicate_count`、`group_count`、`failed_count`。
- `started_at`、`finished_at`、`created_at`、`updated_at`。

`ReferenceDuplicateGroup` 建议字段：

- `dedup_run`、稳定 `sequence`。
- `representative_reference`。
- `match_type`：例如 `doi`、`normalized_title`、`title_year`。
- `match_key_hash`、`display_title`、`member_count`。
- `created_at`。

`ReferenceDuplicateMember` 建议字段：

- `dedup_run`、`group`、`reference`。
- `role`：`kept` 或 `duplicate`。
- `match_reason`、可空 `match_score`。
- `source_file`、`source_record_index` 可通过文献关联读取，不重复复制无必要字段。

建议约束和索引：

- 唯一约束：`(dedup_run, sequence)`。
- 唯一约束：`(dedup_run, reference)`，确保同一去重运行中文献只属于一个结果位置；服务层同时校验 `group.dedup_run_id` 一致。
- 索引：`(dedup_run, sequence)`、`(group, role)`。
- 每组必须恰有一个 `kept` 成员，由服务层和一致性测试保证。

去重运行绑定文献集修订号；文献集新增或删除后旧运行保留审计价值，但必须标记为非当前结果，界面不得继续展示为“已完成的当前去重”。

### 4.6 `ScreeningRun`：AI 初筛运行

每次选择模型并开始初筛时创建一条运行记录。

建议字段：

- `project`、`corpus`、`corpus_revision`、`dedup_run`、`task`、`created_by`。
- `status`：`pending`、`running`、`stopping`、`completed`、`failed`、`cancelled`。
- `criteria_snapshot`、`model_config_snapshot`、`prompt_version`。
- `total_count`、`processed_count`、`included_count`、`excluded_count`、`uncertain_count`、`failed_count`。
- `input_tokens`、`output_tokens`、`points_consumed`。
- `started_at`、`finished_at`、`created_at`、`updated_at`。

项目可以保留多次运行用于审计，但界面需要明确“当前显示的运行”。如果产品只允许一个有效结果版本，可由项目保存 `active_screening_run` 外键。

### 4.7 `ScreeningResult`：单篇 AI 筛选结果

建议字段：

- `screening_run`、`reference`。
- `status`：`pending`、`processing`、`completed`、`failed`、`skipped`。
- `decision`：`included`、`excluded`、`uncertain`。
- `consensus`、`reason`。
- `model_results`：多模型判断明细 JSON。
- `extracted_fields`：模型返回的其他结构化字段 JSON。
- `token_usage`、`points_consumed`、`error_code`、`error_message`。
- `started_at`、`finished_at`、`created_at`、`updated_at`。

建议约束和索引：

- 唯一约束：`(screening_run, reference)`。
- 索引：`(screening_run, status)`。
- 索引：`(screening_run, decision)`。
- 列表常用排序字段应有联合索引。

AI 单篇重试应更新同一结果行或创建显式 attempt 记录，不能通过重复生成 JSON 文件表达版本。

### 4.8 `ManualReview`：人工审阅

现有 `source_xml` 字符串应替换为 `reference` 外键，并根据产品语义关联 `screening_run` 或审阅阶段。

建议约束：

- 如果每篇文献只有一份最终人工判断：唯一约束为 `(project, reference)`。
- 如果每次 AI 运行可以分别复核：唯一约束为 `(screening_run, reference)`。

人工审阅备注继续使用独立记录保存作者和时间，不把备注历史覆盖进单一文本字段。

### 4.9 质量评价引用关系与结果维度

`QAReference` 应继续复制题名、摘要、作者等必要字段作为进入质量评价时的业务快照，同时将 `source_ref_id` 改为真正的 `ScreeningReference` 外键，例如 `source_reference`。

这样可以做到：

- 初筛和质量评价之间有明确的数据库关联。
- 质量评价不会再把人工审阅记录 ID 误当成文献 ID。
- 即使后续初筛运行变化，质量评价的快照仍可保持当时语义。

删除策略建议使用 `PROTECT` 或 `SET_NULL`，不要因删除初筛批次级联删除已经开展的质量评价。

质量评价结果模型还必须保留 `v1.5.0` 已修正的维度语义：

- 偏倚风险与适用性必须使用明确的 `result_dimension` 或不同字段保存，不能仅凭同名领域推断。
- 保存评价方法与领域 schema 快照，QUADAS-2、NOS 等导出列由方法配置生成，不能写死一套字段。
- `pending`、`not_applicable`、`low`、`high`、`unclear` 等状态必须使用不同枚举值。
- 图表、Excel 和报告导出读取同一结构化结果服务，禁止分别实现易漂移的字段映射。
- “包含未完全确认文献”等导出条件必须成为显式查询参数并进入操作日志。

## 5. 环境配置与默认限制

建议在 `.env.example` 增加以下变量，并在 Django settings 中统一读取、校验和暴露给导入服务。字节值使用整数，避免不同解析代码对 `MB` 的解释不一致。

```dotenv
# 文献索引导入
SCREENING_IMPORT_MAX_FILES=100
SCREENING_IMPORT_MAX_FILE_BYTES=52428800
SCREENING_IMPORT_MAX_TOTAL_BYTES=209715200
SCREENING_IMPORT_WARNING_REFERENCES=25000
SCREENING_IMPORT_MAX_REFERENCES=100000
SCREENING_IMPORT_MAX_TITLE_CHARS=2000
SCREENING_IMPORT_MAX_ABSTRACT_CHARS=200000
SCREENING_IMPORT_MAX_AUTHORS=500
SCREENING_IMPORT_MAX_RECORD_TEXT_CHARS=300000
SCREENING_IMPORT_MAX_DOCX_ENTRIES=2000
SCREENING_IMPORT_MAX_DOCX_UNCOMPRESSED_BYTES=104857600
SCREENING_IMPORT_MAX_REPORTED_ERRORS=100
SCREENING_IMPORT_ALLOW_PARTIAL=false
SCREENING_IMPORT_DB_BATCH_SIZE=1000
SCREENING_PROCESSING_BATCH_SIZE=500
SCREENING_AI_MAX_ATTEMPTS=3
SCREENING_IMPORT_MAX_CONCURRENT_PER_USER=1
SCREENING_IMPORT_MAX_CONCURRENT_PER_PROJECT=1

# Django 上传落盘阈值；具体值需结合服务器内存确认
FILE_UPLOAD_MAX_MEMORY_SIZE=2621440
DATA_UPLOAD_MAX_MEMORY_SIZE=220200960

# 质量评价全文 PDF
QA_FULLTEXT_MAX_FILES_PER_REQUEST=20
QA_FULLTEXT_MAX_FILE_BYTES=52428800
QA_FULLTEXT_MAX_TOTAL_BYTES=209715200
QA_FULLTEXT_MAX_PAGES=1000
QA_PDF_TEXT_MAX_PAGES=20
QA_PDF_TEXT_MAX_CHARS=200000
QA_AI_MAX_CONTENT_CHARS=8000
```

说明：

- 200 MiB 使用 `209715200` 字节，而不是十进制 200,000,000 字节。
- 请求体上限必须略高于总文件上限，以容纳 multipart 边界和普通表单字段。
- 文件类型白名单、扩展名映射、MIME 规则等安全规则应固化在代码中，不建议允许运维随意通过环境变量扩大。
- 修改环境变量后需要重启 Web 和 Celery Worker，确保两类进程读取同一配置。
- 解析任务和 AI 请求任务应使用独立队列或独立并发配置，避免多个 100,000 篇导入挤占 Web/AI Worker。

## 6. 上传与解析安全要求

### 6.1 请求入口限制

在读取或保存完整请求体之前执行：

1. 用户必须登录，并拥有目标项目编辑权限。
2. 项目必须属于当前用户可访问范围，不能只相信前端传来的项目 ID。
3. 文件数不得超过 100。
4. 单文件不得超过 50 MiB。
5. 总文件大小不得超过 200 MiB。
6. 同一用户最多同时运行 1 个导入；同一项目最多同时运行 1 个导入。
7. 对上传接口增加用户级频率限制，避免反复提交后立即取消造成磁盘和队列消耗。
8. Web 服务器、反向代理、Django 和应用层的请求体上限必须协调；最外层限制不能小于产品允许值，也不能无限制。

超限时应返回稳定错误码和人类可读信息，例如：

- `413 request_too_large`
- `422 too_many_files`
- `422 too_many_references`
- `409 import_already_running`
- `429 import_rate_limited`

### 6.2 文件身份校验

不能仅依赖用户提供的文件名或 `Content-Type`：

- 只允许明确支持的扩展名和格式。
- 使用文件头、结构特征和解析探测共同确认格式。
- 文件名只保留安全 basename，生成服务端存储名，禁止路径穿越和覆盖已有文件。
- 记录原始文件名用于展示，但不得将其直接拼接成本地路径。
- 拒绝空文件、设备文件、符号链接和无法 seek/read 的异常对象。
- 为原始文件计算 SHA-256，用于审计、重复上传提示和完整性校验。
- MIME 检测结果与扩展名冲突时拒绝或进入明确的人工确认流程，不能静默按另一格式解析。

### 6.3 编码与文本限制

- 采用分块编码探测，并设置允许的编码集合。
- 禁止使用 `errors="ignore"` 静默丢失字节；解码失败必须产生包含文件名和大致位置的错误。
- 去除 NUL、非法控制字符和不允许进入数据库的字符。
- 统一 Unicode 规范化，但保留原始语义，不对题名和摘要做破坏性清洗。
- 单条原始记录文本最多 300,000 字符。
- 题名最多 2,000 字符，摘要最多 200,000 字符，作者最多 500 个。
- 超限记录默认导致整批失败；不能悄悄截断科研内容。
- 错误报告最多返回/保存 100 条样例，并同时保留总错误数，防止异常文件制造巨大错误响应。

### 6.4 XML 安全

- 禁止 DTD、外部实体、网络实体和 XInclude。
- 使用安全解析器或显式关闭实体解析，防止 XXE 和实体膨胀。
- 使用 `iterparse` 流式处理，并在消费后清理节点。
- 限制嵌套深度、单节点文本长度和单条记录总长度。
- 不允许解析器通过 URL 或本地路径读取外部资源。

### 6.5 DOCX/压缩容器安全

- DOCX 是 ZIP 容器，不能只检查压缩后文件大小。
- 压缩包成员最多 2,000 个，解压后总大小最多 100 MiB。
- 拒绝绝对路径、`../` 路径、重复危险路径和加密成员。
- 校验压缩比，防止 zip bomb；达到任一阈值立即终止。
- 当前 DOC/DOCX 解析依赖可能全量加载，应将这类格式放入受限队列，并考虑设置比其他格式更低的篇数上限。

### 6.6 RIS、BibTeX 等第三方解析器

- RIS 已复用 `rispy` 的字段映射，但按 `ER` 边界逐条释放记录，不再调用全量 `rispy.load()`。
- BibTeX 已按平衡花括号/圆括号拆分条目并逐条交给 `bibtexparser`，不再加载完整文献库；宏声明和 citation key 诊断只保留紧凑元数据。
- NBIB、CIW、ENW/TXT 已使用逐行状态机；文本格式统一严格解码 UTF-8/UTF-16/GB18030，不再忽略非法字节。
- DOCX 已消除应用层的多份全文副本，但 `python-docx` 仍会构造主文档 XML 对象树。因此 DOCX 的安全边界仍依赖压缩成员数、解压后总量、单文件大小和单记录字段上限，不能把它视为与纯文本格式相同的恒定内存解析器。

100,000 篇能力首先面向可流式文本/XML 格式；DOCX 的实际容量仍须在目标服务器单独压测并维持更保守的使用建议。

### 6.7 PDF 安全

质量评价 PDF 需要独立保护：

- 扩展名、声明 MIME 和 PDF 文件签名必须一致。
- 限制单文件、单次请求总大小、文件数和页数。
- 对加密、损坏、超深对象树、异常交叉引用表和解析超时给出明确状态。
- PDF 解析必须在 Celery Worker 中执行，并设置软/硬超时与内存限制，不能阻塞 Web 请求。
- 可接入 ClamAV 或云端恶意文件扫描；未完成扫描的文件不得进入后续自动处理。
- 上传后先进入 `pending`，验证、扫描和元数据提取成功后再进入 `ready`。
- PDF 和提取文本均应通过鉴权接口访问，不能把可猜测的媒体 URL 直接暴露为长期公开链接。
- 日志不得记录 PDF 正文、摘要全文、签名 URL 或用户本地路径。

## 7. 新的完整数据流程

### 7.1 新增索引流程

1. 前端提交项目 ID 和索引文件。
2. API 完成权限、文件数、单文件大小、总大小、并发与频率检查。
3. 在项目锁内读取当前 `ScreeningCorpus.revision`，创建 `operation=add` 的 `ReferenceImportBatch`，令 `target_revision = base_revision + 1`，并创建各 `ReferenceImportFile`。
4. 原始文件保存到私有原始文件区，计算 SHA-256；相同项目的重复文件给出明确提示或按产品规则拒绝。
5. 事务提交后通过 `transaction.on_commit()` 投递解析任务，避免 Worker 看到尚未提交的数据。
6. Worker 逐文件、逐记录解析为统一的 `ReferenceRecord`。
7. 每条记录完成字段校验、Unicode 规范化、哈希计算和来源标识提取；Embase PUI 等进入 `source_identifier`。
8. 同步累计 `detected/parsed/skipped/missing_abstract`，并以固定小批次写入 `introduced_revision = target_revision` 的暂存 `ScreeningReference` 与受限数量的 `ReferenceImportIssue`；由于项目当前 revision 尚未变化，这些行对业务查询不可见。
9. 当前有效文献数加本批新增数达到 25,000 时记录警告；预计超过 100,000 时终止，不发布本批次。
10. 解析结束后逐文件核对检测数、写入数、拒绝数和数据库计数；0 条可用文献的文件明确失败。
11. 如果存在致命错误且 `ALLOW_PARTIAL=false`，批次标记失败并清理暂存文献，当前 `revision` 和既有文献保持不变。
12. 全部成功后，在短事务内再次锁定文献集并校验 `base_revision` 未变化，只把 `ScreeningCorpus.revision` 切换为 `target_revision` 并更新聚合计数，不在发布事务内更新 100,000 行。
13. 发布后，旧去重运行、AI 运行和导出因 `corpus_revision` 不匹配自动成为历史版本，无需逐行更新；是否复用未变化文献的 AI/人工结果由后续阶段的明确规则控制。
14. 前端重新查询当前有效来源文件统计；新增少量索引的耗时只随本次文件和记录数增长。

### 7.2 删除索引流程

1. API 校验文件属于当前项目且当前没有冲突的导入操作。
2. 创建 `operation=remove` 的批次并记录 `base_revision`、`target_revision = base_revision + 1`、来源文件和操作人。
3. 分批把该来源的当前有效文献和来源文件写入 `removed_revision = target_revision`；在当前 revision 下它们仍然有效，失败或取消时可以清除这些暂存标记。
4. 全部准备成功后，在短事务内校验 `base_revision` 并把文献集 revision 切换到 `target_revision`，使删除原子生效。
5. 仅给被删文件写入 `removed_revision/removed_by_batch`；原始解析状态仍可审计，其他文件的解析统计和问题记录保持不变。
6. 原始文件按保留策略软删除或延迟物理清理，不能先删文件再提交数据库状态。
7. 当前去重运行和后续结果成为旧修订；界面不得继续把它们显示为当前完成结果。
8. 如果删除最后一个来源文件，当前有效文献数归零，解析统计区进入空状态。

### 7.3 数据库去重与详情分页

1. 创建绑定当前 `corpus_revision` 的 `DedupRun`，保存规则版本和配置快照。
2. 按规范化 DOI、题名哈希等字段分批查找候选，再进行确定性的二次字段校验。
3. 写入 `ReferenceDuplicateGroup` 和 `ReferenceDuplicateMember`；不复制文献文件，不物理删除重复文献。
4. `StageStep.metadata` 或步骤摘要只保存 `total/kept/duplicates/group_count/completion_time/dedup_run_id`，不保存详情数组。
5. 前端展开详情时调用独立接口，不随项目初始化加载全部重复组。

建议 API：

```text
GET /api/projects/{project_id}/dedup-runs/{run_id}/groups/?page=1&page_size=20
GET /api/projects/{project_id}/dedup-runs/{run_id}/groups/{group_id}/members/?page=1&page_size=50
```

接口要求：

- 重复组默认每页 20，最大 100；组成员默认每页 50，最大 200。最大值固化在代码中，不通过环境变量无限放大。
- 组列表按稳定 `sequence` 排序，返回总组数、总页数、当前页和是否有下一页。
- 每组默认展示代表文献与成员数量；展开某组时再按需获取成员，避免一个超大组拖垮整页。
- 查询必须同时限制 `project_id`、`dedup_run_id` 和当前用户权限；跨项目猜测 ID 不得泄露记录存在性。
- 使用 `select_related/prefetch_related` 或等价查询控制 SQL 数，不能按组或成员产生 N+1。
- 不再存在“只保存前 100 组”的业务截断；超大结果依靠分页访问完整数据。

前端交互：

- 展开详情后加载第一页，显示加载态、错误态、空态和重试。
- 列表仍可保留固定高度内部滚动，但底部必须提供页码、上一页、下一页和总组数。
- 切换项目、重新去重或组件卸载时取消旧请求，并用项目/运行 ID 防止旧响应污染新页面。
- 只有当前文献集修订对应的去重运行显示“已完成”；旧修订显示“结果已过期”。

### 7.4 AI 初筛流程

1. 创建 `ScreeningRun` 并保存纳排标准、模型和提示词版本快照。
2. 保存当前 `corpus_revision` 和 `dedup_run`，按主键游标分批读取该修订下去重保留的文献，禁止一次性 `.list()` 全部加载。
3. 每批调用模型，结果通过唯一约束幂等写入 `ScreeningResult`。
4. 每批完成后更新运行进度和用量；计数更新使用数据库原子表达式，避免并发丢失。
5. 重试时只处理非完成状态，不重复扣费；扣费和结果落库需要统一幂等键。
6. 用户停止任务后，不再领取新批次，已发出的调用完成后安全落库。
7. 页面列表、统计和导出只查询当前 `ScreeningRun`，不扫描结果 JSON。

### 7.5 人工审阅与导出

1. API 路径由 `source_xml` 改为 `reference_id`。
2. 每次读写都同时按 `project_id` 和 `reference_id` 查询，防止跨项目越权。
3. 列表在数据库层完成筛选、排序和分页；摘要和多模型详情按需加载。
4. 人工结论用唯一约束和事务 upsert，避免并发重复记录。
5. 导出使用 QuerySet iterator/游标分页流式生成，不一次性加载 100,000 行。
6. XML 仅作为用户主动选择的导出格式临时生成，不再生成单篇 XML。

## 8. 分阶段实施步骤

### 阶段 0：建立基线和冻结语义

要做的事：

- 固定当前支持格式、字段映射、去重规则和筛选决策枚举。
- 为 1,000、10,000、25,000、50,000、100,000 篇准备合成样本。
- 保留若干真实 RIS、NBIB、EndNote XML、Elsevier/Embase XML、BibTeX、DOCX 异常样本；Embase 样本覆盖命名空间、PUI、重复作者分组和缺摘要。
- 记录当前解析结果字段、去重结果、AI 输入、导出结果和资源占用。
- 固定 `v1.5.0` 文件级诊断契约：检测数、成功数、跳过数、摘要缺失、问题位置、来源标识和建议。
- 固定质量评价偏倚风险/适用性维度、方法动态字段及 `pending` 语义。
- 列出所有依赖 `source_xml`、单篇 XML、结果 JSON、`StageStep.metadata.duplicate_details` 的调用位置。

交付物：基准数据、字段契约、性能记录和依赖清单。

验收：新旧流程可以针对相同输入做字段级对比；所有下游消费者均进入清单。

### 阶段 1：增加配置和统一校验入口

状态：**已完成（2026-09-23）**。配置、启动校验、稳定错误结构和统一上传校验已随阶段 3 接入；网关/Nginx 的请求体上限仍需部署时同步配置。

要做的事：

- 将第 5 节配置加入 `.env.example` 和 settings。
- 启动时校验配置为正整数且满足单文件不大于总大小、警告数不大于最大篇数等关系。
- 建立统一 `ImportLimits`/配置对象，禁止视图、Parser 和 Worker 各自读取不同默认值。
- 建立稳定的业务错误码、错误结构和前端提示映射。
- 配置 Nginx/网关、Django 和应用层请求体限制。

验收：Web 与 Celery 打印同一份非敏感配置摘要；边界值自动化测试通过。

### 阶段 2：新增数据库模型

状态：**已完成（2026-09-23）**。

要做的事：

- 新增 `ScreeningCorpus`、`ReferenceImportBatch`、`ReferenceImportFile`、`ReferenceImportIssue` 和 `ScreeningReference`。
- 新增 `DedupRun`、`ReferenceDuplicateGroup`、`ReferenceDuplicateMember`。
- 新增 `ScreeningRun`、`ScreeningResult`。
- 将 `ManualReview` 改为文献外键。
- 将 `QAReference` 的来源字段改为 `ScreeningReference` 外键或可空关联。
- 添加唯一约束、查询索引、状态枚举和 Admin 只读/筛选配置。
- 使用新的增量 migration；不修改 `0001_initial.py` 等历史迁移。
- 因明确不考虑存量数据，不编写单篇 XML/JSON 回填命令，也不保留长期双读逻辑。

建议先在开发数据库清空相关业务数据，再执行 migration；生产环境即使无须保留业务数据，也必须先做数据库和媒体目录备份。

验收：空库和现有 schema 均可正常 migrate；约束测试可阻止重复来源位置、同次去重运行重复成员和同次 AI 运行重复结果；文献集修订号只能单调递增。

### 阶段 3：重写上传入口和批次状态机

状态：**已完成（2026-09-23）**。现阶段解析产物仍保留单篇 XML 兼容输出，数据库文献行写入属于阶段 5，不在本阶段提前实现。

要做的事：

- 上传 API 改为先建批次、再异步解析。
- 实现文件数、大小、格式、哈希、权限、并发和频率检查。
- 将原始文件保存为批次输入，不再在上传请求中创建单篇 `DataFile`。
- 使用 `transaction.on_commit()` 投递任务。
- 实现取消、失败、重试、超时和孤儿临时文件清理。
- 新增索引只把本次 `file_ids` 交给 Worker；后端不得忽略 ID 后重新查询项目全部输入文件。
- 删除索引使用独立 remove 操作，保留其他来源的文件级统计。
- 前端展示上传、验证、解析、发布和下游失效状态。

验收：重复点击、并发请求、Celery 暂停、任务失败均不会发布半套数据；已有 100,000 篇时新增 1 个小文件不会重新解析或重新写入既有文献。

### 阶段 4：统一迭代解析器

状态：**已完成（2026-09-24）**。生产解析入口已使用迭代协议和单遍有界诊断；`parse_file()` 仅作为旧调用方需要列表时的兼容边界。数据库批量写入、修订发布和停止单篇 XML 输出属于阶段 5。

要做的事：

- 定义统一 `ReferenceRecord` 数据结构和 `Iterator[ReferenceRecord]` 协议。
- NBIB、ENW/TXT、CIW 使用逐行状态机。
- XML 使用安全 `iterparse`。
- 将现有 EndNote、内部 XML 和 Elsevier/Embase `bibdataset/item` 适配器纳入统一协议，保留命名空间处理、PUI 和作者序号去重。
- RIS 替换全量 `rispy.load()` 路径或实现流式兼容解析。
- BibTeX 评估并替换全量库加载；无法替换前设置单独上限。
- DOCX 加入压缩容器检查并消除 `lines/full_text/records` 多份全量副本；DOC 如不能安全解析应暂停支持或降低上限。
- 所有 Parser 通过同一字段校验器，不自行静默截断或忽略乱码。
- 解析器同时产出标准记录和结构化诊断事件；候选条目检测与实际写入数必须可核对。

实现说明：

- `iter_file()` 是 Worker 和目录解析的流式入口；所有格式统一返回 `Iterator[ReferenceRecord]`。
- `ParseReportCollector` 随记录流累计成功数、缺摘要、错误和警告，只保留配置数量的问题样例；候选记录再以流式扫描核对检测数和接受数。
- 解析诊断严重程度与批次发布阻断语义分离：BibTeX 非法/重复 citation key、解析器跳过单条记录和候选数量差异继续精确定位，但不阻止其余有效文献发布；字段硬上限、文件级解析失败、安全限制和一致性错误仍阻断发布。失败批次保留诊断报告。
- 标题、摘要、作者数量和单记录文本总量统一经过 `validate_reference_record()`；超限记录明确拒绝并形成结构化问题，不做静默截断。
- XML 在解析前分块扫描 DTD/实体声明，使用 `iterparse` 消费后移除节点，并限制最大嵌套深度。
- 真实回归样本的字段摘要、诊断统计和标题去重结果未发生变化；解析专项与后端全量测试覆盖迭代惰性、问题明细截断及字段超限。

验收：对可流式格式，峰值内存主要由固定批次大小决定，不随总篇数线性增长；异常样本返回稳定错误；数据库化前后 `v1.5.0` 样本字段与诊断统计一致。

### 阶段 5：数据库批量导入和原子发布

状态：**已完成（2026-09-24）**。`ScreeningReference` 已成为新导入批次的结构化主数据；单篇 XML 仅作为尚未数据库化的下游消费者兼容产物保留，不参与修订发布和数量核对。

要做的事：

- 每 1,000 条执行一次 `bulk_create`，避免逐条 ORM 插入。
- 每批提交进度，但暂存数据在批次发布前对业务页面不可见。
- 达到 100,000 篇后继续探测到第 100,001 篇即终止，不再解析剩余内容。
- 实现稳定的来源定位；页面排序使用数据库排序字段，不再通过全局 XML 文件编号表达身份。
- 校验写入条数、哈希、失败数和数据库实际计数。
- 导入/删除记录在分批处理中预写 `target_revision`；成功后短事务只校验 `base_revision` 并切换文献集版本，失败/取消清理暂存行或移除标记。
- 新增和删除只处理受影响来源；其余文献行、文件级统计和诊断问题保持不变。

实现说明：

- `ScreeningReferenceBulkWriter` 按 `SCREENING_IMPORT_DB_BATCH_SIZE` 执行 `bulk_create`，每次提交后更新任务暂存进度，不把整个批次放进长事务。
- 每条文献保存 `source_file/source_record_index/source_identifier`，并生成 `normalized_title_hash`、`normalized_doi` 和稳定 `record_hash`。
- 解析成功数必须与批次暂存行数和逐文件暂存行数完全一致；缓存的有效文献数/来源数也必须与当前修订下的数据库查询一致，否则拒绝发布。
- 达到第 `MAX_REFERENCES + 1` 条时立即停止后续解析；限制使用“当前已发布数 + 本批已接受数”，不能通过多次小批上传绕过。
- 成功发布只在短事务中锁定批次和文献集、复核 `base_revision`、更新 `corpus.revision` 与聚合计数；暂存行通过修订号一次性变为可见。
- 失败、取消、重试和修订冲突都会删除该批次的未发布 `ScreeningReference`；重投同一任务会先清理旧暂存行和诊断，再从原始私有文件安全重放。
- 删除来源在同一发布事务中给该来源的当前有效文献写入 `removed_revision`，其他来源行不更新。

不要把整个 100,000 行导入包在一个超长数据库事务中。应使用“不可见暂存批次 + 分批提交 + 最后短事务发布修订号”，兼顾原子业务语义和数据库可用性。

验收：解析中途杀死 Worker 后可安全恢复或清理；用户始终只能看到一个完整修订；删除一个索引后其余文件统计不消失，新增少量索引的数据库写入量只随新增记录数增长。

### 阶段 6：数据库化去重

状态：**已完成（2026-09-24）**。去重主数据、修订安全发布、完整详情分页和前端按需加载均已落地；仅为阶段 7 以前的下游消费者保留数据库生成的兼容 XML。

要做的事：

- 将当前基于复制/打开 XML 的去重改为规范化字段和哈希查询。
- 明确定义 DOI、题名、年份等规则的优先级和冲突处理。
- 创建绑定 `corpus_revision` 的去重运行，记录组、代表文献、成员、规则版本和匹配理由，不物理删除重复项。
- 对哈希候选进行二次字段校验，避免只凭哈希或空字段误判。
- 对大文献集按数据库批次或游标处理，避免把全部题名映射加载到 Python。
- 步骤 metadata 只保存摘要和 `dedup_run_id`；删除 `duplicate_details` 大数组及 `duplicates[:100]` 截断。
- 新增重复组和组成员分页 API；前端展开时按每页 20 组加载，组成员按需分页。
- 前端提供总组数、页码、上一页、下一页、加载/失败/空状态，并取消过期请求。

验收：与阶段 0 样本的去重结果一致；重复关系不跨项目、不跨修订串联；第 101 个重复组可以通过分页访问；单个超大重复组不会导致项目接口或首屏响应无限增长。

实现说明：

- 规则版本固定为 `v1.5.0-normalized-title-v1`：SHA-256 只用于候选分桶，候选必须再次通过完整规范化题名精确比较；空题名直接保留，不会相互误判。为保持 `v1.5.0` 回归语义，DOI 和年份冲突暂不否决题名精确匹配，并完整记录在规则快照中。
- 当前有效文献按 `normalized_title_hash, id` 排序并使用数据库 iterator 分批读取；每组最小文献 ID 为代表项，成员使用批量写入，不构造全项目题名映射。
- 运行完成前不会更新 `ScreeningCorpus.last_dedup_run`；发布使用短事务锁定运行与文献集，文献集修订变化时本次运行失败并清理关系。新增或删除索引发布后会清空当前去重指针，历史运行仍保留审计价值。
- API 使用项目可见性策略隔离用户数据；重复组和成员页大小上限固化在代码。前端展开详情后才请求第一页，切页、项目切换和组件卸载都会取消过期请求。
- 自动化测试覆盖题名规范化、代表项、空题名、哈希完整性、取消清理、修订冲突、跨项目隔离、成员上限以及第 101 个重复组访问。

### 阶段 7：AI 初筛结果数据库化

状态：**已完成（2026-09-28）**。

要做的事：

- AI 输入选择器改为读取 `ScreeningReference`。
- AI 运行绑定 `corpus_revision` 和 `dedup_run`，旧修订结果不得混入当前统计。
- 模型请求和响应使用 `reference_id`，保留模型配置快照。
- 结果写入 `ScreeningResult`，删除单篇结果 JSON 的写入路径。
- 加入唯一幂等键、失败重试、停止语义和原子计数。
- 明确 `uncertain`/待定结果的存储、展示和导出规则。
- 积分扣减和结果保存使用可重试事务/账本关联，避免重复扣减或有结果无账单。

验收：任务重试和 Worker 重启不会产生重复结果或重复扣费；100,000 行不会生成 100,000 个 JSON 文件。

实现说明：

- `ScreeningRun` 保存纳排标准、模型与提示词配置快照，并绑定文献集修订及当前去重运行；恢复任务只能认领同一修订下的原运行。
- `ScreeningResult` 以数据库状态机分批领取，失败重试只更新同一行；新增 `attempt_count` 及 `SCREENING_AI_MAX_ATTEMPTS`，达到上限后以失败/待定语义进入人工处理。
- 单篇结果的 JSON 文件写入仓库已移除。结果查询以数据库为主，历史 DataFile 仅作为旧项目只读兼容。
- 积分流水使用 `screening-run:<run_id>:usage` 幂等键；用量日志复用同一流水，运行完成、修订校验和扣费在同一事务内提交。
- 自动化回归覆盖结果唯一性、停止恢复、失败重试上限、重复结算、修订冲突回滚、数据库选择器和 Handler 不生成 JSON。

### 阶段 8：人工审阅 API 和前端切换

状态：**已完成（2026-09-28）**。

要做的事：

- 将 URL、Serializer、Service、前端状态中的 `source_xml` 替换为 `reference_id`。
- 所有查询绑定明确的 `corpus_revision`/`screening_run`，文献集变化后旧结果显示为历史版本而不是静默混用。
- 列表、统计、搜索、筛选、排序全部下推数据库。
- 大字段详情按需加载，列表响应不默认携带完整摘要和多模型明细。
- 使用数据库聚合或准确失效的统计缓存。
- 更新操作日志，使其同时记录项目、文献 ID、运行 ID 和变更前后值。

验收：分页请求耗时和文件读取次数不随项目总篇数线性增长；跨项目猜测文献 ID 返回 404/403，不能泄露数据存在性。

实现说明：

- `ManualReview` 新增 `screening_run`，并以数据库唯一约束 `(screening_run, reference)` 隔离不同初筛运行；迁移编号为 `0025_manualreview_screening_run`。
- 新增按运行和文献 ID 访问的详情、决定及备注接口；阶段 11 已删除旧 `source_xml` 兼容接口。
- 列表 SQL 只选择页面展示字段，详情点击后按需获取；统计通过数据库条件聚合生成。
- 当前语料修订或去重指针与运行快照不一致时，该运行被标记为历史只读；服务端写接口再次校验，不能仅依赖前端禁用按钮。
- 决定、备注和完成审阅均写入项目操作日志；专项回归覆盖轻量列表、详情加载、运行绑定、历史只读和跨项目 ID 隔离。

### 阶段 9：导出和质量评价衔接

状态：**已完成（2026-09-28）**。

要做的事：

- RIS、Excel、XML 导出改为数据库流式读取。
- 导出临时文件创建、下载权限和过期清理使用统一服务。
- 质量评价导入从 `ScreeningReference + ScreeningResult + ManualReview` 读取最终纳入项。
- 创建 `QAReference` 快照并保存 `source_reference` 关联。
- 处理待定、人工覆盖、重复文献和多次 AI 运行的选择语义。
- 质量评价结果和导出显式区分偏倚风险与适用性，按评价方法 schema 动态生成字段。
- 图表、Excel 和报告复用统一结果映射服务，并分别回归 QUADAS-2、NOS 和无适用性领域方法。

验收：最终纳入数量、导出字段和质量评价引用与数据库查询一致；导出过程内存有界；偏倚风险、适用性、待定和不适用在前端与所有导出中语义一致。

实现说明：

- 新增运行级最终结果迭代服务，按主键分批读取 `ScreeningResult + ScreeningReference`，并仅加载同一 `ScreeningRun` 的 `ManualReview`；导出和质量评价导入共同使用该决定规则。
- Excel 继续使用 openpyxl write-only 模式；RIS 和 XML 通过回调在同一次遍历中增量写入，不为第二、第三种格式重新扫描结果或构建全量列表。
- 新增 `screening_export_xml` 产物类型和结构化 XML 下载。每条记录保存稳定 `reference_id`、最终决定、人工覆写标记、题录字段和自定义提取字段，XML 特殊字符由标准库转义。
- `QAReference` 新增 `source_screening_run` 和 `source_screening_decision`；使用新增迁移 `0026_qareference_screening_source`，不修改历史迁移。阶段 11 后质量评价导入只接受当前数据库筛选运行。
- 当前文献集只有过期筛选运行而没有匹配的已完成运行时，质量评价导入返回明确的 `409 current_screening_run_required`，且事务回滚，不清空既有质量评价数据。
- 统一质量结果映射包含 `low/high/unclear/pending/na` 五态。比例图分母来自实际映射项；交通灯、比例图和 Excel 不再将 `pending` 映射为“不清楚”或将 `na` 映射为“低风险”。
- 阶段专项回归覆盖人工覆盖、过期运行拒绝、来源快照、XML 转义、偏倚/适用性隔离、待定/不适用五态、NOS 动态字段、缺失结果按待确认导出和安全工作区清理；全量 Django 309 项、前端 38 项测试及前端生产构建通过。

### 阶段 10：质量评价 PDF 存储加固

状态：**已完成（2026-09-28）**。

要做的事：

- PDF 二进制继续存私有文件/对象存储，不放数据库 BLOB。
- 新增全文资产状态、SHA-256、大小、MIME、页数、扫描状态、提取状态和错误信息。
- 实现第 6.7 节的 PDF 检查、解析超时和恶意文件扫描接口。
- 抽象 Storage 读取方式，消除执行器直接依赖 `file.path`；对象存储下应以流或受控临时文件交给解析器。
- 提取文本使用独立私有产物或受限专用表，设置保留期限和访问权限。
- 下载改为鉴权接口或短期签名 URL。

验收：本地文件系统和对象存储两种后端均可评估；非法、超限、加密或损坏 PDF 不会拖垮 Web/Worker。

实现说明：

- 新增 `QAFulltextAsset` 和迁移 `0027_qa_fulltext_asset`，记录项目、全文状态、SHA-256、字节数、MIME、页数、安全扫描、文本提取和分类错误；项目与哈希唯一约束防止并发重复落库。
- PDF 与提取文本使用可由 `QA_FULLTEXT_STORAGE_BACKEND` 替换的独立私有 Storage 和服务端随机路径，不再生成公开 URL。下载统一经过项目权限接口；解析器通过受控临时文件兼容没有 `path()` 的对象存储。
- 上传入口统一校验单次文件数、单文件/总大小、扩展名、声明 MIME、`%PDF-` 文件头和项目内重复内容。资产先进入 `pending`，结构校验、页数限制、安全扫描和限量文本提取完成后才将文献标为 `available`。
- Celery PDF 任务配置软/硬超时，并通过 `CELERY_WORKER_MAX_MEMORY_PER_CHILD` 回收高内存子进程；加密、损坏、空页、超页、恶意文件和扫描不可用均保存稳定错误码。重复投递由资产行锁和状态机幂等保护，暂时性失败支持鉴权重试，异常中断资产由清理任务转为可重试失败。
- 恶意文件扫描使用可替换后端接口；默认 `DisabledScanner` 明确记录 `not_configured`。生产环境可替换为 ClamAV/云扫描实现，并通过 `QA_FULLTEXT_REQUIRE_CLEAN_SCAN=true` 强制只有 `clean` 文件进入自动处理。
- AI 评价优先读取有字符上限的私有提取文本；历史 `DataFile` 仅保留兼容读取，并通过 Storage 物化层消除执行器对本地 `.path` 的直接依赖。失败原件和已完成评价的提取文本分别按环境变量保留期限清理。
- 前端显示等待、校验、扫描、提取、拒绝和失败状态，处理期间自动刷新，失败项可重试；专项测试覆盖伪 PDF、错误 MIME、项目隔离去重、加密/超页 PDF、授权下载、文件联动删除和无本地路径 Storage。

### 阶段 11：移除旧文件主数据路径

状态：**已完成（2026-09-29）**。

要做的事：

- 删除单篇 XML 生成、复制、递归查找和读取代码。
- 删除单篇 AI JSON 写入和扫描代码。
- 删除去重详情 JSON 作为页面主数据的读取路径，以及 `StageStep.metadata.duplicate_details`。
- 删除 `source_xml` API 契约、旧 Serializer 字段和兼容查询。
- 调整 `DataFile` 类型，只保留原始上传、导出、报告和全文等真正的文件资产。
- 更新 Admin、API 契约、OpenAPI、操作手册和测试。

验收：代码搜索不存在运行时依赖 `source_xml` 的业务路径；导入 100,000 篇时文件数量只与上传文件数和主动导出次数相关。

实现说明：

- 解析器仅逐条校验并批量写入 `ScreeningReference`/原始元数据表，文件侧只保留原始上传和解析诊断报告。
- 去重器只发布数据库运行、重复组/成员和一份紧凑报告，不再为保留文献生成兼容 XML。
- AI 待筛接口 `/api/projects/<id>/ai_screen_inputs/` 返回有界数据库分页及真实题名；人工审阅只保留运行 ID + 文献 ID 路由。
- 导出必须绑定当前已完成的数据库初筛运行，Excel 的稳定身份列改为 `reference_id`；质量评价不再回退到旧 JSON/XML。
- 迁移 `0030_remove_legacy_screening_file_keys` 删除 `ManualReview.source_xml` 和冗余的 `QAReference.source_ref_id`。
- 新增 `cleanup_legacy_screening_artifacts` 命令，默认仅预览，可按项目清理历史单篇 XML/JSON 数据库记录和物理文件；执行前必须备份。

### 阶段 12：容量、并发和故障测试

状态：**本地工程验收已完成（2026-09-29）；目标服务器复验纳入阶段 13 上线门禁。**

至少覆盖：

- 0、1、999、1,000、25,000、50,000、100,000、100,001 篇边界。
- 1、100、101 个文件边界。
- 单文件 50 MiB、总计 200 MiB 及各自超出 1 字节。
- 标题、摘要、作者数和单记录文本长度边界。
- 乱码、截断记录、错误 MIME、伪扩展名、XXE、实体膨胀、ZIP bomb、路径穿越。
- 重复文件、重复文献、空 DOI、相同题名和哈希碰撞候选。
- 0、1、20、21、100、101 个重复组分页边界，以及单组 1、50、51、200、201 个成员边界。
- 删除一个来源后其他来源统计保持不变；新增个位数记录不重写既有文献。
- 同用户、同项目和不同项目并发导入。
- Worker 被杀死、数据库短暂断开、Redis 任务重复投递、用户取消和进程重启。
- AI 超时、单篇失败、批次重试、停止、重复回调和积分扣减幂等。
- 列表/统计/导出在 100,000 篇下的 SQL 数、耗时、响应大小、内存和磁盘占用。
- 去重详情第一页、末页、越界页、超大重复组和项目切换请求取消。

性能验收不应只写一个脱离硬件的绝对秒数。先在目标服务器记录 CPU、内存、磁盘、数据库版本和 Worker 并发，再确定正式预算。最低要求是：

- 可流式格式的解析峰值内存不随总篇数线性增长。
- 数据库写入不存在逐篇 insert 的 N+1。
- 列表查询只随页大小增长，不扫描整个项目或打开文献文件。
- 去重详情响应和 SQL 数只随组页大小、成员页大小增长，不随全部重复组数量增长。
- 统计查询不读取单篇 JSON/XML。
- 导出采用流式/游标方式，内存有界。
- 取消信号可以在一个处理批次内生效。

实现与证据：

- 新增 `core/tests/test_screening_capacity_boundaries.py`，固定验证 0、1、999、1,000、25,000、50,000、100,000、100,001 篇，100/101 文件，单文件 50 MiB 与总计 200 MiB 的精确边界，以及标题、摘要、作者上限、XML DTD/实体和 DOCX 路径穿越。
- 项目总篇数限制收敛到 `validate_projected_reference_count()`，解析执行器和边界测试使用同一规则，避免入口与 Worker 对 100,000 篇上限理解不同。
- 新增受 `--execute` 保护的 `benchmark_screening_capacity` 命令。命令创建隔离用户和项目，生成并真实解析 RIS，批量写入文献及原始元数据，执行数据库去重、结果落库、首末页列表、统计，并以生产导出器单遍生成 XLSX、RIS 和 XML；默认无论成功失败都清理测试数据。
- 本地报告保存在 `docs/benchmarks/screening-capacity-local-2026-09-29.json`。测试环境为 10 核 Apple Silicon、Python 3.12.7、MySQL 8.0.32；该环境信息必须随报告保存，数据不能直接当作服务器 SLA。
- 10 万条合成 RIS 为 15,066,685 字节，真实流式解析耗时 0.6418 秒；数据库批量写入耗时 20.9866 秒。去重完整处理 100,000 条，形成 999 个重复组和 999 条重复记录，耗时 5.3120 秒。
- AI 输入首/末页分别为 10/9 条 SQL；人工审阅首/末页分别为 11/10 条 SQL；统计为 8 条 SQL。响应大小保持在当前页范围，未随 10 万篇线性放大。
- 99,001 条去重后结果以单次有界迭代生成 XLSX、RIS、XML，耗时 17.7512 秒，输出分别约 6.70 MiB、5.36 MiB、20.28 MiB；全流程进程峰值 RSS 为 150.86 MiB。
- 基准执行 `ANALYZE TABLE` 后记录相关整表空间（不是单项目精确占用）；本次五张核心表的数据与索引合计约 132.05 MiB。报告在测试项目删除前采集，因此可用于同环境纵向比较。
- 最新质量评价修复已纳入验收范围：上传、方法选择和结果审核采用服务端分页；AI 评价进度不再铺开全部未评价文献；“全部一键确认”只处理已有评价结果；初筛结果下载在同一入口选择 XLSX/XML 格式，不增加含义不清的重复下载行。

可重复执行：

```bash
python manage.py test core.tests.test_screening_capacity_boundaries --keepdb
python manage.py benchmark_screening_capacity \
  --references 100000 --batch-size 1000 --duplicate-every 100 \
  --execute --output docs/benchmarks/screening-capacity-<environment>.json
```

目标服务器上线前仍必须执行：同用户/同项目/跨项目并发导入，Worker 强制终止、MySQL/Redis 短暂中断、取消与重复投递，以及数据库和私有文件存储的备份恢复。上述项目依赖实际部署拓扑，不在本地开发机伪造“通过”；任一失败均阻止阶段 13 正式开放。

### 阶段 13：上线与回滚

由于不考虑存量数据，推荐采用明确切换，不建设长期双写：

1. 在测试环境完成全流程和 100,000 篇容量测试。
2. 备份生产数据库、媒体目录和环境配置。
3. 进入维护模式并排空正在运行的解析、筛选和导出任务。
4. 清理确认不保留的旧项目业务数据。
5. 执行新增 migration。
6. 部署 Web 和 Worker，确认环境变量完全一致。
7. 运行 Django system check、migration check 和小样本冒烟测试。
8. 开放给管理员/测试账号，再逐步开放普通用户。
9. 观察数据库慢查询、Worker 内存、队列长度、磁盘增长和错误码分布。

回滚原则：

- 在 migration 和清理前保留可恢复备份。
- 新导入操作发布修订号前失败不影响当前有效文献集。
- 代码回滚与 schema 回滚分开评估；不要在生产直接 reverse 可能丢数据的 migration。
- 已明确不兼容旧单篇 XML/JSON 项目，因此切换前必须由负责人确认旧数据可以删除。

## 9. 质量评价 PDF 为什么不应直接存数据库

将 PDF 以 BLOB 写入关系数据库技术上可行，但对当前平台并不合适：

- 单个 PDF 已允许达到 50 MiB，会快速放大数据库表、事务日志、主从复制和备份体积。
- 数据库备份无法轻量地只恢复结构化数据，恢复时间和运维风险都会增加。
- PDF 下载适合对象存储的流式传输、Range 请求、生命周期、校验和短期签名 URL。
- AI/PDF 解析器通常需要文件流或临时文件，写入数据库并不会消除解析过程。
- 全文可能包含版权、敏感和隐私风险，需要独立访问控制、保留和删除策略。

推荐的结构是：

```text
QAReference（数据库业务记录）
  └─ QAFulltextAsset / DataFile（数据库元数据、状态、哈希、大小、页数）
       └─ private storage object（真正的 PDF 二进制）
       └─ private extracted-text object（可选的受限提取文本）
```

这并不影响事务一致性：先创建 `pending` 资产，文件上传并校验成功后置为 `ready`；失败资产由清理任务回收。业务表只允许引用 `ready` 资产。

## 10. 推荐实施顺序与依赖关系

推荐严格按以下主线推进：

```text
基线与限制
  → 文献集修订、导入诊断与核心数据模型
  → 安全上传和增量导入状态机
  → 流式解析、文件级诊断和批量入库
  → 数据库去重、重复组与详情分页
  → AI 结果数据库化
  → 人工审阅前后端切换
  → 导出与质量评价维度衔接
  → PDF 存储加固
  → 删除旧 XML/JSON 主数据路径
  → 10 万篇容量测试与上线
```

不能先删除 XML/JSON，再补齐数据库消费者；也不建议先改前端 ID 而后端仍靠文件名查询。去重前端分页必须建立在结构化去重组 API 上，不能先对当前被截断的 100 组数组做一个看似完整的客户端分页。每一阶段都应保持可运行，并由自动化测试约束输入输出。

## 11. 完成定义

只有同时满足以下条件，才能认为数据库化改造完成：

- 导入、去重、AI 初筛、人工审阅、统计、导出和质量评价衔接均不依赖单篇 XML/JSON。
- 新增或删除索引只处理受影响来源，既有文献不会因全局重新编号而重写；文献集修订冲突不会覆盖新数据。
- 单次 100 个文件、200 MiB、100,000 篇的限制在代理、Web、任务和 Parser 各层行为一致。
- 所有支持格式都有安全异常处理；无法流式处理的格式有单独上限和明确提示。
- EndNote、内部 XML 和 Elsevier/Embase XML 的字段与诊断结果不低于 `v1.5.0` 基线，0 条可用文献明确失败。
- 删除一个来源后，其他来源的检测、解析、异常和缺摘要统计保持不变。
- 导入失败、取消、重复投递和并发执行不会发布半套数据。
- 结果和扣费具有幂等性。
- 列表、统计和分页由数据库完成，不进行项目级文件扫描。
- 所有重复组及组成员均可通过分页访问，不存在前 100 组截断，项目接口不携带完整去重详情。
- 去重、AI和人工审阅结果绑定明确的文献集修订，旧版本不会冒充当前结果。
- 质量评价偏倚风险、适用性、待定和不适用在页面、图表、Excel 和报告中使用同一数据语义。
- 质量评价 PDF 保存在私有文件/对象存储，访问经过鉴权，数据库保存可审计元数据和关系。
- API 契约、OpenAPI、环境变量模板、运维文档和前端验收用例同步更新。
- 目标服务器完成 100,000 篇容量、并发、故障恢复和备份恢复演练。

## 12. 实施时预计涉及的主要代码区域

- `core/models.py` 与新增 migration。
- 新增文献集修订、导入批次、导入文件、诊断问题和去重运行领域服务。
- `core/api/file_views.py`、`core/artifacts/services.py` 中现有上传/删除联动逻辑。
- `core/screening/executors/parse_handler.py`。
- `core/screening/executors/dedup_handler.py`。
- `core/screening/executors/ai_screen_handler.py`。
- `core/screening/services/input_selector.py`。
- `core/screening/services/result_repository.py`。
- `core/screening/services/review_query.py`、人工审阅 API 和服务。
- 新增去重运行、重复组和组成员分页 API、Serializer 与权限测试。
- `core/screening/executors/export_handler.py` 与各导出器。
- `core/quality/services/reference_service.py`。
- `core/quality/api/reference_views.py`、`core/quality/executors/qa_eval.py`。
- 前端 `StepParse.vue`、`StepDedup.vue`、上传/进度、AI 初筛、人工审阅和质量评价页面。
- 前端 screening store 与 API 层中的修订号、分页、取消请求和过期结果状态。
- `.env.example`、settings、Admin、API 契约、OpenAPI 和自动化测试。

本清单用于定位影响面，不建议一次性大提交。每个阶段应独立提交、可测试、可回滚，并避免在同一提交中混入无关重构。
