# Review Writer 产品设计

> 文档状态：`CANONICAL / TARGET DESIGN / NOT_READY`
> 版本：`0.1`
> 日期：`2026-08-20`
> 产品方向：高风险化学综述的证据审计与决策工作台

本设计与 [`REVIEW_WRITER_SRS.md`](./REVIEW_WRITER_SRS.md) 成对使用。SRS 冻结用户合
同、需求 ID、验收边界和非目标；本文件冻结 authority、数据流、写入规则、模块边界、
兼容迁移和实现顺序。文中的 `TARGET` 是设计目标，不是当前实现证明；当前仓库仍为
`NOT_READY`。

## 1. 设计结论与边界

### 1.1 一条 canonical 链路

普通用户只给 Agent：

```text
自然语言 topic/RQ + absolute blank/resume project root + authorized PDF folder
    -> Agent public orchestrator
    -> source-set / parse / Source Truth / Evidence / Matrix / GAP
    -> batch Decision Bundle（必要时 HUMAN_ACTION_REQUIRED）
    -> multi-study synthesis / figures / manuscript
    -> same-version Markdown + DOCX release
    -> stale / regenerate / history / branch / undo / cold resume
```

用户不运行 CLI、cURL、pytest、内部脚本、`generator-start` 或
`generator-continue`。Agent 可以内部调用现有 producer，但只能返回稳定的阶段、下一
步、Dashboard URL 和可理解的阻断原因。

### 1.2 当前与目标必须分开

| 维度 | `CURRENT`：已观察起点 | `TARGET`：本设计冻结的合同 |
| --- | --- | --- |
| fresh bootstrap | public package 只接受 `1–3` 个 PDF、选排序后的第一个 PDF，并在 MAIN/SI 身份决策处暂停 | 读取授权目录中的实际 source set，`N` 可变；身份、解析和证据按 study 批处理 |
| synthesis | `build_pdf_only_synthesis_plan` 强制 single-study case report | adapter 以 per-study Evidence/Matrix/GAP 做 multi-study synthesis，保留不可比较项 |
| variable-N | 旧 variable-N `20–40` CLI/manifest 能力存在，但未接入 public Agent route | `N` 不是固定 `1–3` 或 `20–40`；首轮验证点是 `N=1/3/10/20`，不是产品上限 |
| authority | 已有 product foundation、VersionContext、Dashboard 和多个底层 producer，入口与状态布局仍分散 | 每个 review 的 explicit project root 是唯一 durable authority；只有一个 current/history/branch 体系 |
| 质量 | 主仓库已有大量底层模块和 tests；最近 `tests/product_use` 结果为 `72 passed / 6 failed / 1 skipped`，失败集中 Dashboard context | 只有新鲜、用户可见、分层的证据才可推进；任何缺少 producer、persistence、public caller 或依赖证明的点停在 `HOLD` |

CURRENT 描述的是迁移起点，不是兼容承诺；TARGET 描述的是本设计要实现的公共行为。
任何实现或测试报告必须同时带上 `CURRENT/TARGET` 标签，不能把一条旧 CLI、一个 bounded
synthetic 结果或一次 Engineering PASS 推广为产品 Ready、HUMAN_ACCEPTANCE、scientific
validity 或 PROMOTE。

## 2. Canonical authority 与持久化布局

### 2.1 authority 规则

1. 每个 review 的 `explicit_project_root` 是唯一 durable authority。新项目只能从用户给
   定的绝对空目录创建；resume 必须回到同一绝对目录。
2. project root、authority 组件和 authorized PDF folder 均做 realpath、symlink/reparse
   escape 和普通文件检查。目录外、重复字节跨 study、未授权网络获取和 secret 写入一律
   拒绝。
3. Dashboard、Agent session、缓存、临时端口和进程内对象都是 projection/runtime，不是
   事实源；不得创建 parallel session store、第二 current、第二 history 或隐藏 marker
   层。
