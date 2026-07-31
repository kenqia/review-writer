# Review Writer 双层解析证据增强与小综述完整闭环需求设计

日期：2026-07-30
状态：用户已批准设计，待据此编制实施计划
目标产物：三篇 core 论文的小综述 `SELF_REVIEWED_DRAFT`

## Fresh v3 Honest Progressive Contract

<!-- FRESH_V3_CONTRACT_START -->

This is the normative contract for every fresh v3 execution. The route never
converts a candidate into a confirmed fact and never uses zero as a substitute
for an unknown or unavailable state.

### Three-state scientific value

Every authoritative molecule row uses exactly one state:

| State | Value | Required evidence | Allowed use |
|---|---|---|---|
| `CONFIRMED` | non-null | PDF locator and researcher confirmation | precise scientific claims |
| `AI_PROVISIONAL` | non-null | PDF locator, confidence, and provenance | explicitly provisional internal views only |
| `BLOCKED` | `null` | non-empty `gap_reason`; locator when available | limitation/gap disclosure only |

`CONFIRMED` is never inferred from an AI candidate. `AI_PROVISIONAL` must keep
its PDF locator, confidence, and provenance. `BLOCKED` must keep
`value=null` plus `gap_reason`. The researcher-safe projection may expose
status, safe locator, confidence, provenance, and gap reason, but never raw
paths, hashes, JSON, MolBlocks, tokens, sessions, or internal IDs. Append-only
history is immutable; actor mismatch is disclosed as provenance residual.

### Fresh v3 initial state

When the fresh project has only verified PDFs and fresh Generic current, with no
authoritative Chemical cohort yet:

- `availability/status` is `unknown/unavailable`, never `ready/current`;
- `core_denominator`, `confirmed_count`, `ai_provisional_count`,
  `blocked_count`, `coverage_ratio`, `coverage_sufficient`, and `gap_registry`
  remain unknown/null; none is compressed to `0` and no empty `gap_registry`
  is fabricated;
- the only next action is `待 Chemical Paper 导入`; after the first approved ZIP
  has completed safe preflight and awaits confirmation, the only next action is
  `确认第一份 Chemical Paper 导入`;
- credits are displayed only as `NOT_APPLICABLE_BY_CURRENT_SCOPE`.

No new next action is allowed to compete with those labels. `gap_registry` is
created only after authoritative molecule rows exist.

### Formal Chemical import and v3 counting

Only after all three approved Chemical inputs have completed formal
preflight/confirm/import and are `3/3 current` may the server validate pages
`6/11/11`, molecule counts `125/109/75` (project total `309`), and
`reaction_data_status=unavailable_not_provided`. At that point, and only when
authoritative molecule rows exist:

```text
project_denominator = 309
coverage_ratio = (confirmed_count + ai_provisional_count) / 309
coverage_threshold = 0.8
coverage_sufficient = server_calculated(coverage_ratio >= coverage_threshold)
```

The server calculates all counts, denominator, ratio, threshold, and
`coverage_sufficient`; client-supplied counts are untrusted. Missing reaction
data remains `unavailable_not_provided`, never zero.

For the approved-inputs fresh-v3 audit snapshot, the authoritative projection
is `CONFIRMED=0`, `AI_PROVISIONAL=210`, `BLOCKED=99`, so covered rows are
`210/309 = 0.6796116505`. The threshold target is
`ceil(309 * 0.80) = 248`; therefore this snapshot needs **38 additional
traceable candidates** before `coverage_sufficient` can become true. The
per-study slices are ANIE `78/125`, ACS Catalysis `80/109`, and JACS `52/75`;
the project gap registry contains exactly `99` BLOCKED rows. These values are
server-derived audit evidence, not a permission to fabricate or backfill
values; every later change must be append-only and recompute the same formula.

Approved ZIPs enter only through the formal preflight → confirm → importer
path. Never hand-unzip them, use a v2 Generic ZIP, or reuse old Generic
outputs. ZIP/PDF binding and path/hash evidence are Coordinator-only and never
enter Dashboard or Researcher projections.

A current Generic Parse gate may be `approved_with_pdf_locator`: this keeps
automatic Generic extraction fail-closed while still permitting the current
PDF-bound Chemical lane and reconciliation to proceed. It must never be
treated as automatic extraction approval.

### Progressive continuation and role sequence

Honest Progressive permits incomplete work but never permits opaque work. Below
80%, source/evidence preparation may continue with an explicit
`needs_more_traceable_candidates` state; no scientific approval may be
fabricated or silently upgraded.

The Researcher makes visible PDF-bound decisions and supplies confirmation for
`CONFIRMED`; the Coordinator audits binding, path/hash, formal-import, safe-
projection, and gap evidence read-only; the Integration Owner owns Task 10
fresh bootstrap, formal preflight/confirm/import, safe projection, runtime
readiness, and protocol restarts. Only after formal import, safe projection,
and runtime readiness are complete may Task 11 create a new Playwright
Researcher. Content Agents remain candidate-only and study-local.

### Researcher-safe fields

```text
resolved_smiles_status
resolved_smiles
confidence
provenance
gap_reason
actor_provenance_residual
```

<!-- FRESH_V3_CONTRACT_END -->

## 1. 结论

Review Writer 的正式解析路线采用“双层证据增强”，不是 Generic MinerU 与 Chemical Paper 二选一：

