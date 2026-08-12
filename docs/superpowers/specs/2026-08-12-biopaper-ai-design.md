# BioPaper AI 设计规格

状态：已完成分节设计确认  
日期：2026-08-12  
目标周期：四周内发布可用、可审计、可贡献的开源 MVP  
优先级：论文真实性 > 信息提取准确性 > 功能数量 > 界面美观

## 1. 项目定位

BioPaper AI 是面向生物、医学和生物工程用户的开源“生物医学论文智能检索 + AI 证据提取助手”。它将真实论文来源转换成带字段级出处、缺失值声明和中文解释的实验事实表。

用户输入自然语言问题后，系统生成可审阅检索计划，查询真实数据库，筛选并去重论文，获取摘要与可合法处理的全文，生成中文总结和实验信息证据表，并保留 PMID、PMCID、DOI、来源 URL 和原文依据。

BioPaper AI 不是医疗诊断工具。AI 无权创建论文记录，也不能把没有原文支持的推测写成实验事实。

## 2. 一个月 MVP

MVP 包含：

1. Codex 插件、biopaper CLI 和简洁 Web UI 三个入口，共用同一核心。
2. 中文或英文自然语言转英文关键词、同义词、MeSH 候选、Boolean Query 和筛选条件。
3. 用户可以审阅或修改检索计划后再搜索。
4. PubMed 真实论文、摘要、基础筛选、去重和导出。
5. 使用用户自备 OpenAI API Key 生成基于摘要的中文总结。
6. 对可合法获取的 PMC 或 Europe PMC 全文提取 12 个实验字段。
7. 每个支持字段均能定位回摘要或全文；缺少依据时显示“原文未明确说明”。
8. 约 20 篇人工标注论文的质量评估集和公开评估方法。

MVP 不包含完整引用图、全量实验字段、付费全文绕过、医疗建议或对所有学科的覆盖。

## 3. 开源调研与复用

调研结论截至 2026-08-12：

| 项目 | 许可证 | 可复用能力 | 决策 |
|---|---|---|---|
| u9401066/pubmed-search-mcp | Apache-2.0 | 稳定 Python SDK、PubMed、Europe PMC、OpenAlex、MeSH、去重、全文回退 | 固定版本依赖，放在 adapter 后，不复制成同类 MCP |
| openags/paper-search-mcp | MIT | 多数据源 adapter、CLI/MCP 双入口 | 参考 connector 设计，不引入所有平台 |
| cyanheads/pubmed-mcp-server | Apache-2.0 | PubMed XML、PMC 到 Europe PMC 到 Unpaywall 回退、结构化失败 | 作为实现和测试对照，不引入 TypeScript 运行时 |
| oksure/openalex-research-mcp | MIT | 引用、相似论文和关系网络 | 后续阶段参考 |
| TaewoooPark/scholar-megasearch | MIT | Codex Skill 与安装体验 | 只借鉴交互方式 |

采用“组合依赖，自研证据层”路线。pubmed-search-mcp 负责成熟检索能力；BioPaper AI 自己拥有检索计划、统一论文模型、实验证据 schema、原文定位、缺失值约束、中文证据表、质量评估和三个入口。

项目建议使用 Apache-2.0。所有依赖和借鉴记录到 THIRD_PARTY_NOTICES.md。复制或修改 Apache-2.0 文件时保留许可证、归属及 NOTICE，并显著标记修改。

## 4. 架构

架构原则：

- 三个薄入口，一个共享核心。
- 检索与 AI 解耦；没有 OpenAI Key 仍可搜索和导出。
- 外部系统只通过 ports 和 adapters 接入。
- AI 候选值通过 schema、标识符、单位和证据定位校验后才能入库。
- 原始数据库记录、原文材料、AI 输出、验证后证据和人工修订分开保存。

主要层次：

| 层 | 组件 | 职责 |
|---|---|---|
| 入口 | Codex Skill + MCP | Agent 工具和研究流程编排 |
| 入口 | Typer + Rich CLI | 本地搜索、审阅、提取和导出 |
| 入口 | FastAPI + Next.js | 搜索、筛选、证据表和论文详情 |
| 应用 | Search Plan | 意图、关键词、MeSH、Boolean Query |
| 应用 | Search Pipeline | 搜索、标准化、去重、筛选、排序 |
| 应用 | Evidence Pipeline | 分段、提取、核验、证据表 |
| 领域 | Paper、Evidence、Provenance | 稳定业务契约和真实性约束 |
| Adapter | Search、Fulltext、Entity、AI | 隔离第三方 API 和上游 SDK |
| 数据 | SQLite + artifacts | 查询、论文、证据、运行记录和合法原始材料 |