4. 事实对象带 stable ID、输入 binding、producer、schema/contract、时间和 SHA-256 digest。
   读取时验证 digest 和依赖 currentness；不能从 basename、mtime 或旧矩阵猜测等价。
5. `current` 与 `inspected` 分离。History/compare 只读；明确的 `Branch from here` 才创
   建新的可写 candidate；undo 通过新节点表达，不覆盖旧节点。

### 2.2 TARGET 逻辑布局

以下是 canonical 相对路径；未迁移的历史路径由只读/适配层读取，不能形成第二权威。

```text
<explicit_project_root>/
├── .paper_evidence.lock
├── .review-writer/
│   └── version_context/
│       ├── current.json                 # 唯一 pointer；pointer-last
│       ├── versions/<version_id>.json   # immutable version nodes
│       └── branches/<branch_id>.json   # branch heads
├── 00_brief/review_state.json           # topic/RQ/scope/entry provenance
├── 00_sources/                           # authorized source-set descriptors/assets
│   └── manual_upload/inbox/source_bundle.zip
├── 01_evidence/                          # Evidence, parse quality, decision projection
├── 02_claims/                             # Matrix, synthesis claims, coverage, GAP links
├── 03_review/                             # review questions and risk decisions
├── 04_manuscript/                         # v1/v2, section contracts, figure bindings
└── 05_release/                            # same-version Markdown, DOCX, snapshot, report
```

`source_bundle.zip` 只是获授权输入的项目内快照，不是用户需要理解的 protocol。每个
source descriptor 仍须保留原始 PDF hash、study/source ID、MAIN/SI role、页数、文件名、
授权边界和 archive binding。目标布局具体落地时必须复用项目已有 schema 和 writer，
不能仅凭目录名称新造存储协议。

### 2.3 pointer-last 写入序列

所有 Agent、Dashboard、producer 的 durable 写入都经过同一个 project writer/lock：

```text
read current + expected revision/head
    -> validate root, lock, input identities, dependency digests, write set
    -> lock project
    -> write immutable candidate artifacts to temporary paths
    -> fsync/rename candidate artifacts; validate schemas and all bindings
    -> write immutable version node and branch head candidate
    -> atomically replace .review-writer/version_context/current.json  # last
    -> unlock and return new current/version/revision
```

任一 preflight、schema、digest、lock 或 commit 步骤失败，current pointer 不移动，旧
current 和 release 字节不变；临时文件清理可重试。expected revision/head 不匹配返回
`VERSION_CONFLICT`，zero-write。重复的相同 `Decision Bundle` revision/digest 必须幂等，
不是再造节点。

## 3. 数据模型与数据流

### 3.1 规范化对象

```text
ReviewBrief(topic, rq_candidates, scope, venue, project_id, input_boundary)
SourceSet(SourceIdentity[], N, expansion_revision)
SourceIdentity(study_id, source_id, role, pdf_sha256, page_count, MAIN/SI binding)
ParseRecord(backend, version, contract, input_sha256, output_digest, attempts, fallback)
SourceTruth(locator[], parse_digest, source_sha256, role, quality_state)
Evidence(statement, epistemic_type, conditions, locator[], study_id, status, dependencies)
Matrix(rq_id, study_id, evidence_ids[], comparability, digest)
Gap(kind, reason, affected_ids[], minimum_next_action, blocking_level)
DecisionBundle(bundle_id, revision, items[], impact_preview, expected_write_set)
Synthesis(ComparisonProtocol, Coverage, SynthesisClaim[], SectionContract[])
FigureCandidate(source_binding, page, label, bbox, asset_sha256, rights, manuscript_binding)
Manuscript(version, sections, user_edits, figure_bindings, source_digest)
Release(version, markdown_sha256, docx_sha256, snapshot, quality_report, currentness)
```

`candidate`、`confirmed`、`blocked`、`stale` 是状态，不是可信度分数。尤其
`AI_PROVISIONAL` 只能作为需要人确认的候选；它不能投影为 `CONFIRMED`，不能绕过
`HUMAN_ACTION_REQUIRED`，也不能进入可发布 release。