```text
原始 PDF（唯一科学真源）
   ├─ Generic MinerU API lane
   │    └─ 正文、章节、表格、图片、caption、页码、bbox 和阅读顺序
   │
   └─ MinerU Chemical Paper manual-export lane
        └─ 分子、MolBlock、来源名称/论文局部标签、SMILES 和化学版面候选

两条解析通道
   ↓ 同一 study identity + 同一 PDF 字节绑定
Dual-source Source Truth Bundle
   ↓
Parse Quality + Chemical Completion + Reconciliation
   ↓
Paper Evidence
   ↓
Comparison Protocol / Coverage / Synthesis Claims / Section Contracts
   ↓
按节起草 + 高风险人工编辑
   ↓
内部自审 DOCX/PDF
```

原始 PDF 始终是唯一科学仲裁源。Generic MinerU 与 Chemical Paper 都是可定位、可核验的候选索引，任何一条解析通道都不能单独构成科学批准。

本轮目标不是投稿或专家发布，而是以一个全新、非覆盖的三篇项目完整跑通一次可恢复、可审计、前端可用、由独立 Agent 模拟研究者决策的内部小综述生产闭环。

## 2. 与既有设计、执行计划和冻结状态的关系

### 2.1 继承

本设计继承并继续执行：

- `2026-07-28-evidence-synthesis-workbench-design.md` 的证据与综合判断工作台、五阶段投影、四个主检查点、高风险人工编辑升级和人工综合图政策；
- `2026-07-28-source-truth-parse-quality-first-loop.md` 的 Source Truth、对象级 Parse Quality、PDF 真源、局部失效和可恢复任务原则；
- `2026-07-28-three-paper-evidence-to-release-complete-loop.md` 已实现的 Typed Paper Evidence、Comparison Protocol、Coverage、Synthesis Claim、Section Contract、Source Figure、manuscript lineage v2、内部 DOCX、benchmark、Hard Fail 和独立 QA 协议；
- QA commit `ff525d55ee2c2e56e2d0f0926e25d8da61ccd2c2` 中 Chemical Paper、安全投影、桌面/平板优先和 Round 2 credits 范围规则；
- frozen integration candidate `9213018b527c0abb7583365311c7a7b1c86c55a7` 中已集成的 Scientific State、Dashboard UI、Release Backend 与 R2-F001–R2-F007 修复链。

### 2.2 取代

发生冲突时，本设计取代 2026-07-30 的临时 Chemical-only 路线：

- Generic MinerU API 不再被排除，而是恢复为所有论文的基础解析层；
- Chemical Paper 不再是唯一结构化输入，而是 core 论文的必需化学增强层；
- Content Agent 不再只能读取 Chemical Paper state，而是读取同一 PDF 绑定、当前、researcher-safe 的双层输入；
- 仍然禁止旧轮次 Generic MinerU 语义结果、stale parse、跨 study Evidence 和旧 Content Agent result 进入新项目。

旧的 `regression-v1`、Round 2 浏览器状态和被隔离的 study2 results 只保留为负向 QA 证据，不得成为新项目输入。

### 2.3 不回写旧计划状态

本设计不修改旧执行计划 checkbox，不把旧 Round 2 宣称为 PASS，也不把已冻结项目修补成新验收项目。后续必须据此创建新的实施计划和全新回归项目。

## 3. 产品目标与非目标

### 3.1 目标

1. 恢复 Generic MinerU 对正文、阅读顺序、caption、表格和原图定位的规模化价值；
2. 使用 Chemical Paper 补充分子、MolBlock、SMILES 和化学版面信息；
3. 用同一原始 PDF 严格绑定两条通道，禁止来源串线；
4. 将双层差异转成可见、对象级、依赖范围明确的 reconciliation item；
5. 对 core 论文建立 formal Chemical import 与 Honest Progressive Completion projection；
6. 让人工工作集中在可追溯候选、解析冲突和高风险科学主张，而不是逐个确认全部已存在字段；
7. 保留现有 Evidence-to-Release 工程成果并避免重新实现已闭合 finding；
8. 用全新 Agent、全新项目和两次真实重启完整跑通三篇小综述；
9. 导出内容真实更新、来源可追溯、benchmark 达标且无适用 Hard Fail 的内部 DOCX/PDF。

### 3.2 非目标

1. 不宣称自动生成“科学完美”、投稿级或可被顶级期刊接收的综述；
2. 不要求 background 论文全部手工生成 Chemical Paper ZIP；
3. 不把 309 个分子设为 fresh v3 的初始 denominator 或全量完成门；正式 3/3 Chemical import 后才核验 309 条 authoritative molecule rows；
4. 不允许 AI 把候选静默升级为 `CONFIRMED`；`AI_PROVISIONAL` 必须保留 PDF locator、confidence 和 provenance；
5. 不自动生成、组合、重绘或补画跨论文科学综合图；
6. 不调用 MinerU 的非公开 Chemical Paper API，不保存 cookie、session、token 或私有任务 URL；
7. 不把 credits 恢复成本轮验收门禁；
8. 不复用旧浏览器、旧决定、旧 Evidence、旧 Content Agent result、旧稿或旧 release 作为新轮科学输入。

## 4. 来源分层与 Chemical Paper 强制范围

来源继续分为 `core`、`background`、`candidate` 和 `excluded`。

### 4.1 Core

每篇 core primary study 必须具备：