## 5. 技术栈

- Backend：Python 3.11+、FastAPI、Pydantic v2、SQLAlchemy 2、Alembic、HTTPX。
- CLI：Typer + Rich。
- MCP：Python MCP SDK。
- Codex 插件：plugin.json、Skills 和 MCP server 声明。
- Frontend：Next.js + TypeScript。
- Database：SQLite 起步，通过 SQLAlchemy 和 Alembic 保留 PostgreSQL 迁移能力。
- AI：OpenAI Responses API 和 Structured Outputs；模型由配置指定。
- 质量：pytest、pytest-asyncio、Ruff、mypy、契约 fixtures 和科学质量 evals。

## 6. 目录

    biopaper-ai/
    ├── .codex-plugin/plugin.json
    ├── skills/biopaper-research/SKILL.md
    ├── mcp/server.json
    ├── backend/
    │   ├── pyproject.toml
    │   ├── migrations/
    │   ├── src/biopaper_ai/
    │   │   ├── domain/
    │   │   ├── application/
    │   │   │   └── ports/
    │   │   ├── adapters/
    │   │   │   ├── search/
    │   │   │   ├── fulltext/
    │   │   │   ├── enrichment/
    │   │   │   ├── ai/
    │   │   │   └── persistence/
    │   │   ├── entrypoints/api/
    │   │   ├── entrypoints/cli/
    │   │   ├── entrypoints/mcp/
    │   │   ├── schemas/
    │   │   ├── config.py
    │   │   └── errors.py
    │   └── tests/
    │       ├── unit/
    │       ├── contract/
    │       ├── integration/
    │       ├── fixtures/
    │       └── evals/
    ├── frontend/
    ├── docs/
    ├── examples/
    ├── scripts/
    ├── THIRD_PARTY_NOTICES.md
    ├── CONTRIBUTING.md
    ├── SECURITY.md
    ├── LICENSE
    └── README.md

domain 不依赖 FastAPI、MCP、OpenAI 或具体数据库。application 只编排用例并依赖 ports。adapters 处理第三方变化。API、CLI 和 MCP 不复制业务逻辑。

## 7. 数据流

自然语言问题经过以下流程：

1. 生成 SearchPlan。
2. 用户审阅或修改检索式。
3. 查询真实数据库。
4. 映射为 Canonical Paper。
5. 按 DOI、PMID、PMCID、标题加年份分级去重。
6. 应用年份、类型、全文、物种等筛选。
7. 获取摘要及可合法处理的全文。
8. 按章节和段落切分，保留定位信息。
9. AI 生成临时候选值。
10. 执行 schema、ID、数值、单位和证据定位校验。
11. 保存正式 Evidence Record。
12. 仅由已验证字段生成中文总结和证据表。
13. 导出 CSV、XLSX、JSON 或 Markdown。

## 8. 数据契约

Canonical Paper 保存标题、作者、年份、期刊、发表类型、摘要、PMID、PMCID、DOI、OpenAlex ID、来源记录 ID、原始 URL、检索时间、响应哈希、全文通道和许可信息。

Evidence Record 保存：

- field、value、normalized_value 和 unit。
- status。
- 短证据片段、章节、段落 ID、字符偏移、来源、PMID、PMCID 和 URL。
- extraction_method、provider、model、schema_version 和 prompt_version。
- confidence 只作为调试和人工复核信号，不作为校准后的科学概率。

状态定义：

- supported：有可定位证据。
- not_reported：已检查可用文本但原文未明确说明。
- not_applicable：字段不适用于该研究。
- abstract_only：只有摘要证据。
- conflicting：不同位置或版本出现冲突。
- validation_failed：候选值未通过校验，不进入正式证据表。

MVP 的 12 个字段：

1. 研究类型
2. 研究对象
3. 动物种类
4. 动物品系
5. 样本量
6. 实验分组
7. 干预物或菌株
8. 剂量
9. 给药方式
10. 实验周期
11. 检测指标
12. 主要结果

## 9. 真实性和合法性