### 3.2 端到端数据流

1. **Intake**：Agent 校验非空自然语言 topic、绝对 project root 和明确授权 PDF folder，
   记录原文、输入 boundary 和 resume/fresh intent；缺口在任何写入前返回。
2. **Source-set**：枚举授权目录内全部合法 PDF，按内容 hash 建立 study/source identity，
   保留 MAIN/SI 候选及冲突；不再选第一个 PDF。source set 的实际计数是 `N`。
3. **Parse**：对未命中相同 `(pdf_sha256, backend, version, contract)` 的 source 调度
   MinerU；解析失败或 contract 不合格时，在允许的本地 fallback 中显式重试并记录原因、
   能力缺口、attempt 和 digest。没有真实 fallback 时 `HOLD`，不伪造成功。
4. **Source Truth / quality**：从 PDF 和 parse object 建立页码、章节、表/图/caption、
   段落和化学符号 locator；parse quality/reconciliation 将异常聚合为 bundle item。
5. **Evidence / Matrix / GAP**：每条 evidence 保留 source/hash/locator、条件、限制和
   epistemic status；Matrix 绑定稳定 RQ 和 comparison protocol；任何缺失、冲突、不可比
   或未确认化学字段都生成 GAP，不用空值补齐结论。
6. **Decision gate**：Agent 为当前 source set 生成一个或少量有边界的 batch Decision
   Bundle；研究者通过 Dashboard 确认/修订/驳回/保持 GAP/要求重解析。Bundle 结果经同一
   writer 写入 immutable decision events 和 candidate projection。
7. **Synthesis**：adapter 只消费 per-study canonical objects，产出 Comparison Protocol、
   Coverage、Synthesis Claim、Section Contract 和带 locator 的章节 candidate。
8. **Figures**：figure producer 从真实授权 PDF/解析资产登记候选并生成 rights/binding
   检查；候选可停留内部 GAP，不能用 placeholder 伪装 source figure。
9. **Manuscript / Release**：从当前 evidence/synthesis 生成 v1；用户编辑由同一 writer
   保存为 `USER_EDITED`/`RESEARCHER_AUTHORED` v2 增量；Markdown 和 DOCX 从同一 manuscript
   version 生成，snapshot、asset、citation、rights binding 全部校验后才成为 release。
10. **Invalidation / resume**：任何 source、parse contract、decision、evidence、matrix、
    figure、正文或权限 binding 变化都精确标 stale。冷启动从 project root 重载
    VersionContext 和未完成 bundle，不依赖进程内 session。

### 3.3 增量与 N-agnostic 规则

- `N` 由当前 SourceSet 计数决定，不作为配置档位；`N=1/3/10/20` 是验证矩阵点。
- source-set expansion 只为新增/变化 source 建立 candidate；未变化 source 的 parse、
  Source Truth、Evidence digest 必须保留。受影响的 Matrix/GAP/Synthesis/Figure/Manuscript/
  Release 精确 stale。
- PDF bytes、parser backend/version/contract 或身份 binding 任一变化即视为新输入；不按
  文件名、mtime 或位置复用。
- 减少 source 时保留历史版本，并从新 candidate 的 dependency graph 移除受影响对象；不
  删除历史、不回写旧 current。

## 4. 状态机与阻断语义

```text
EMPTY
  -> INTAKE_VALIDATED
  -> SOURCE_SET_READY
  -> PARSE_CANDIDATE
  -> SOURCE_TRUTH_REVIEW
  -> EVIDENCE_REVIEW
  -> SYNTHESIS_CANDIDATE
  -> FIGURE_REVIEW
  -> MANUSCRIPT_CANDIDATE
  -> RELEASE_CANDIDATE
  -> RELEASED
```

任一阶段可进入以下受控状态：