- 已验证的原始主文 PDF；
- Generic MinerU API 当前解析；
- Chemical Paper 只有在正式 preflight/confirm/import 后才进入 authoritative cohort；
- 当前的 Parse Quality 与 researcher-safe projection；
- 每条需要精确科学结论的 molecule row 具备合法三态和对应证据；
- 所有依赖对象的 reconciliation 已关闭或明确转 PDF locator。

Fresh v3 可以在 PDF + fresh Generic current、Chemical 尚未正式导入时继续
source/evidence preparation，但 availability/status 必须保持
unknown/unavailable，不能生成伪造的分母、三态计数或 gap registry。
正式 3/3 Chemical current 后才执行 pages `6/11/11`、molecules
`125/109/75=309` 和 `reaction_data_status=unavailable_not_provided` 的计数核验。

当前三篇可见光论文全部是 core，因此在正式导入阶段必须验证 3/3 Generic
current 与 3/3 Chemical current；这不是 fresh v3 初始状态的开始条件。

### 4.2 Background

Background primary study 可以只使用 Generic MinerU API。若某条 background Evidence 依赖分子结构、SMILES、MolBlock 或 Chemical Paper 特有字段，则该 study 必须升级为 Chemical-enhanced，或该 Evidence 保持 blocked/needs review。

## 5. 角色与权限

### 5.1 真实用户

真实用户负责：

- 确认 Review Brief 与 core/background 分层；
- 获取合法可用的原始 PDF；
- 在公开 MinerU Web UI 中为 core PDF 手工执行 Chemical Paper 模式；
- 下载完整原始 Chemical Paper ZIP；
- 最终审阅本轮输出，但不需要参与独立 QA 浏览器中的每个操作。

系统不得要求或保存用户的 MinerU 登录状态、cookie、session、token 或私有任务 URL。

### 5.2 Simulated Researcher Agent

独立完整回归中的所有产品内人工操作由一个全新的 Playwright Researcher Agent 完成。固定 actor 为：

```text
actor_type = simulated_researcher_agent
actor_label = simulated_researcher
```

该 Agent 可以在浏览器中：

- 查看正式导入后的 PDF、两种安全解析投影和 Source Figure locator；
- 对有 PDF 支持的候选作 `CONFIRMED` researcher confirmation，或保留
  `AI_PROVISIONAL`/`BLOCKED` 及其 provenance/gap；
- 作出 Parse、Chemical reconciliation、Paper Evidence、Synthesis、Section、figure slot 和 manuscript 决定；
- 完成高风险正文编辑与逐节批准；
- 触发内部 DOCX 下载；
- 其可见、来源支持的决定构成本轮模拟科学批准。

该 Agent 不得：

- 冒充真实用户或项目所有者；
- 读取仓库、项目文件、数据库、browser storage、请求/响应 body 或内部 JSON；
- 使用 page evaluation、直接 API 或脚本绕过禁用控件；
- 修产品代码、诊断内部根因或自行重启服务；
- 生成缺失的 Evidence/Synthesis/Section/manuscript 候选内容；
- 猜测或伪造 SMILES、名称、locator、confidence 或 provenance；
- 兼任 Content Agent、Integration Owner 或 QA 修复 Owner。

### 5.3 Content Agents

Content Agents 只生成候选科学内容，不进行浏览器研究者批准。每项 study Evidence 必须由独立、study-local 的 Content Agent 生成；下游 Synthesis 和 Section drafting 使用新的、角色明确的 Agents。任何 Content Agent 输出必须经过正式 importer 和 Simulated Researcher Agent 的可见审核。

### 5.4 Integration Owner 与 QA Coordinator

- Integration Owner 只负责 code integration、Task 10 fresh v3 bootstrap、三份 approved Chemical input 的正式 preflight/confirm/import、safe projection、runtime readiness 和收到信号后的两次真实 restart；
- QA Coordinator 只读协调 Task 11 protocol、Coordinator-only binding/path/hash evidence、findings 和 artifact verification；
- 只有 formal import、safe projection、runtime readiness 均完成后，QA Coordinator 才创建新的 Playwright Researcher；
- 产品 finding 返回原 Owner 修复；不得在同一 Reviewer run 中边测边临时补丁后宣称 PASS。

## 6. 双层权威架构

### 6.1 原始 PDF

原始 PDF 是最高等级科学来源。标题、DOI、study identity、文件字节和主文/SI 角色必须先闭合，解析任务和 Chemical ZIP 才能绑定。

### 6.2 Generic Parse Lane

Generic MinerU API 负责：

- canonical Markdown；
- page、bbox、reading order 和 section boundary；
- table、formula、image、caption 和 content-list；
- 原论文图片资产和 Source Figure 候选；
- 检索、定位与 Content Agent 的基础上下文。

Generic parse 仍受对象级 Parse Quality Gate 约束。复杂公式、化学符号、结构、复合图片和表格不因解析成功而自动可信。

### 6.3 Chemical Enhancement Lane

Chemical Paper ZIP 负责：

- molecule array 的稳定源顺序；
- MolBlock；
- 来源名称或论文局部标签；
- expanded/unexpanded SMILES 候选；
- page/bbox 与化学版面候选；
- backend/version、文件 inventory、缺失字段和 immutable import history。

Chemical Paper 输出是候选化学数据，不是科学真源，也不自动批准元素、结构、反应或机制。

### 6.4 双层绑定

两条 lane 必须同时绑定：

