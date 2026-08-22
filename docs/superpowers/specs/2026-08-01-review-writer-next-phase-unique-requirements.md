# Review-Writer 下一阶段唯一需求依据

状态：`APPROVED`
批准日期：2026-08-01
决策比例：`B 80% + A 20%`

## 1. 结论与主目标

本阶段唯一主目标是：以“可见光驱动烯烃双官能化”为第二条真实主题，在 Codex 内完成一次 corpus-first、20–40 篇论文的大综述闭环，验证系统不依赖三论文特例；同时用 20% 工作收口唯一产品入口、真实 Dashboard 路径和可恢复的多会话调度。目标用户是已经知道要总结哪些论文或洞察什么主题、并能准备原始论文与化学解析的研究者。用户完成输入后，系统应在无人继续操作的情况下，于 12 小时内生成可读、可审计、可打开的 DOCX/PDF。

## 2. 权威基线

执行前必须在本地 execution authority record 填写并冻结：

```text
SPEC_ID=
BASE_WORKTREE=
BASE_BRANCH=
BASE_HEAD=
BASE_PARENT=
INTEGRATION_WORKTREE=
INTEGRATION_BRANCH=
AUTHORITATIVE_PROJECT_ID=
AUTHORITATIVE_PROJECT_ROOT=
INPUT_BUNDLE_ROOT=
CORPUS_STUDY_COUNT=
CORE_STUDY_IDS=
STANDARD_CORPUS_MANIFEST_SHA256=
```

约束：

- `CORPUS_STUDY_COUNT` 必须为 20–40；产品合同必须支持 variable-N，不得固定 `3`、`309` 或本 corpus 的具体数量。
- `CORE_STUDY_IDS` 必须在 T0 前冻结，运行中不得为降低解析要求而缩减。
- 黄金标准 corpus 固定包含 8 篇标准综述、6 份指南和 1 份 ChemDraw stylesheet，并由 manifest hash 绑定。
- 权威顺序为：

```text
Approved Spec
→ execution authority record
→ frozen code revision
→ authoritative project state
```

旧 dual-parse 计划、Round 1/2、历史 checkpoint、旧 checkbox 和旧项目状态均不得扩大本 Spec。

## 3. 范围内 / 范围外

### Must

- 用户唯一入口：主题、5 个 Review Questions、逐论文文件夹、核心论文清单及 Chemical Parse。
- 20–40 篇全部正式完成 MAIN、SI、Generic Parse 和规定的 Chemical Parse 绑定。
- fresh project；不得复制旧项目下游状态。
- Simulated Researcher 通过可见 Dashboard 完成保守科学判断。
- 每篇论文由独立 Content Agent 生成 Paper Evidence。
- 按 5 个 Review Questions 综合，最终由单一写作者形成权威 manuscript。
- 输出 DOCX、PDF、artifact manifest、claim/source audit、覆盖率及不确定性披露。
- T0 后无人参与，12 小时内成功或生成固定终止报告。

### Should

- 黄金基准达到 `score >= 90`。
- 在不突破 12 小时和代码冻结线的前提下，提高分子覆盖率及论文间比较密度。
- 失败后可由新调度会话依据持久化状态继续，而非依赖原会话上下文。

### Won’t

- 开放式论文 discovery。
- 第二个新主题或第二套大 corpus。
- QoderWork 验收或迁移。
- 要求全部分子 100% `CONFIRMED`。
- 将全局 80% 分子覆盖率设为 release hard gate。
- 自动生成新的科学综合图。
- 新 Provider、RAG、SaaS、部署或多用户能力。
- 框架、数据库或设计系统重构。
- 投稿、发布或真实领域专家签字背书。

### 仅允许修复的 P0/P1

只有以下问题可以重开代码冻结：

- variable-N 阻断 20–40 篇运行；
- 强制输入无法正式绑定、校验或保持 current；
- Source Truth、科学状态或 workflow gate 相互矛盾；
- Dashboard/Playwright 主路径不可用；
- Content Agent 不隔离，或 Evidence/Synthesis 无法闭环；
- benchmark、DOCX/PDF 或最终 audit 无法完成；
- fresh project 被旧状态污染；
- 敏感路径、raw JSON、MolBlock、token、session 或 auth 信息泄露；
- 调度器无法接管、恢复或在预算内终止。

其余均记为 `MVP_BACKLOG`，不得继续扩展审计。