```text
HUMAN_ACTION_REQUIRED --(researcher decision via writer)--> next candidate state
HOLD                  --(minimum repair + fresh preflight)--> retrying candidate
STALE                 --(regenerate from current dependencies)--> candidate state
VERSION_CONFLICT      --(reload current; discard stale write)--> HUMAN_ACTION_REQUIRED/HOLD
ERROR                 --(diagnosed retry; no implicit continuation)--> HOLD
```

状态含义必须可由项目 artifact 重建。Dashboard 的 loading、进程退出、ready text 或
Agent 自述不构成状态迁移。`RELEASED` 只表示同版本 release contract 通过；不表示
HUMAN_ACCEPTANCE、scientific validity、PROMOTE 或 B2。

## 5. Public Agent orchestrator

### 5.1 Public contract

目标入口可以是宿主提供的 Agent/Skill 调用，但外部语义固定为：

```text
start_or_resume_review(
    topic: str,
    explicit_project_root: absolute path,
    authorized_pdf_folder: absolute path,
    review_questions?: list[str],
    scope?: object,
    venue?: str,
    output_formats?: ["markdown", "docx"]
) -> {
    project_id, stage, status, current_version, revision,
    dashboard_url?, next_action, gaps[], write_mode
}
```

内部 tool/protocol、claim schema、contract ID、MinerU 参数和路径不出现在普通用户的
下一步中；只有诊断所需的稳定 category code 和最小修复动作可见。任何需要人判断的情况
返回 `HUMAN_ACTION_REQUIRED`，并附上对应 Decision Bundle URL/ID。

### 5.2 Fresh 与 resume

- fresh：确认 root 为空、父目录可写、授权目录真实存在且只读边界合法；先在临时候选构
  建 identity/parse plan，再按 pointer-last 创建项目 authority。任何 preflight 失败都不
  创建半项目。
- resume：只从同一 root 读取 `current.json`、version nodes、branch head、source/decision
  bindings 和用户编辑；验证 project ID、digest、lock 和 currentness。不可重建或损坏时
  `HOLD`，不能从 Dashboard memory、legacy JSON 或默认第一个文件猜 current。
- public orchestrator 负责调用 acquisition、parse、evidence、synthesis、figure、draft、
  release producer；每一步返回 producer/persistence/caller binding，缺一项即停在第一处
  `HOLD`。

### 5.3 当前限制的最小修复方向

第一公共 blocker 是入口与 source-set/synthesis contract 不一致：

1. 保留现有 fresh bootstrap 的安全 root/archive/lock/VersionContext preflight；
2. 将 `1–3` 和“选择第一个 PDF”替换为授权目录全量 identity + source-set candidate；
3. 将 `build_pdf_only_synthesis_plan` 的 single-study case-report 输出包在 multi-study
   adapter 后面；
4. 将旧 variable-N CLI/manifest producer 作为内部适配器接入 Agent，不将 CLI 暴露给用户；
5. 每步以真实 public route 重测，首个失败未关闭时保持 `HOLD`，不新建 packet/marker/receipt
   层。

## 6. Batch Decision Bundle

### 6.1 对研究者的可见模型

Bundle 是“一个人类阅读回合”的聚合视图，不暴露内部 claim/contract/protocol 图。它显示：

- source identity、MAIN/SI 候选、PDF hash、页数、页内 locator 和 parse provenance；
- 候选文本/结构、原始 PDF 对照、冲突、质量风险和权限风险；
- 受影响的 Evidence、Matrix、GAP、synthesis section、figure 和 release preview；
- 每个 item 的 `confirm`、`revise`、`reject`、`keep GAP`、`reparse` 动作及理由；
- 当前 revision/head、预计写集、旧 bundle 是否过期以及并发提示。

内部实现可以含多种 event/claim/contract，但用户只处理稳定的 item 和影响关系。一次
bundle 不能跨越未授权 source、不同 project root 或不相容 revision。

### 6.2 写入合同