- project ID；
- study ID；
- source ID；
- 原始 PDF SHA-256；
- 当前 Source Truth version；
- 各自输入版本与生成时间。

任一绑定不唯一、stale 或不匹配时，零下游写入。

## 7. 权威对象与状态合同

### 7.1 Generic Parse Binding

记录 Generic MinerU 输入/输出身份、parser contract、当前 Source Truth、页数、内容类型、图片/caption 注册和对象级 Parse Quality。

### 7.2 Chemical Paper Binding

记录 PDF/ZIP identity、backend/version、页数、molecule count、reaction status、缺失字段、来源顺序、correction/review history 和 currentness。

### 7.3 Dual-source Binding

证明 Generic Parse 与 Chemical Paper 来自同一原始 PDF。该 binding 是 reconciliation、Content package、manuscript lineage 和 release currentness 的共同上游。

### 7.4 Honest Progressive Route 与 Chemical Completion projection

每个 fresh v3 项目只有一个正式用户面路线名称：`Honest Progressive Route`
（内部枚举 `honest_progressive`）。它不拆分成两套 Completion 门。正式
Chemical import 之前，Chemical availability/status、分母、三态计数、coverage
和 `gap_registry` 都是 `unknown/unavailable` 或 `null`，不得压成 `0`；只有
3/3 current import 后才核验每论文 `125/109/75`、总计 `309` 和
`reaction_data_status=unavailable_not_provided`。

完成正式 import 后，每条 authoritative molecule row 必须且只能有一种状态：

- `CONFIRMED`：值非空，具有 PDF locator，并由研究者确认；可用于精确科学主张；
- `AI_PROVISIONAL`：值非空，具有 PDF locator、confidence 和 provenance；只可用于明确标注的内部候选/趋势视图；
- `BLOCKED`：值必须为 `null`，具有非空 `gap_reason`（有则带 locator），只能进入限制披露和 gap registry。

服务端固定计算：

```text
coverage = (confirmed_count + ai_provisional_count) / 309
coverage_threshold = 0.80
```

所有计数、分母、coverage、threshold 和 `coverage_sufficient` 由服务端产生，
客户端提交的计数不可信。低于 0.80 时可继续 source/evidence preparation，但必须
显示 `needs_more_traceable_candidates`；受影响的精确主张/release path 不能绕过
coverage 或隐藏 gap。缺失/unknown 永远不解释为零。

Chemical Paper 的 `smiles_expanded` 与 `smiles_unexpanded` 仅作候选和 provenance，
不再分别形成输入或门禁；两者都缺失时，研究者可依据 PDF/结构定位补录一次
`resolved_smiles`。论文局部标签如 `3a`、`compound 7`、`intermediate A` 可作为名称，
不要求系统生成 IUPAC 名称。AI 不得猜测、填写或把候选静默升级为 `CONFIRMED`。
`AI_PROVISIONAL` 必须保留 confidence/provenance，`BLOCKED` 必须保留
`value=null`、`gap_reason` 和可见 gap registry。Append-only history 不可改写，
actor mismatch 以 provenance residual 披露。

### 7.5 Reconciliation Registry

每个可比较对象记录：

- `corroborated`：两层一致且 PDF locator 可用；
- `complementary`：只有一层提供信息，另一层不矛盾；
- `conflict`：两层内容不一致；
- `single_lane_only`：只能从一条 lane 定位；
- `pdf_resolved`：研究者已用 PDF 仲裁；
- `needs_review`、`stale` 或 `blocked`。

Reconciliation 不能自动选择 Chemical Paper 或 Generic MinerU 覆盖另一侧。研究者决定必须包含 PDF locator、作用范围、限制、actor、时间和 bound versions。

### 7.6 Impact Edge

Generic reparse、Chemical re-import、SMILES correction、reconciliation decision、Evidence 和 downstream objects 建立对象级 impact edge。上游变化只使依赖对象 stale，不清空未受影响决定，也不把项目全局退回第一阶段。

## 8. 目标全流程

### 8.1 Review Brief

系统形成主题、范围、目标读者、纳排标准、core/background 分层、比较轴、内部稿目标和停止条件草案。Simulated Researcher Agent 在独立回归中通过可见 UI 确认。

### 8.2 Source Set 与 PDF 获取

系统提供论文身份、DOI、来源链接和下载状态。真实用户获取 PDF；系统导入并验证：

- 标题/DOI 与 study identity；
- 主文/SI 角色；
- 重复项；
- PDF 文件类型和字节 identity；
- 来源完整性。

不能仅凭文件名或相似标题猜测绑定。

### 8.3 双通道解析准备

PDF 验证通过后：

1. Generic MinerU API 可以立即启动；
2. 三份 approved Chemical input 由 Integration Owner 通过正式 preflight → confirm → importer 进入 authoritative cohort；
3. Chemical formal import 未完成前，唯一 researcher-readable next action 只能是
   `待 Chemical Paper 导入`，或首份安全 preflight 后的 `确认第一份 Chemical Paper 导入`；
4. 只有 3/3 Chemical current 后才显示 pages `6/11/11`、molecules
   `125/109/75=309` 和 reaction `unavailable_not_provided` 的 authoritative counts。

选择 ZIP 只能触发 formal preflight；confirm/import 必须由正式 importer 原子写入。
不得手工解压、使用 v2 Generic ZIP 或旧 Generic outputs；ZIP/PDF binding 与
path/hash 只进入 Coordinator-only evidence，不能进入 Dashboard/Researcher。