- 论文必须先由真实数据库返回；AI 不得创建论文。
- PMID、PMCID 和 DOI 只接受数据库值或官方 ID 转换结果。
- supported 字段必须有关联原文片段。
- 摘要证据和全文证据分级显示。
- 中文总结只能使用已验证元数据和证据，并标明“基于摘要”或“基于全文”。
- 默认导出短证据片段和定位信息，不重新分发整篇全文。
- PMC 自动获取只使用其允许的 API 或数据服务，并逐篇遵守许可条款。
- “免费阅读”不等同于“可自由再分发”。

## 10. 去重、筛选与排序

去重优先级为标准化 DOI、PMID、PMCID、标准化标题加年份。标题回退只能产生候选合并，必须保留模糊匹配标记和所有来源记录。

MVP 支持年份、关键词、发表类型、动物、细胞、临床、Review、RCT、Meta-analysis、全文、Open Access、期刊和物种筛选。即使固定版本的上游 SDK 能返回 OpenAlex 数据，MVP 也不把引用数或引用关系列为稳定契约；它们在后续生产化接入 OpenAlex 后提供。

MVP 排序优先使用可解释信号：数据源原始顺序、标题和摘要匹配、年份及筛选符合度。AI 重排不是第一阶段必要功能。

## 11. API、费用和密钥

| 服务 | 用途 | 费用和密钥 |
|---|---|---|
| NCBI E-Utilities | PubMed 搜索、摘要、MeSH | 免费；NCBI Email 必填；Key 可选。无 Key 不超过 3 req/s，有 Key 默认 10 req/s |
| PMC APIs | PMCID、JATS、BioC | 免费，无 Key；逐篇遵守许可 |
| Europe PMC | 元数据、OA 全文、注释 | 公共 API 免费，通常无 Key；遵守内容许可和批量政策 |
| OpenAlex | 引用和相似论文 | 基础小规模使用免费；正式使用建议申请免费 Key |
| PubTator 3 | 生物实体和关系 | 免费，无 Key；不超过 3 req/s |
| OpenAI Responses API | 检索计划、中文总结、证据提取 | 付费，用户自备 Key |
| pubmed-search-mcp | 聚合检索基础 | Apache-2.0；使用 NCBI Email，可选 NCBI/OpenAlex Key |

配置：

    BIOPAPER_NCBI_EMAIL=
    BIOPAPER_NCBI_API_KEY=
    BIOPAPER_OPENAI_API_KEY=
    BIOPAPER_OPENAI_MODEL=
    BIOPAPER_OPENALEX_API_KEY=
    BIOPAPER_DATABASE_URL=sqlite:///./biopaper.db

密钥不得写入数据库、日志、导出、URL 或前端 bundle。Web UI 只调用本地 FastAPI。系统支持 no-AI 模式。AI 结果按论文、原文哈希、schema、provider、模型和 prompt 版本缓存。

## 12. 入口契约

CLI 首批命令：

    biopaper plan QUERY
    biopaper search QUERY
    biopaper paper IDENTIFIER
    biopaper summarize IDENTIFIER
    biopaper evidence IDENTIFIER
    biopaper export RUN_ID
    biopaper doctor

交互终端默认展示 SearchPlan 供确认或修改；脚本模式必须显式接受计划或提供已保存计划。

MCP 首批工具：

- plan_search
- search_papers
- get_paper
- summarize_paper
- extract_evidence
- build_evidence_table
- export_results

工具返回稳定结构化输出、来源计数、部分失败、run ID 和 artifact 定位信息。Codex Skill 必须区分数据库原始信息与 AI 派生信息。

Web UI 包含首页、可编辑检索计划、带筛选器的论文列表、证据表和论文详情。

## 13. 错误处理与降级

统一错误：

- source_unavailable：尝试可用来源；主 SDK 失败时可降级 native PubMed。
- rate_limited：携带建议重试时间，遵守 Retry-After。
- paper_not_found：不生成占位论文。
- fulltext_unavailable：明确降级为仅基于摘要。
- license_restricted：只保留元数据和原页链接，不绕过限制。
- ai_key_missing：继续搜索和导出，跳过 AI。
- ai_output_invalid：有界重试一次，仍失败则进入人工检查。
- evidence_unsupported：不进入正式证据表。
- partial_result：返回成功数据和逐源失败列表。

只对超时、429 和 5xx 重试。输入错误、404、许可限制和确定性 schema 错误不无限重试。所有外部服务使用独立限流、指数退避、抖动、超时和短期缓存。

## 14. 测试与质量门槛