提交前校验：`project_id`、bundle ID、expected revision/head、source/parse/evidence digests、
actor、合法 action、reason（需要时）和精确 write set。提交通过同一个 writer：

```text
bundle read -> preview write set -> lock -> validate all items
-> write decision events + candidate projection -> validate dependencies
-> append version node -> pointer-last current update
```

部分 item 失败时整个 bundle zero-write；相同 bundle/digest 重复提交幂等；旧 revision 返回
`VERSION_CONFLICT`。旧 current、旧 release 和人类编辑永不被覆盖。

## 7. Multi-study synthesis adapter

adapter 的输入只能是 per-study Source Truth/Evidence/Matrix/GAP canonical projection，不能
直接把 legacy matrix、UI 表格或模型草稿当作事实源。内部接口的逻辑形状为：

```text
SynthesisAdapter.project(
    current_source_set,
    per_study_evidence,
    per_study_matrix,
    gap_registry,
    review_questions,
    expected_revision
) -> ComparisonProtocol + Coverage + SynthesisClaims + SectionContracts + gaps
```

规则：

- 每个 study 保留 `study_id/source_id` 边界、输入 digest、条件、单位、样本和 limitations；
- 先建立 Comparison Protocol，再判断可比较性；条件不一致输出 `NOT_COMPARABLE` 或 GAP，
  不用缺失值、平均值或模型猜测填充；
- claim 必须反向指向 evidence/matrix/source locator，冲突作为显式 competing claim；
- N 增长、减少或替换时只重算受影响的 projection；不变 study 的 digest 不变；
- synthesis candidate 不能移动 current，也不能使 `AI_PROVISIONAL` 自动成为 confirmed。

## 8. Figure producer 与 manuscript binding

### 8.1 真实 PDF source figure

figure producer 从授权 PDF 或其 parse asset 提取候选；每个候选至少记录：

```text
candidate_id
source_pdf_sha256 / study_id / source_id / role
page / figure_label / caption / bbox_or_fragments / asset_sha256
extractor_backend + version + input/output digest
attribution / license_or_rights_evidence / rights_status
selection_status / manuscript_section / marker / occurrence
bound_manuscript_sha256 / bound_version_id
```

真实 source figure、重绘 figure、placeholder 和 AI suggestion 是不同类型。没有实际 PDF
来源、asset hash、页码/locator 或 rights evidence 的对象只能是 internal candidate/GAP；
不能放进 release。未知许可可以保留以供研究者处理，但 release 必须阻断或明确受限。

### 8.2 stale 传播

source PDF、extractor contract、asset bytes、caption/attribution、manuscript marker 或
section version 任一变化都会使 figure binding stale；release validator 必须拒绝旧 binding。
正文与图件由同一 manuscript version 生成，任何用户编辑都经 writer 产生新节点。

## 9. Simplified 五组 Dashboard IA

目标 UI 严格只保留以下五组顶级心智模型；内部阶段和 legacy URL 可继续映射，但不新增
平行 writer。Decision Bundle 归入“来源与证据”，图表单列；顶级导航不得把决策或正文与
图表拆成额外顶级页签。

| 顶级组 | 研究者看到的内容 | 允许的 durable action |
| --- | --- | --- |
| **首页** | topic/RQ、N、阶段、current/revision、下一步、GAP 摘要、Dashboard URL 状态 | fresh/resume、添加授权 source、打开待处理 bundle；不直接改 projection |
| **来源与证据** | source identity、MAIN/SI、Corpus、parse provenance、Source Truth、Evidence、Matrix、GAP、PDF locator，以及 batch Decision Bundle 的候选/冲突/影响预览/写集 | 只读检查、请求重解析、确认/修订/驳回/保持 GAP/reparse；所有动作走 canonical writer |
| **正文** | 写作大纲、Sections、synthesis section candidate、manuscript v1/v2、用户编辑和 citation/locator 状态 | 保存用户编辑、生成正文 candidate；不直接发布、不覆盖 `USER_EDITED` |
| **图表** | 真实 PDF figure/table candidate、extract/hash/page/locator、attribution、license/rights、manuscript binding 和 stale 状态 | 选择/拒绝 figure、补充 attribution/license、生成图表 candidate；不直接发布 |
| **发布与历史** | Quality、Release、Markdown/DOCX snapshot、current/inspected、compare、branch、undo、stale/regenerate 和下载状态 | 只读 history、显式 branch/undo、regenerate current candidate、下载同版本产物 |