### 8.4 Chemical Completion

工作台只显示 researcher-safe 的候选和缺口。每个 authoritative molecule row
必须是 `CONFIRMED`、`AI_PROVISIONAL` 或 `BLOCKED`：`CONFIRMED` 需要
researcher confirmation 与 PDF locator；`AI_PROVISIONAL` 需要 PDF locator、
confidence、provenance；`BLOCKED` 必须是 `value=null` 并带 `gap_reason`。
不得要求分别填写 expanded/unexpanded，也不得由 AI 猜测或静默批准值。

低于 80% 时仍可进行 source/evidence preparation，但必须显式显示
`needs_more_traceable_candidates`；它不构成科学批准，也不把 blocked rows
压成零或从 gap registry 隐去。

### 8.5 Parse 与 Reconciliation Review

研究者同屏比较 PDF、Generic parse、Chemical Paper 和差异项，只处理：

- reading order、section、table、formula 和 chemistry defect；
- Figure/Scheme/Chart caption 与 fragment identity；
- molecule/SMILES/structure mismatch；
- 两层冲突；
- 会影响 Evidence 的缺失或 locator 歧义。

### 8.6 Paper Evidence

每篇 core study 由新的 study-local Content Agent 生成候选 Evidence。Simulated Researcher Agent 在 PDF 和双层 locator 可见的情况下决定 epistemic type、条件、风险、限制和批准状态。

不得让另一篇 study 的 Evidence、旧轮次结果或旧 reviewer conclusion 进入 package。

### 8.7 Synthesis

沿用已批准工作台：

- Comparison Protocol 必须先于综合；
- Coverage 显示代表性、冲突和缺口；
- Synthesis Claim 显示 supporting/counter evidence、边界、机制等级和不确定性；
- single-study 结论不得伪装为领域共识；
- Section Contracts 固定每节问题、证据预算、反例、Source Figure 和 Synthesis Figure Placeholder。

### 8.8 Manuscript Loop

AI 只依据当前、已批准的 Section Contract、Paper Evidence 和 Synthesis Claim 按节起草。高风险内容固定进入 `needs_human_edit`，由 Simulated Researcher Agent 直接编辑并批准。

### 8.9 Internal Release

系统合并 authoritative manuscript，检查引用、数字、单位、术语、图号、binding、stale 和 Hard Fail，并导出内部 DOCX/PDF。

允许必需综合图保持 `awaiting_human_figure`，但必须显示完整制图 brief；专家发布按钮继续禁用。

## 9. Content Agent 输入合同

Paper Evidence package 按 study 隔离，只允许包含：

- 当前原始 PDF；
- 当前 Generic Parse researcher-safe 层；
- 当前 Chemical Paper researcher-safe 层；
- 当前 Parse Quality 与 Chemical Completion 投影；
- 当前 reconciliation 决定；
- 最小 study identity/binding manifest。

禁止包含：

- raw Chemical JSON 或完整 MolBlock；
- 本地绝对路径、内部 digest、token/session/private URL；
- 另一篇 study 的 Evidence；
- 旧轮次 Content Agent result；
- 旧 manuscript、release、browser/session 或 reviewer conclusion；
- 未经正式 importer 验证的任意 Markdown/JSON。

Synthesis/Section package 可以消费已批准的多 study Paper Evidence，但必须使用不同 request kind 和新 Agent，不能让 per-study generation 互相污染。

## 10. Figure 政策

### 10.1 Source Figure

Source Figure 优先来自 Generic MinerU 图片层，但必须满足：

- 原始 PDF/current Source Truth binding；
- 明确 Figure/Fig./Scheme/Chart caption；
- 页码、图号、caption、publication identity 和 attribution 完整；
- fragment grouping 有明确同页 caption 关系；
- 不把 header、abstract、citation text 或附近正文冒充 caption；
- 不发明图号。

Chemical Paper ZIP 没有独立图片资产时不得伪造 Source Figure，只能记录 researcher-visible gap。

### 10.2 Synthesis Figure

系统永久只生成 `Synthesis Figure Placeholder` 和人工制图 brief，不生成、重绘或组合科学综合图。内部稿可以保留占位符；专家发布必须等待真实用户制作、上传和验收综合图。

## 11. Dashboard 需求

### 11.1 项目 Cockpit

显示三篇论文的：

- PDF verified；
- Generic Parse state；
- Chemical Paper import/completion state；
- fresh v3 `availability/status`、authoritative cohort readiness 和唯一 next action；
- formal import 后的 server-calculated denominator、三态 counts、coverage ratio、
  threshold、`coverage_sufficient` 与 gap registry；formal import 前这些值保持
  unknown/unavailable，不渲染为零；
- reconciliation state；
- Evidence availability；
- 项目当前阻塞和唯一 next action。

### 11.2 PDF 获取与验证

显示论文链接、DOI/标题、主文/SI、导入与身份核验。用户不处理 hash、manifest
或路径；ZIP/PDF binding、path/hash 和 importer receipt 只由 Coordinator 保留。

### 11.3 Dual Parse Review

同屏显示：

- 原始 PDF；
- Generic parsed preview；
- Chemical Paper 分子/化学版面安全投影；
- reconciliation items。

支持按正文、表格、图、公式、分子和风险过滤。

### 11.4 Chemical Completion Queue