## 4. 科学与产品合同

### 4.1 唯一输入合同

用户提交主题及 5 个 Review Questions。本次权威运行冻结为：

1. 主要键组合、反应模式及活化策略是什么？
2. 条件如何影响表现，哪些结果不可直接比较？
3. 底物范围、耐受性、选择性和局限是什么？
4. 机制证据处于什么层级，作者解释之间有哪些冲突？
5. 通用性、选择性、放大、资源效率和机制确定性还存在哪些缺口？

设论文数为 `N`、核心论文数为 `K`，T0 前必须满足：

```text
MAIN_PDF_READY=N/N
SI_PDF_READY=N/N
GENERIC_MAIN_READY=N/N
GENERIC_SI_READY=N/N
CHEMICAL_MAIN_READY=N/N
CHEMICAL_CORE_SI_READY=K/K
SOURCE_TRUTH_CURRENT=true
```

每个 study 必须拥有唯一、hash-bound、current 的 source/MAIN/SI/Generic/Chemical binding。缺失、损坏、错绑、跨论文复用、hash 不一致或 stale 一律阻断，不得降级为 warning。

禁止手改解析内容或项目 JSON 制造状态。原始 MAIN/SI PDF 是科学仲裁源；Generic Parse 提供正文、页码、locator、图表基础层；Chemical Parse 提供化学增强层。非核心 SI 若化学信息仍不足，不再打断用户，而应保守改写、排除精确结论或登记 `BLOCKED`。

### 4.2 Honest Progressive

分子状态仅允许：

- `CONFIRMED`：原始 MAIN/SI 唯一支持，且 Simulated Researcher 已明确确认。
- `AI_PROVISIONAL`：有 locator、provenance、confidence 和未确认标记的候选。
- `BLOCKED`：无法唯一确定，`value=null`，并记录 gap reason。

每条状态必须保留 actor、timestamp、locator、provenance 和 freshness。Simulated Researcher 的 actor 必须明确，不得表述为“真实用户已接受”。

禁止猜测结构、用 R-group/`[*]`/抽象标签充当最终结构、以语法有效代替科学正确、自动修改已有有效 confirmed 值，或把 provisional 当作精确事实。

全体分子覆盖率只披露，不作为 release hard gate。任何进入正文的精确 material claim，其全部实际结构依赖必须 100% `CONFIRMED`，并通过独立二次科学复核；否则必须降级、排除或阻断。

### 4.3 Agent 与运行合同

- Simulated Researcher、独立科学 Reviewer、黄金基准 Reviewer：仅使用 `5.6 sol max`。
- 调度、Content、Synthesis、Drafting、Merge 和普通 QA：仅使用 `5.6 luna max`。
- 不得静默替换模型。
- Researcher 只能使用 Playwright 操作可见 Dashboard；禁止直接 API、page evaluation、内部 JSON、storage 或脚本代填。
- 脚本不得冒充 Content Agent。
- 每篇论文一个隔离 Content Agent；不得跨 study 复用结论。
- Synthesis 按 Review Question 隔离并行。
- 权威 manuscript 只有一个写入者。
- 最大并发为 `min(4, Codex 可用并发)`。
- 同一个 immutable task 最多两次尝试。
- 主调度器必须轻量、状态驱动、可替换；至少发生两次由全新调度会话完成的接管，并留下交接 artifact。
- 用户完成输入及 Chemical MinerU 后，不再执行任何步骤。

T0 仅在以下条件同时成立时记录：

```text
INPUT_READY=OK
CODE_FREEZE_READY=OK
RUNTIME_READY=OK
```

从 T0 到终止报告的墙钟时间不得超过 12 小时。代码冻结后最多两轮 P0/P1 修复；benchmark 最多两轮定向改稿。

### 4.4 Evidence、Synthesis 与文稿

- Corpus 中每篇论文必须在 Evidence ledger 中具有明确去向：有效 Evidence、带理由排除，或明确 blocker；不得静默遗漏。
- 关键 claim 必须有 MAIN/SI page、figure、table 或 section locator。
- Synthesis 只能消费 current Evidence，并保留证据强度、冲突和不可比较边界。
- 不支持内容不得写成事实。
- 最终正文使用学术英语和 ACS 数字引用，覆盖全部 5 个 Review Questions，并含跨论文比较表。
- 文稿必须披露数据覆盖率、`CONFIRMED / AI_PROVISIONAL / BLOCKED` 数量、逐论文覆盖率、gap registry 和模拟审阅身份。
- DOCX/PDF 必须来自同一权威 manuscript。