旧 `WorkspaceModel` 的 Overview/Research/Draft/Figures/Review/History/Release 七层可作为
兼容 projection 和测试入口；它们不得各自拥有 current、写锁或存储协议。旧写 API 必须转
canonical writer 或返回稳定 `405/NOT_SUPPORTED`，旧 GET 可只读兼容并规范化到 project ID。

## 10. 失败处理、兼容与安全

| 失败场景 | 用户可见结果 | 写入规则 |
| --- | --- | --- |
| topic/root/folder 缺失或非绝对 | `INPUT_INVALID` + 最小补充项 | zero-write |
| root 非空（fresh）、symlink/reparse escape、目录越界 | `PROJECT_ROOT_INVALID` / `AUTHORIZED_PATH_INVALID` | zero-write |
| 非 PDF、损坏 PDF、重复 hash、错 role、MAIN/SI mismatch | `SOURCE_INVALID` / `DUPLICATE_SOURCE` / `ROLE_CONFLICT` | current/release zero-write；可留隔离 diagnostic candidate |
| PDF/hash 在 parse 前后变化 | `AUTHORIZED_PDF_STALE` / `SOURCE_HASH_CONFLICT` | zero-write，重新 intake |
| MinerU timeout/contract invalid，fallback 可用 | `FALLBACK_USED` + backend/version/reason/capability gap | 只写 provenance-bound candidate，不冒充 MinerU |
| MinerU 与真实 fallback 都失败 | `PARSE_HOLD` / `HUMAN_ACTION_REQUIRED` | current/release zero-write |
| 缺 locator、化学字段未确认、跨 study 不可比 | `GAP` / `AI_PROVISIONAL` / `NOT_COMPARABLE` | 不进入 confirmed claim/release |
| bundle 过期、expected revision/head 不匹配 | `VERSION_CONFLICT`（409-class） | zero-write |
| figure rights/attribution/binding 缺失 | `FIGURE_RIGHTS_GAP` / `FIGURE_STALE` | internal candidate 可留；release 阻断 |
| release 输入变化 | `STALE` + regenerate action | 旧 release 保留且不可伪装 current |
| legacy path 读请求 | 兼容 projection，显示 canonical project/version | 只读；写请求转 writer 或 405 |
| process crash/冷恢复无法验证 current | `HOLD` | 不从 memory/旧文件猜测或覆盖 |

错误响应不得回显 token、cookie、auth、完整敏感日志或不必要的私人路径；稳定 category code
可以用于测试和最小修复提示。400/409-class 只是接口错误分类，不是允许部分写入的理由。

## 11. 模块复用矩阵

分类只表示实现策略，不表示对应模块已经满足 TARGET；每一项仍需 producer、persistence、
public caller 和独立验证证据。