显示 Honest Progressive 三态 molecule rows、缺失名称/标签、单一 `resolved_smiles`、
confidence/provenance、PDF/结构定位、reason、actor、stale protection 与 gap registry。
`smiles_expanded`/`smiles_unexpanded` 只作为候选来源，不能变成两套输入或门禁；
`BLOCKED` 行必须显示 `value=null` 与 `gap_reason`，不得用 0 替代 unknown/missing。

### 11.5 Evidence、Synthesis、Figure、Manuscript 与 Release

继续使用现有统一工作台，不增加第二个 Dashboard。所有决定显示具体 actor 和更新时间。Release 显示内部下载、benchmark 七维 rationale、Hard Fail、placeholder blocker 和 lineage currentness。

### 11.6 交互与响应式

- ZIP import 固定为“预检结果 → 确认导入”两步，由 Integration Owner 在
  Coordinator-only boundary 内完成；Dashboard/Researcher 只读取 safe projection；
- loading 必须对应真实任务状态、失败原因和可重试动作；
- 不得无限 loading 或用 disabled navigation 隐藏阻塞原因；
- 关键决定和 dialog 支持 Tab、Shift+Tab、Enter/Space、Escape、可见焦点和 focus return；
- `1440x1000` 与 `1024x900` 为强制验收；
- `390x844` 为观察性验收，但数据丢失、必需操作不可达或 dialog 无法关闭仍阻断。

正常 UI、DOM、可访问文本和安全 API 不得暴露：

- schema/version token/internal ID；
- PDF/ZIP/internal digest；
- 本地路径；
- raw JSON、完整 MolBlock 或 raw molecule ID；
- token、cookie、session 或私有 URL。

## 12. 失败与恢复

### 12.1 Generic Parse 失败

保留 PDF 和已完成任务，允许有限重试、其他解析器或人工 PDF locator。Core study 不得在 Generic Parse 不 current 时进入 Evidence。

### 12.2 Chemical ZIP 缺失或无效

Core study 保留 PDF + fresh Generic current，显示 `availability/status` 为
unknown/unavailable，唯一 next action 为 `待 Chemical Paper 导入` 或首份预检后的
`确认第一份 Chemical Paper 导入`；不生成零分母或伪造 gap registry。Background
study 不受全局阻塞。Generic ZIP、v2 Generic ZIP 和旧 Generic outputs 不能冒充
Chemical Paper ZIP。

### 12.3 SMILES 缺失

缺失值只按 Honest Progressive Route 的三态规则处理，不构成“309 个 SMILES 全完成才可
继续”的全局门。`smiles_expanded`/`smiles_unexpanded` 只是候选与 provenance；
有 PDF 支持并经研究者确认时为 `CONFIRMED`，有 locator/confidence/provenance
但未确认时为 `AI_PROVISIONAL`，无法确定时为 `BLOCKED` 且
`value=null` + `gap_reason`。低于 80% 继续 source/evidence preparation，明确
`needs_more_traceable_candidates`；禁止 AI 伪造科学批准。

### 12.4 双层冲突

只阻塞依赖对象。研究者使用原始 PDF 仲裁；未关闭冲突不得进入依赖 Evidence。

### 12.5 Reaction data 缺失

固定显示 `unavailable_not_provided`，不能解释为零反应。只阻塞依赖结构化 reaction data 的主张，不全局阻塞无关 Evidence。

### 12.6 安全失败

ZIP path traversal、absolute/backslash path、NUL、symlink、重复或大小写冲突、nested archive、escaping reference、可执行内容、source binding 模糊、stale write 均必须在权威写入前拒绝，结果为零写入。

### 12.7 进程与网络失败

所有动作短时、幂等、原子写回。Generic MinerU API、Dashboard、QoderWork 回合或机器退出后，下一次从持久状态和唯一 next action 恢复，不依赖 watcher 或长时间 shell 进程。

## 13. Credits

Credits 在本轮继续为：

```text
NOT_APPLICABLE_BY_CURRENT_SCOPE
```

UI 不显示 credits；后端未知值不伪造为零；credits 不阻塞内部稿。既有 audit data 不删除，但不进入本轮 QA 要求。

## 14. 新鲜项目与隔离合同

历史 v2 project ID（仅作为执行记录，不得复用输入）：

```text
vis-light-olefin-difunctionalization-complete-loop-regression-v2-dual-parse
```

Fresh v3 必须使用新的、非覆盖 project ID；v2 Generic ZIP、旧 Generic outputs
和旧项目的 Chemical/Evidence 状态都不属于 fresh v3 输入。

只允许复用：

- 三篇原始 PDF；
- 由这些 PDF 新鲜生成或正式绑定的 Generic MinerU 输入；
- 用户提供的三份原始 Chemical Paper ZIP；
- 标准评估 corpus 作为只读 benchmark。

禁止复制：

- regression-v1 的 Parse/Evidence/reconciliation 决定；
- Paper Evidence、Comparison、Coverage、Synthesis、Section Contracts；
- Source Figure selections、placeholders 或 molecule review 决定；
- Content Agent result；
- manuscript、DOCX、release、evaluation、credits；
- browser/session/storage；
- Reviewer conclusion。

Fresh bootstrap 必须通过正式主 CLI，不能依赖手工 JSON、复制旧 Source Truth 或删除旧产物伪装干净项目。

## 15. 三篇真实输入验收

验收分为两个不可混淆的阶段：