测试分为：

1. 单元测试：去重、字段状态、单位、证据定位、许可。
2. 契约测试：锁定上游 SDK 和各数据库响应结构，默认离线运行。
3. 集成测试：少量固定 PMID 调用真实接口，单独运行。
4. 端到端测试：CLI、MCP 和 API 对相同查询得到一致标识符集合。
5. 科学质量 eval：约 20 篇人工标注论文的 12 字段黄金集。

发布门槛：

- PMID、PMCID 和 DOI 不由 AI 生成。
- 黄金集论文身份准确率 100%。
- 无证据字段误填目标为 0；未达到时不得声称证据提取稳定。
- 每个 supported 片段可定位回摘要或全文。
- 去重测试覆盖 DOI、PMID、PMCID、标题回退和冲突。
- AI 首次 schema 合格率目标不低于 95%，失败进入明确状态。
- 发布运行单元测试、契约测试、类型检查、lint 和固定样本 eval。

## 15. 四周计划

第 1 周：开源仓库、领域模型、pubmed-search-mcp adapter、native PubMed fallback、SearchPlan、去重、CLI、JSON/CSV 导出和真实性验证。

第 2 周：结构化摘要、中文摘要总结、no-AI 降级、FastAPI、Codex Skill、MCP tools 和三入口一致性测试。

第 3 周：PMC/Europe PMC 合法全文、段落定位、12 字段 Evidence、Grounding Guard、CSV/XLSX/JSON/Markdown 证据表和约 10 篇初始黄金集。

第 4 周：最小 Next.js UI、实验性 PubTator、约 20 篇黄金集、质量评估、Docker、安装文档、中英文 README 和公开发布。

## 16. 第一阶段 14 项任务

1. 创建 Git 仓库和开源文件。
2. 配置 Python 包、测试、lint、类型检查和 CI。
3. 定义 Paper。
4. 定义 Provenance。
5. 定义 SearchPlan 和筛选。
6. 定义 SearchProvider port。
7. 接入 pubmed-search-mcp adapter。
8. 固定依赖并添加契约测试。
9. 实现 native PubMed fallback。
10. 实现 OpenAI SearchPlan 生成器。
11. 实现 SearchPlan schema 校验和可编辑输出。
12. 实现搜索用例和基础去重。
13. 实现 Typer CLI 与 JSON/CSV 导出。
14. 用固定查询完成端到端真实性验证。

第一阶段不做 Web UI、全文 AI 阅读、完整证据表、PubTator、OpenAlex 或引用网络。

## 17. 开源发布

发布应包括 Apache-2.0、第三方归属、贡献指南、安全政策、行为准则、中英文 README、可复现示例、评估命令、已知限制、路线图和 contributor-friendly issues。

一个月成功标准是公开仓库、可安装版本、可运行演示、至少一条贯通 CLI/插件/Web 的工作流、公开质量评估、少量真实科研用户反馈，以及诚实的 commit、issue 和维护记录。

项目准备完成并通过验证后，已获得用户授权直接创建公开 GitHub 仓库并上线。发布动作仍须以测试、许可证检查、密钥扫描和发布清单全部通过为前提。

## 18. MVP 后续阶段

- 检索扩展：将第 3 周用于合法全文的 Europe PMC 通道生产化，并正式接入 OpenAlex、跨库去重、引用数和更完整筛选。
- 证据扩展：扩展实验字段、单位标准化和完整证据表。
- 实体扩展：将第 4 周的实验性 PubTator 接入生产化，加入实体对齐和带来源关系图。
- 引用扩展：基于 OpenAlex 提供引用网络、相似论文和 Citation Graph。

## 19. 风险

- 上游 SDK 活跃变化：锁版本、adapter 隔离、契约测试。
- 全文许可差异：逐篇保存权利信息，不把免费阅读等同于可再分发。
- 信息存在于补充材料和图表：MVP 明示文本覆盖范围。
- AI 结构正确但语义错误：字段证据、黄金集和人工复核共同约束。
- 四周期限紧：Web UI 和 PubTator 保持最小切片，不挤占真实性测试。

## 20. 设计验收

用户已分节批准复用路线、系统架构、技术栈、目录、数据流、真实性机制、API 和密钥策略、错误处理、测试策略及四周计划。

用户审阅并确认本规格文件后，下一步必须使用 Superpowers writing-plans 生成逐项实施计划，然后才能创建业务代码。