| 模块/能力 | 分类 | TARGET 角色与适配边界 |
| --- | --- | --- |
| `product_foundation` | **直接复用** | 作为 project root、VersionContext、current/inspected、branch/undo/history、lock/pointer-last 的 kernel；不得建立第二上下文。 |
| `acquisition` | **需适配** | 复用授权路径与来源清点能力；改为全量 source-set、任意合法 N、source expansion，并保留 zero-write preflight。 |
| `input_provenance` | **直接复用** | 复用输入 hash、文件身份、授权边界和 provenance 记录；补齐 study/source/MAIN/SI 绑定到 public bundle。 |
| `dual_parse_bootstrap` | **需适配** | 保留 Generic/Chemical/MAIN/SI 关系和 bootstrap 安全门；接入 MinerU default、真实 fallback、attempt/digest 及任意 N 调度。 |
| `source_truth` | **直接复用** | 作为 PDF/hash/parse object/page/locator 的唯一事实边界；UI 和 legacy matrix 不得越权。 |
| `parse_quality/reconciliation` | **需适配** | 复用质量检查和冲突检测；将异常聚合到 Decision Bundle，并按 source 增量重算。 |
| `paper_evidence` | **直接复用** | 作为 Evidence/GAP/decision persistence 与 project lock 的 producer；公共动作必须经 canonical writer。 |
| `synthesis package/project synthesis` | **需适配** | 保留 Comparison Protocol/Coverage/Claim primitive；由 adapter 消费 per-study canonical objects，解除 single-study 强制。 |
| `section_contract` | **直接复用** | 作为 synthesis 到 manuscript section 的绑定 contract；补充 N 变化、GAP 和 source locator 依赖。 |
| `batch_runner` | **需适配** | 内部调度 parse/evidence/synthesis/figure 的 batch；不得暴露 CLI，不得批量绕过人工 gate 或 pointer-last。 |
| `review_figures/figure_policy` | **需适配** | 复用 figure registry、policy、attribution/license 检查；接入真实 PDF extract/hash/page/locator/manifest-to-manuscript binding。 |
| `manuscript_v2/draft/generator_runtime` | **需适配** | 复用 v1/v2、用户编辑保留、Agent session 事件；session 状态必须落入同一 VersionContext，不能覆盖 USER_EDITED。 |
| `project_release/docx_integrity` | **直接复用** | 复用 release validator、Markdown/DOCX integrity、snapshot/quality report；绑定 canonical manuscript/version 和 figure rights。 |
| `dashboard` | **需适配** | 将现有多 workspace/route projection 收敛为“首页/来源与证据/正文/图表/发布与历史”五组 IA；所有写入转同一 writer，修复 context/public URL seam。 |
| 旧 `20–40` CLI/manifest route | **仅参考** | 可作为内部 producer/fixture 的来源；不作为公共 N 合同、入口或默认上限。 |
| 旧 single-study case-report route | **仅参考** | 可适配为 N=1 fixture；不作为 multi-study authority 或 synthesis 公共输出。 |
| 第二 session store、独立 packet/marker/receipt 层 | **不适用** | 违反 per-review root sole authority；不创建。 |
| 自动科学批准、远程 RAG/Provider、未授权下载 | **不适用** | 超出本版本范围和 source/authority 安全边界。 |

## 12. 测试与验收矩阵

测试必须区分 Engineering、Independent Quality、Product Use、`PUBLIC_E2E`、
`HUMAN_ACCEPTANCE`、scientific validity 和 promotion；前一层不代替后一层。

| 轨道 | 最小场景 | 必须观察 | 不能宣称 |
| --- | --- | --- | --- |
| N contract | N=1/3/10/20 合法 source set | 同一 schema/route；实际 N；资源、失败恢复、未变化 digest 统计 | N 上限、科学有效 |
| expansion/reparse | 新增、替换、parser contract 变化 | 只重算受影响 source；精确 stale；旧 current 不动 | 全量任意 PDF 已覆盖 |
| fallback | MinerU timeout/invalid 与本地 fallback 可用/不可用 | provenance 完整；不可用时 HOLD/zero-write | 静默成功 |
| identity | duplicate/wrong role/MAIN-SI mismatch/stale | 400/409-class fail-closed；项目字节不变 | 业务批准 |
| bundle | 首次、重复、旧 revision、并发提交 | 一次写入/幂等；冲突 zero-write；影响 preview 与写集可见 | Agent 自动批准 |
| synthesis | 条件冲突、不可比较、N 变化 | `NOT_COMPARABLE`/GAP、study 边界和 locator 保留 | 科学结论正确 |
| figures | 真实 source figure、无 rights、marker 变化 | candidate/extract/hash/page/locator/attribution/license/binding；stale 阻断 release | placeholder 可发布 |
| manuscript/release | v1 -> USER_EDITED v2 -> Markdown/DOCX | 用户内容保留；两种格式同 version/hash/lineage；变更触发 stale | 投稿资格 |
| history/resume | compare/branch/undo/冷恢复/进程退出 | inspected 不移动 current；branch 明确可写；同 root 恢复 | 内存 session 可靠 |
| Dashboard/public | 新鲜浏览器、真实 Agent 请求、五组 IA（首页/来源与证据/正文/图表/发布与历史）、legacy GET | 真实 URL/DOM/console/下一步；Decision Bundle 在来源与证据、图表单列；不要求 CLI/cURL | HUMAN_ACCEPTANCE（除非研究者实际确认） |