### 4.5 黄金基准

黄金 corpus 仅用于写作质量、结构和规范评估，不得进入本次科学证据链。

硬门：

```text
benchmark_score >= 80
hard_fails = []
```

`score >= 90` 为 Should。两轮定向改稿后仍未达到硬门，返回 `BENCHMARK_BLOCKED`，不得无限改稿。

## 5. 角色与权限

| 角色 | 权限 | 禁止 |
|---|---|---|
| 真实用户 | 提供主题、问题、完整 MAIN/SI、Chemical Parse 和核心论文清单 | T0 后补判断、操作 Dashboard 或批准结构 |
| Simulated Researcher | 用 Sol + Playwright 完成保守判断和 gap 登记 | 改代码、直接 API、猜测结构、冒充真实用户 |
| Content Agent | 用 Luna 处理唯一 study 并生成 Paper Evidence | 跨 study 推断、写权威 manuscript |
| Synthesis Agent | 用 Luna 处理唯一 Review Question | 绕过 Evidence、修改 Source Truth |
| Merge/Polish Agent | 单独写入权威 manuscript并统一文风 | 修改科学状态或输入绑定 |
| Integration Coordinator | 集成经审查的最小 commit、冻结代码、启动权威 run | 自批 commit、借机开发新功能 |
| 独立 Reviewer | 只读审查代码、UI、科学决定、benchmark 和 artifacts | 修代码或批准自己的工作 |

任何 Owner 不得批准自己的 commit。Reviewer finding 只能交给全新的、单一 finding 范围内的 Repair Owner；Reviewer 自身不得修复。

## 6. 完成标准与失败类别

### 6.1 成功必须同时返回

```text
SCALED_CODE_READY=OK
SCALED_INPUT_READY=OK
SCALED_RUNTIME_READY=OK
SCALED_REVIEW_READY=OK
```

判定依据：

- `SCALED_CODE_READY`：frozen revision 已记录；focused regression、`make smoke`、`make quality-check`、Git diff/show checks 全部通过；无未解决 P0/P1。
- `SCALED_INPUT_READY`：所有 N/K 输入计数满额、binding/currentness 通过、fresh isolation audit 通过。
- `SCALED_RUNTIME_READY`：真实 Dashboard/Playwright 路径完成；至少两次调度接管；T0 后用户操作数为 0；未使用脚本/API 冒充产品路径。
- `SCALED_REVIEW_READY`：全部论文有 Evidence 去向，5/5 Synthesis current，benchmark 硬门通过，同源 DOCX/PDF 可打开，claim/source 与 artifact audit 通过。

### 6.2 一级失败类别

只允许：

```text
CODE_BLOCKED
INPUT_BLOCKED
PARSE_BLOCKED
ORCHESTRATION_BLOCKED
SCIENTIFIC_DECISION_BLOCKED
CONTENT_EVIDENCE_BLOCKED
SYNTHESIS_BLOCKED
BENCHMARK_BLOCKED
EXPORT_BLOCKED
AUDIT_BLOCKED
```

超过 12 小时使用 `reason_code=TIME_BUDGET_EXCEEDED`；若无更精确主因，归入 `ORCHESTRATION_BLOCKED`。科学不确定性只有在保守排除后仍无法回答必需 Review Question 时，才升级为 `SCIENTIFIC_DECISION_BLOCKED`。

每个 blocker 必须给出受影响对象、已完成的不依赖工作以及唯一恢复动作。出现 blocker 后仍须完成所有独立工作，并在预算终点停止。

### 6.3 固定无人值守终止报告