1. fresh v3 bootstrap 阶段只有 3/3 verified PDF 与 3/3 fresh Generic current，
   Chemical authoritative cohort 尚未存在；availability/status、denominator、
   三态 counts、coverage、coverage_sufficient 和 gap registry 必须保持
   unknown/unavailable，唯一 next action 为等待首份 Chemical import/confirm。
2. 三份 approved Chemical input 经正式 preflight/confirm/import 且 3/3 current
   后，才验证 pages `6/11/11`、molecules `125/109/75=309`、
   `reaction_data_status=unavailable_not_provided`。只有此时存在 authoritative
   molecule rows 才生成 gap registry，并由 server 计算三态 counts、
   `coverage_ratio=(confirmed+AI_provisional)/309`、threshold `0.8` 和
   `coverage_sufficient`；不得信任客户端计数。

两阶段都必须验证：

- `CONFIRMED` 有 PDF locator 与 researcher confirmation；
- `AI_PROVISIONAL` 有 PDF locator、confidence、provenance；
- `BLOCKED` 是 `value=null` 且有 `gap_reason`；
- Paper Evidence、科学批准和下游对象不会把 AI candidate 伪装成 confirmed；
- Source Figure 只来自真实 caption binding；无图像资产或 caption 歧义时保留 gap；
- safe projection 无敏感或内部字段；credits 只显示 `NOT_APPLICABLE_BY_CURRENT_SCOPE`。

## 16. 独立完整全流程 QA

### 16.1 开始条件

在启动 Reviewer 前必须提供：

- 唯一 frozen integrated revision；
- 全新 project ID；
- 同一 WSL Dashboard URL；
- fresh bootstrap audit；
- 三份 Chemical input 的 formal preflight/confirm/import receipt、3/3 current
  safe projection 与 runtime readiness；
- 两次真实 restart 的 Integration Owner 与 receipt channel；
- 然后才创建全新的浏览器 context 和 Simulated Researcher Agent。

### 16.2 执行角色

同一个独立 Playwright Researcher Agent 从头到尾保持浏览器研究者身份，完成
formal import 之后的产品内可见决定和 checkpoint 1–19。它不接收 ZIP/PDF
path/hash，不执行 importer；它的科学决定在本轮模拟流程中有效，但不等于真实
用户最终接受。

缺少候选内容时，Researcher Agent 发出 `CONTENT_AGENT_REQUEST` 并暂停。QA Coordinator 分派新的独立 Content Agent，验证并正式导入结果，然后让原 Researcher Agent 从原 checkpoint 继续。

### 16.3 Restart

Researcher Agent 在 checkpoint 10 和 15 分别返回：

- `READY_FOR_RESTART_1`；
- `READY_FOR_RESTART_2`。

只有 Integration Owner 可以执行真实 server restart。Repair restart、服务意外退出和普通 refresh 均不计协议 restart。每次 receipt 必须记录 old/new PID、revision、project、start/readiness local+UTC 和 HTTP health。

### 16.4 禁止边跑边修后宣称 PASS

若独立 run 发现 release-blocking product finding：

1. Reviewer 停止在规定 checkpoint；
2. finding 路由原 Owner；
3. Owner 用失败测试和最小修复形成独立 commit；
4. Integration Owner 集成并运行门禁；
5. 当前 run 只作为 finding evidence；
6. 最终 PASS 必须来自新的、从头开始的独立完整 run。

## 17. 内部稿验收标准

最终 `SELF_REVIEWED_DRAFT` 必须同时满足：

1. 三篇 Paper Evidence 均经 Simulated Researcher Agent 审查；
2. Comparison Protocol 覆盖比较对象、轴、单位/归一化、缺失值、不可比条件、反例和结论强度；
3. Coverage 和 Synthesis 显示冲突、反证、边界、局限和不确定性；
4. 所有 Section Contracts 可审查；
5. 有 5–8 个有科学任务和理由的 figure slots；
6. 每篇至少设置一个 Source Figure slot；有来源支持时至少选择一个可追溯 Source Figure，经 PDF 确认无可用图时显示真实 gap，不能伪造；
7. Synthesis Figure 只保留高质量人工制图 placeholder；
8. 至少完成一次高风险正文直接编辑及逐节批准；
9. 内部 DOCX/PDF 可下载，且不是旧稿重新打包；
10. benchmark 总分至少 80/100，七维均有 rationale；
11. 无适用于内部稿的 Hard Fail；
12. placeholder 正确阻塞 expert release，但不阻塞 internal draft；
13. refresh 和两次真实 restart 后决定、actor、计数、next action、稿件和 release 状态一致；
14. console 零 warning/error，计划请求没有异常 4xx/5xx、重复 mutation 或无界 retry；
15. `1440x1000` 与 `1024x900` 完整通过，mobile 观察项无阻断缺陷；
16. Git、安全、smoke、quality、Task 14 和最终完整回归通过。

## 18. Hard Fail

除既有 Hard Fail 外，新增或明确以下拒绝条件：

1. Core study 缺 Generic current parse 或未完成 formal Chemical current import，
   却生成 exact authoritative Evidence/Release；safe source/evidence preparation
   必须保持 provisional/blocked 与显式不确定性；
2. authoritative molecule row 的三态合同失效：`CONFIRMED` 无 researcher
   confirmation/PDF locator、`AI_PROVISIONAL` 缺 PDF locator/confidence/provenance，
   或 `BLOCKED` 不是 `value=null` + `gap_reason`；