每个失败测试记录输入 N、explicit root、source hashes、代码/项目 revision、write set 前后
摘要、首次 blocker 和剩余风险。任何“全套通过”仍不能越过科学与人类验收边界。

## 13. 分阶段实施计划

### Phase 0 — Contract freeze and fixtures

冻结 SRS/Design、canonical path、稳定错误码、Decision Bundle schema、五组 IA mapping
（首页/来源与证据/正文/图表/发布与历史）和 N=1/3/10/20 fixture；只读确认现有 producer 的输入/输出/persistence/public caller。若
发现路径、写集或 authority 不可证明，停在 `HOLD`，不改代码。

### Phase 1 — Public intake 与唯一 authority

复用 `product_foundation` 和 fresh/resume 安全门，接通一个 Agent-first public orchestrator。
先修第一真实 blocker：自然语言 + explicit root + authorized folder 真实进入同一
VersionContext/Dashboard；保持 old route 只读兼容。验证 malformed/path/empty-root/zero-write
和 native public entry。

### Phase 2 — N-agnostic source set 与 parse provenance

接入全量 source identity、source-set expansion、incremental reparse、MinerU default 和
真实 fallback。以 N=1/3/10/20 逐点验证，测量资源和未变化 digest；旧 1–3/首 PDF 和 20–40
只留 adapter/fixture 语义。

### Phase 3 — Decision Bundle 与 multi-study synthesis

将 parse quality/reconciliation、paper evidence、matrix/GAP 聚合为 batch Bundle；接入
synthesis adapter、Comparison Protocol、Coverage、Claim、Section Contract。先证明身份、
版本冲突、幂等和 zero-write，再测跨 study 不可比较和 N 变化。

### Phase 4 — Figures、manuscript、same-version release

接通真实 PDF figure candidate/rights/binding、manuscript v1/v2、用户编辑保护、Markdown/DOCX
一致性、stale/regenerate。任何 unknown rights 或 binding drift 都保持 HOLD/GAP。

### Phase 5 — 五组 Dashboard IA 与冷恢复

把现有 Dashboard projection 收敛到“首页/来源与证据/正文/图表/发布与历史”五组，修复真实
public URL/context、独立浏览器和冷 resume；旧七 workspace/URL 仅兼容读取。最后再做跨层 Product Use/PUBLIC_E2E，仍需肯恰大人
实际 HUMAN_ACCEPTANCE 才能讨论接受；不自动 PROMOTE。

每个 Phase 遵循“直接复现 -> 最小修 -> 真实测试 -> 重测”；只关闭第一个真实 blocker，
没有新 authority、packet、marker、receipt 或未经确认的架构扩张。

## 14. 停止规则

若不能同时证明 `producer -> persistence -> public caller`、当前 revision/head、精确 write
set、依赖 digest、真实用户可见证据和层级边界，立即在第一处 `HOLD` 停止。当前设计不授予
Ready、HUMAN_ACCEPTANCE、scientific validity、PROMOTE 或 B2；这些结论必须由相应新鲜证据
和肯恰大人的明确确认产生。