```text
SPEC_ID=
RUN_ID=
FROZEN_CODE_HEAD=
AUTHORITATIVE_PROJECT_ID=
CORPUS_STUDY_COUNT=
CORE_STUDY_COUNT=

T0=
TERMINATED_AT=
ELAPSED_SECONDS=
TIME_BUDGET_SECONDS=43200

SCALED_CODE_READY=
SCALED_INPUT_READY=
SCALED_RUNTIME_READY=
SCALED_REVIEW_READY=

BLOCKERS=
REASON_CODE=
AFFECTED_OBJECTS=
COMPLETED_INDEPENDENT_WORK=
UNIQUE_RECOVERY_ACTION=

MAIN_PDF_READY=
SI_PDF_READY=
GENERIC_MAIN_READY=
GENERIC_SI_READY=
CHEMICAL_MAIN_READY=
CHEMICAL_CORE_SI_READY=
SOURCE_TRUTH_CURRENT=

CONFIRMED_COUNT=
AI_PROVISIONAL_COUNT=
BLOCKED_COUNT=
PER_STUDY_COVERAGE_ARTIFACT=
GAP_REGISTRY_ARTIFACT=

PAPER_EVIDENCE_CURRENT=
PAPER_EVIDENCE_DISPOSITIONED=
SYNTHESIS_CURRENT=
MANUSCRIPT_CURRENT=
CLAIM_SOURCE_AUDIT=
BENCHMARK_SCORE=
BENCHMARK_HARD_FAILS=
BENCHMARK_ROUNDS=
DOCX_READY=
PDF_READY=
ARTIFACT_MANIFEST=

ORCHESTRATOR_TAKEOVERS=
USER_ACTIONS_AFTER_T0=
OWNER_REPORTS=
FOCUSED_TESTS=
SMOKE=
QUALITY_CHECK=
GIT_SHOW_CHECK=
GIT_STATUS=

MVP_BACKLOG=
PUSHED=false
DEPLOYED=false
PLAN_CHECKBOX_CHANGED=false
SENSITIVE_DATA_EXPOSED=false
```

报告中的 artifact 引用必须使用项目相对路径、稳定 ID 或 digest，不得泄露私密绝对路径或内部状态。

## 7. 建议的执行切分

1. **Input & Provenance Owner**  
   负责 variable-N manifest、正式输入生命周期、binding/hash/currentness、fresh isolation 和 zero-write failure；不得写下游科学内容。

2. **Scientific State & Evidence Owner**  
   负责 Honest Progressive、gap registry、精确 claim 依赖规则和 Paper Evidence 合同；不得修改 Dashboard、调度或导出。

3. **Orchestration & Dashboard Owner**  
   负责唯一入口、真实 Dashboard/Playwright 路径、可恢复状态机、会话接管、并发/重试/时间预算；不得代做科学判断或写 manuscript。

4. **Synthesis, Manuscript & Export Owner**  
   负责按 5 个问题综合、单写者 manuscript、ACS 引用、比较表、benchmark、DOCX/PDF 和 artifact audit；不得修改输入合同。

5. **Integration Coordinator**  
   只集成四个已独立审查的最小 commit，运行统一 regression，建立 authority record，冻结代码并启动唯一权威运行；不得增加新功能。

独立审查关系：

- Luna Reviewer：代码、合同、Git、worktree 隔离、安全和敏感数据。
- Sol Reviewer：Playwright 主路径、科学决定、精确事实依赖和黄金基准。
- Owner 与 Reviewer 必须为不同会话；任何 Reviewer 不改代码。
- Repair Owner 不是第六条常驻工作流，仅在 P0/P1 finding 出现时新建，并严格限定为该 finding。
- 初始 Owner 不得用单一会话串行承担完整流水线。

## 8. 明确不做与 backlog 停车场

### 本阶段明确禁止

- 单会话完成全部开发与运行。
- 脚本冒充 Content Agent。
- API 调用冒充 Dashboard 用户路径。
- 重开旧计划 checkbox、历史 checkpoint 或 Round 协议。
- 为寻找新问题无限审计。
- 为通过测试删除论文、降低输入门禁、伪造 READY 或隐藏 blocker。
- push、deploy、发布、远程写。
- 清理历史 worktree、reset、checkout 丢弃既有状态。
- 复制旧项目的 decisions、Evidence、Synthesis、Content Agent result、Manuscript、Release、Evaluation、Credits 或浏览器状态。

### `MVP_BACKLOG`

- 第三个真实主题与跨主题验证。
- 开放式 discovery。
- QoderWork 路径。
- 非阻断 Dashboard 视觉与交互优化。
- 更高分子覆盖率及更多精确结构结论。
- 自动科学综合图和投稿级图形系统。
- 多 Provider、RAG、SaaS、部署及多用户能力。
- 超出本 corpus 所需的性能和基础设施重构。

按 `spec` skill 的可执行性约束，本草案已将成功条件绑定到可见状态、命令和 artifacts；未执行该 skill 的 issue filing、归档或 Agent 启动步骤。本轮未修改文件，也未运行测试。