3. AI candidate 被静默升级为 `CONFIRMED`，或低于 80% 时伪造科学批准；
4. Generic/Chemical 冲突未经 PDF 仲裁却被下游消费；
5. 两条 lane 绑定到不同 PDF 或 study；
6. stale parse、stale Chemical state、旧 result 或跨 study Evidence 进入 package；
7. Reaction data 缺失被表述为零反应；
8. Chemical ZIP 无图片时伪造 Source Figure；
9. Simulated Researcher Agent 通过内部 API、文件或脚本绕过可见 UI；
10. 同一有 finding 的 run 经修补后直接被宣称为最终 PASS。

## 19. 测试策略

### 19.1 确定性单元测试

- 双层 PDF/study binding；
- Generic 和 Chemical currentness；
- molecule source order；
- name/local label、三态 value contract 与 SMILES traceability；
- append-only correction/history；
- reconciliation state transition；
- object-level invalidation；
- safe projection；
- release dependency gating。
- 四份 fresh v3 文档的 Honest Progressive contract 完整性与逐字一致性。

### 19.2 集成负例

- 错 PDF；
- Generic ZIP 冒充 Chemical；
- 不安全 ZIP；
- duplicate/case conflict/nested archive；
- stale correction/import；
- Generic/Chemical 冲突自动覆盖；
- 跨 study Content package；
- 旧 Content Agent result reuse；
- service kill/restart/resume；
- invalid write 保持零权威写入。

### 19.3 真实三篇回归

使用三篇固定 PDF、fresh Generic MinerU 和三份 approved Chemical Paper ZIP，
先验证 fresh v3 初始 unknown/unavailable 与唯一 next action，再经正式
preflight/confirm/import 验证 pages `6/11/11`、`125/109/75=309`、
`reaction_data_status=unavailable_not_provided`、三态计数、server-calculated
coverage、traceable gaps、figure gaps 和新鲜隔离；不得把旧 SMILES completion
门当作继续条件。

### 19.4 最终门禁

- 双层解析与 Chemical focused tests；
- Source Truth/Parse/Paper Evidence/Synthesis/Figure/Manuscript tests；
- Task 14 quick gate；
- Dashboard/release gate；
- Task 10 DOCX/release gate；
- Dashboard JavaScript syntax；
- `make smoke`；
- `make quality-check`；
- 最终完整回归仅在新的独立 Round 完成后运行一次；
- Git diff/show/status/safety scan。

测试计数以新计划执行时的新鲜输出为准，不沿用历史通过数。

## 20. 迁移边界

### 20.1 保留

- frozen candidate `9213018…` 的已验证实现和修复 ancestry；
- 现有 Chemical Paper importer、safe projection、correction/history 和 release binding；
- 现有 Source Truth、Parse Quality、Evidence/Synthesis、Figure、Manuscript、Release、benchmark 与 Dashboard。

### 20.2 调整

- 新增正式 dual-parse bootstrap；
- Source Truth 升级为双层 binding/currentness；
- 新增 formal Chemical import、Honest Progressive Completion projection 与
  Reconciliation Registry；
- Content Agent package 从 Chemical-only 调整为当前双层安全输入；
- QA protocol 增加 Chemical Completion、双层 reconciliation 和 Agent 模拟全部人工操作。

### 20.3 删除或永久禁止

- Chemical-only 作为唯一科学内容输入；
- Generic/Chemical 自动覆盖；
- 复制旧项目 Source Truth/决定/下游产物作为 fresh bootstrap；
- AI 自动补 SMILES；
- 长时间 watcher 和无界重试；
- 自动科学综合图。

## 21. 实施拆分建议

本设计应拆成一个新的实施计划，并按以下顺序执行：

1. 冻结审计与 dual-parse bootstrap；
2. Dual-source binding、Chemical Completion 和 Reconciliation contracts；
3. Content Agent 双层安全 package 与局部失效；
4. Dashboard Dual Parse/Chemical Completion/Reconciliation UI；
5. Release/benchmark/Hard Fail 双层 currentness；
6. Task 10 fresh v3 bootstrap、formal import、safe projection 与 runtime readiness；
7. Task 11 在上述 readiness 后创建全新 Playwright Researcher Agent + Content Agents；
8. 最终 artifact、DOCX、benchmark、restart 和 Git 验收。

每个实现任务采用失败测试、最小实现、聚焦验证和独立 commit。不得在计划中重新实现已闭合 finding，也不得修改旧计划 checkbox。

## 22. 完成定义

本设计完成必须同时满足：

1. Generic MinerU 与 Chemical Paper 双层路线在真实项目中可用；
2. Core/background 强制范围符合本设计；
3. fresh v3 初始 unknown/unavailable 不被压成零；正式导入后 authoritative
   molecule rows 满足三态合同，`coverage=(confirmed+AI_provisional)/309`，
   threshold `0.8` 与 `coverage_sufficient` 由 server 计算；
4. 双层冲突由 PDF 仲裁并局部失效；
5. 独立 Agent 完成全部产品内人工操作；
6. 三篇全流程从 fresh project 完整跑通；
7. 内部 DOCX/PDF、benchmark、Hard Fail、两次 restart 和三视口证据完整；
8. 最终结果明确为 `SELF_REVIEWED_DRAFT`；
9. 不宣称投稿级、专家发布、真实用户接受或科学完美。
