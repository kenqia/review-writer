# Review Writer 产品 SRS

> 文档状态：\`CANONICAL / TARGET SPECIFICATION / IMPLEMENTATION NOT READY\`
> 版本：\`0.1\`
> 日期：\`2026-08-20\`
> 产品方向：高风险化学综述的证据审计与决策工作台

本文件是产品需求的唯一入口之一，定义“普通研究者如何从 Topic/RQ 与本地获授权
PDF 得到一份可审计的综述决策包和版本绑定的交付物”。它不是当前代码已完成能力的
清单，也不把 Engineering PASS、bounded synthetic、Product Use 或测试通过写成用户
验收、科学有效性或可发布状态。实现前以本文件和
[\`REVIEW_WRITER_DESIGN.md\`](./REVIEW_WRITER_DESIGN.md) 为准；实现中的差异必须明确
标为 \`CURRENT\`、\`TARGET\` 或 \`HOLD\`。

## 1. 一句话结论

普通用户只需要在 Codex 中说明：

1. 自然语言综述主题（\`topic\`）；
2. 明确的、可写的项目根目录（\`explicit project root\`）；
3. 本次明确授权读取的本地 PDF folder；
4. 可选的 RQ、范围、目标期刊或格式要求。

随后由 Agent 在同一个项目 authority 内完成来源清点、解析、证据审计、跨研究综合、
图件候选、综述草稿和 Markdown/DOCX 交付，在确需人判断时只把一个可解释的
\`Decision Bundle\` 交给研究者。研究者不需要运行 CLI、cURL、pytest、内部脚本或
\`generator-start\`/\`generator-continue\`。

产品必须能处理可变研究数量 \`N\`。\`N\` 不是产品输入中的固定 \`1–3\`，也不能被旧的
\`20–40\` 约束冒充为最终公共合同；\`N=1/3/10/20\` 只是首轮回归和容量验证点。缺少
证据、身份或科学判断时，系统暂停并给出最小修复动作，不猜测、不扩写、不覆盖旧
current。

## 2. 现状基线与目标边界

### 2.1 \`CURRENT\`：只描述已观察到的历史系统

只读审计显示，仓库中实际存在下列能力或历史资产：

- variable-N corpus、MAIN/SI 成对合同、Generic/Chemical dual parse、source truth、
  hash/page/locator 绑定、Paper Evidence、Matrix/RQ/Gap、多研究 synthesis primitive；
- Comparison Protocol、Coverage/Synthesis Claim/Section Contract、batch runner；
- Chemical GAP/completion、source figure registry/attribution/license/manuscript binding；
- manuscript v1/v2、\`USER_EDITED\`、\`VersionContext\`、Markdown/DOCX、stale/regenerate、
  History/branch/undo/resume、fail-closed/zero-write；
- Dashboard 与 native \`GeneratorSession\` 的研究者工作台能力。

这些能力分散在不同历史入口和状态布局中。当前公开 package 的本地
\`review-orchestrator\` 主要走 PDF-only、single-study、bounded route；旧 variable-N
能力主要暴露为 CLI/manifest，当前二者没有收敛成一个普通用户可依赖的公共链路。
现有 \`tests/product_use\` 共有 79 项；最近整套结果为 \`72 passed / 6 failed / 1 skipped\`，
失败集中在 public Dashboard context 等待。上述数字和观察用于说明重构起点，不是
目标承诺，也不构成 Ready。

当前公开入口仍可能同时出现旧页面、旧 URL、旧 stage API、单研究流程和
\`20–40\` 语料输入说明。任何实现都必须显式标出兼容层与 canonical 层，不能把其中一
条路径的通过推广到整个产品。

### 2.2 \`TARGET\`：本 SRS 的产品承诺

目标产品只有一个面向普通研究者的 Agent-first 入口和一个项目级 durable authority：

\`\`\`text
自然语言 Topic/RQ + explicit project root + authorized PDF folder
        -> Agent 编排（内部调用工具）
        -> Source Truth / Parse / Evidence / Matrix / Gap
        -> 一次性 Decision Bundle（必要时 HUMAN_ACTION_REQUIRED）
        -> multi-study synthesis + figures + manuscript
        -> Markdown/DOCX Release
        -> stale / regenerate / History / resume
\`\`\`

目标不是抹掉旧代码，而是先冻结统一产品合同，再以适配器复用已存在的可信生产者，
只在真实第一失败点补缺。

## 3. 角色、输入与输出

### 3.1 角色

| 角色 | 允许做什么 | 不允许替代什么 |
| --- | --- | --- |
| 普通研究者 | 给 Topic/RQ、授权 PDF；在 Dashboard 阅读、决定 MAIN/SI、确认/驳回证据、编辑正文、检查图件与 Release | 不需要知道内部命令，不被假设为自动确认科学结论 |
| Generator Agent | 在项目目录调用确定性工具，计划/执行解析和生产，读取同一 current，停在人工 gate 后继续 | 不得把候选变成确认，不得越过人工 gate，不得建立第二状态库 |
| Dashboard | 提供人类研究工作台和唯一可见下一动作，通过 canonical writer 保存决定/编辑 | 不得成为事实源、独立 current 或自动批准器 |
| 工具/Producer | 生成 Source Truth、Parse Quality、Evidence、Matrix、Gap、Figure、Draft、Release artifact | 不得直接移动 current 或隐式改变研究者决定 |
| Independent Verifier | 用新鲜环境验证里程碑和失败路径 | 不得将 bounded 证据升级为 HUMAN_ACCEPTANCE/scientific validity |

### 3.2 用户最小输入合同

必填：

- \`topic\`：非空自然语言主题；Agent 记录原文和规范化摘要，不能擅自缩窄范围；
- \`explicit_project_root\`：绝对、明确、用户授权的项目目录。新项目只能在空目录创建；
  恢复必须使用原项目根目录；缺失或不明确时 \`HOLD\`；
- \`authorized_pdf_folder\`：用户明确授权读取的本地目录。Agent 只能枚举、复制或解析该
  目录允许的 PDF，不扫描其它位置，不联网下载，不访问未授权文件。

可选：\`review_questions\`、\`scope\`、\`venue\`、\`language\`、\`figure_policy\`、输出格式。
若用户没有提供 RQ，Agent 可以提出候选，但不能在未确认时将候选当作权威 RQ；系统可
先生成范围和证据缺口预览，不能提前写成发布稿。

输入不包括：CLI 参数、内部 manifest 路径、MinerU token、解析器命令、API 地址、
浏览器 cookie 或云端账号。授权 PDF folder 只作为输入边界，不等同于用户批准内容。

### 3.3 交付物

在同一个项目根目录内产生（具体相对路径由 Design 冻结，历史路径可由兼容适配器读取）：

- Source Set：每个 study 的 MAIN/SI identity、文件 hash、页数、角色和来源关系；
- Parse Record：默认 MinerU 或真实 fallback 的 backend/version/contract、输入 hash、
  输出 digest、时间、失败/降级原因和可重放信息；
- Source Truth：页码、段落/章节、figure/table、原始 PDF 与解析对象的 locator；
- Evidence、Matrix、Gap：带 source locator、study identity、证据状态和不可比较原因；
- \`Decision Bundle\`：一次人工阅读所需的候选、证据、冲突、待决定事项和影响预览；
- Multi-study synthesis：Comparison Protocol、Coverage、Synthesis Claim、Section
  Contract 与可追溯的章节草稿；
- Figure registry：真实 PDF 图件候选、原图 hash/page/bbox/caption、attribution/license
  证据、选择状态和 manuscript binding；
- authoritative manuscript v1/v2（保留 \`USER_EDITED\`/\`RESEARCHER_AUTHORED\`）；
- 同版本 Markdown 和 DOCX，以及 release snapshot、quality report、current/version 绑定；
- History/compare/branch/undo/resume 所需的 immutable version nodes。

## 4. 产品目标与成功定义

### 4.1 目标

1. **降低不支持 claim**：正文每一个 material claim 都能往返到当前 source/hash/
   locator/evidence/decision；无法闭环的内容显示为 limitation 或 Gap。
2. **减少专家复核时间**：将跨来源冲突、解析异常、需要身份判断的事项聚合为少量
   Decision Bundle，一次处理一组同源决策，而不是在多个页面反复点击。
3. **降低研究者决策成本**：界面展示“为什么需要决定、决定影响哪些证据/段落/图件、
   现在的最小下一步是什么”，不展示无关工程诊断。
4. **支持 N-agnostic 复用**：从单 study 到多 study 的数据流一致；增加或替换来源时
   只增量解析受影响对象，不重做未变化对象。
5. **保留化学判断与用户编辑**：AI 只能给候选和不确定性，不覆盖人类判断，不丢失正文
   编辑、理由、版本历史或 source locator。

### 4.2 可验收的产品结果

目标验收必须同时看到：

- 用户只通过自然语言入口启动/恢复，并拿到真实 Dashboard URL；
- \`N=1/3/10/20\` 均使用同一逻辑合同，N 不改变数据模型；
- 新增/替换单个 PDF 时，未变化 source 的 parse/evidence digest 不变，受影响下游
  明确 stale；
- MinerU 失败时真实 fallback 被记录，原因和 backend provenance 可见，不得静默切换；
- 一次 Decision Bundle 能完成 MAIN/SI 身份、parse quality、Evidence 状态和 Gap 决策，
  并能恢复相同 Bundle，不重复写入已决定项目；
- multi-study synthesis 能区分可比较、不可比较和证据不足，不用缺失值填充结论；
- 图件候选有来源、hash、页码、署名/许可和正文绑定；缺失权利证据时 release 保持 GAP/HOLD；
- 用户编辑 v1 后生成 v2，release 与 v2 同版本；正文变化使旧 release stale，必须
  regenerate；
- 查看历史不移动 current；冲突、错误、过期和错误角色输入均为 fail-closed 且 zero-write；
- 所有层级分别报告，不以测试或 Agent 文本推断 HUMAN_ACCEPTANCE、科学有效性或 PROMOTE。

## 5. 功能需求

需求 ID 是后续实现、测试和变更请求的稳定引用。没有标注 \`TARGET\` 的行为均不代表
当前已经实现。

### 5.1 Agent-first 入口与项目生命周期

**FR-001（TARGET，唯一入口）**
Agent 接受 \`topic + explicit_project_root + authorized_pdf_folder\`，可选 RQ/范围/格式；
缺任一必填项时返回可理解的缺口，不让用户运行内部命令。

**FR-002（TARGET，fresh/resume）**
新项目从空目录创建；恢复项目读取同一项目的 current、VersionContext、source/evidence
绑定和未完成 Decision Bundle。不能创建平行 session store、workspace 或第二 current。

**FR-003（TARGET，授权边界）**
只读授权 PDF folder，拒绝符号链接/reparse escape、目录外路径、非 PDF、重复字节跨
study 复用和未授权网络获取；拒绝前不写项目 authority。

**FR-004（TARGET，进度）**
Agent 返回项目 ID、阶段、current/version/revision、当前阻断原因和 Dashboard URL；
需要研究者决定时返回 \`HUMAN_ACTION_REQUIRED\`，不假装完成。

### 5.2 可变 N、source-set expansion 与增量解析

**FR-005（TARGET，N-agnostic）**
项目的 \`N\` 是 source set 的实际计数，产品合同不得固定为 \`1–3\` 或 \`20–40\`；系统
必须允许合法的单 study、少量、多篇和更大本地集合。首轮必须验证 \`N=1/3/10/20\`，
并报告每个 N 的可用性与性能边界，而不是将验证点写成产品上限。

**FR-006（TARGET，source-set expansion）**
用户可在同一项目中添加授权 PDF。Agent 计算新 source identity，保留旧 version，
只为新增/变化 study 建立新的 candidate；source set 变更后，受影响的 Matrix、Gap、
Synthesis、Figure、Manuscript、Release 被精确标 stale。

**FR-007（TARGET，incremental reparse）**
若 PDF hash、解析 backend/version/contract 和 parse input binding 未变，复用已验证的
parse object；若任一改变，只重跑受影响 source。复用必须保留原 output digest 和
provenance，禁止通过 basename 或时间戳猜测等价。

**FR-008（TARGET，identity）**
每个研究的 MAIN/SI 角色、study/source ID、文件 hash、页数、标题/DOI（若有）必须可
验证。重复、错角色、MAIN/SI 不匹配、跨 study 复用或 hash 变化在写入前拒绝。

### 5.3 Parse、Source Truth 与质量门

**FR-009（TARGET，默认解析器）**
本地 MinerU 是默认 Generic Parse backend；Agent 负责内部调用并记录输入 hash、
输出对象 digest、版本、配置 contract、时间和状态。用户不接触 token 或解析命令。

**FR-010（TARGET，真实 fallback）**
MinerU 不可用、失败、超时或输出不满足 contract 时，系统只能切换到已登记且可验证
的本地 fallback（例如 PDF text/layout parser）。Fallback 必须记录：
\`fallback_reason\`、backend/version、输入/输出 hash、能力缺口（如没有图件或化学结构）、
attempt 序列和重试边界；没有真实 fallback 就返回 HOLD，不写“fallback succeeded”。

**FR-011（TARGET，Source Truth）**
每个 source 的 Source Truth 是下游唯一可引用事实边界。它至少包含 PDF hash、解析对象
hash、页码、章节/项目、figure/table、原始 PDF 可回看位置和 source role。解析候选与原始
PDF 人工定位必须明确区分。

**FR-012（TARGET，Parse Quality）**
系统检查正文顺序、章节边界、图/caption、表格、公式/化学符号、参考文献边界和
MAIN/SI 完整性；异常进入 Decision Bundle。Parse Quality 通过不等于科学正确，也不
自动批准 Paper Evidence。

### 5.4 Evidence、Matrix、Gap 与 Decision Bundle

**FR-013（TARGET，Evidence）**
Evidence candidate 必须包含 statement、epistemic type、source locator、条件/定量结果、
limitations、mechanism grade、field dependencies、绑定 parse digest 和 source PDF hash。
\`CONFIRMED\`、\`AI_PROVISIONAL\`、\`BLOCKED\` 是不同状态；没有 locator 或不能唯一支撑的
候选不能进入 confirmed projection。

**FR-014（TARGET，Matrix/RQ binding）**
每条 Matrix 行绑定一个稳定 RQ、study/source、Evidence ID、locator 和 canonical digest。
跨研究比较必须显式声明 Comparison Protocol；缺少同口径条件时标记 \`NOT_COMPARABLE\`
或 Gap，禁止用空值、猜测或旧矩阵补齐。

**FR-015（TARGET，Gap registry）**
Gap 记录缺失输入、解析缺陷、冲突、未确认化学字段、权利问题、不可比较条件和下一步
最小修复动作。Gap 可以阻断 claim/release，但不能被 UI 的“完成率”隐藏。

**FR-016（TARGET，一次性 Decision Bundle）**
Agent 将同一 source set 当前需要的人类事项聚合成有边界的 Bundle，展示：

- source identity、MAIN/SI 关系、hash/page 和 parse provenance；
- 原始 PDF locator、解析候选、冲突与风险等级；
- 受影响的 Evidence/Matrix/Gap/figure/section/release；
- 可选决定（确认、修订后确认、驳回、保持 GAP、要求重解析）及理由字段；
- 预计写入集合、当前 revision 和并发冲突提示。

Bundle 决定通过一个 canonical writer 事务写入 immutable decision events 和 projection；
重复提交相同 revision/digest 必须幂等，旧 Bundle 对新 current 提交必须 \`VERSION_CONFLICT\`
且 zero-write。Bundle 是减少人工次数的聚合，不是自动批准器。

### 5.5 Multi-study synthesis 与图件

**FR-017（TARGET，multi-study synthesis）**
Synthesis adapter 以 per-study Evidence/Matrix/Gap 为输入，产出 Comparison Protocol、
Coverage、Synthesis Claim、Section Contract 和可追溯章节。它必须保留 study 边界、
条件差异、冲突与不确定性，支持 N 增长/减少；不直接读 legacy matrix 作为事实源。

**FR-018（TARGET，PDF figure candidates）**
图件候选只能来自获授权 PDF/解析资产，记录 source PDF hash、study/source ID、页码、
figure label、caption、asset hash、bbox/fragments、Evidence IDs 和 selection status。
候选不是正文图，也不是科学批准。

**FR-019（TARGET，attribution/license/binding）**
被选图件必须有 attribution、license/rights evidence 或明确 \`unknown\`；权利未知时可
保留为内部候选，但不能进入可发布 release。正文绑定必须含 section、marker、occurrence、
manuscript hash 和 asset hash；正文/图件任一变化使 binding stale。

### 5.6 Manuscript、Release、History 与 Resume

**FR-020（TARGET，草稿）**
Agent 只从当前 source-bound Evidence/Gap 生成 manuscript v1；Dashboard 人类编辑通过
同一 authority 写入 \`USER_EDITED\`/\`RESEARCHER_AUTHORED\`。v2/v3 只能增量合并，不能
覆盖人类段落或删除理由。

**FR-021（TARGET，Markdown/DOCX）**
Markdown 与 DOCX 必须由同一 manuscript/version 生成，保留 citation、figure、attribution
和 release lineage。任一输出 hash 与 snapshot 不一致都不能称同版本交付。

**FR-022（TARGET，stale/regenerate）**
source、Evidence、Matrix、Gap、figure、正文或用户决定发生物质变化时，旧 release 变为
\`STALE\`；旧文件不能伪装成当前下载。Agent/Dashboard 先生成 candidate，再在校验通过
后 regenerate；stale 期间下载返回受保护的 stale/blocked 结果。

**FR-023（TARGET，History）**
History/compare 只读 immutable nodes；\`Branch from here\` 明确创建可写 candidate；undo
创建新版本节点，不能覆盖历史；current 与 inspected 分离。

**FR-024（TARGET，cold resume）**
从同一 explicit project root 冷恢复时，Agent 重新读取 current/versions/decisions，复用或
重启其拥有的 Dashboard；不得假定内存 session、生成第二 authority 或覆盖未完成/用户编辑。

### 5.7 失败关闭与安全

**FR-025（TARGET，zero-write）**
缺失、重复、错误角色、损坏、过期、错 hash、未授权路径、解析 contract 失败、并发
冲突、缺少人类决定、权利不明或 canonical dependency 不完整时，拒绝 current/release
写入。允许写入明确的隔离 candidate/error receipt 的前提是不会污染 current；若无法证明
隔离，也必须 zero-write。

**FR-026（TARGET，安全边界）**
项目根目录、其 authority 组件和授权输入均拒绝 symlink/reparse escape；不写入 secrets、
token、cookie、auth 或完整原始敏感日志；Dashboard 仅监听本地 loopback。错误信息对用户
给出稳定 category code 与最小修复动作，不回显 secret 或隐私路径。

## 6. 质量分层与不可越界的结论

| 层级 | 证明什么 | 不能证明什么 |
| --- | --- | --- |
| Engineering | 类型/契约、focused regression、锁、hash、fail-closed/zero-write | 普通研究者能完成全链路、科学结论正确 |
| Independent Quality | 新鲜环境、独立浏览器/视口、DOM/console、兼容 URL、stale 证据 | 用户接受、论文科学有效 |
| Product Use | 隔离真实项目中从 Evidence 到 Draft、Figure、DOCX、History/resume 的代表路径 | 未覆盖 N、所有 PDF、发表资格 |
| \`PUBLIC_E2E\` | 普通用户以自然语言、explicit root、授权 PDF 走公开入口的独立证据 | 科学 validity 或产品已发布 |
| \`HUMAN_ACCEPTANCE\` | 肯恰大人实际阅读并接受的产品体验与结果 | Agent 自己推断接受 |
| scientific validity | 合格化学研究者对来源、结构、机制和比较的科学判断 | 代码测试或模型置信度 |
| PROMOTE/B2 | 明确批准后的版本提升 | 任一 bounded/synthetic PASS |

任何报告必须同时带上 scope、输入 N、项目根、代码/项目版本、证据新鲜度和限制。当前
状态依据审计是 \`NOT_READY\`；本 SRS 不改变它。

## 7. 非功能需求

### NFR-001 可追溯性

从最终段落/图件反查到 Synthesis Claim、Matrix、Evidence decision、Source Truth、PDF
hash/page/locator；反向从 source 能看到哪些段落/图件受影响。

### NFR-002 可重放与增量性

相同 source hash、parse contract、Decision Bundle revision 和代码/配置 digest 应得到
等价对象 digest；单 source 变化不能隐式重跑或改变未受影响对象。

### NFR-003 可用性与性能

N=1/3/10/20 的 intake、source-set expansion、parse scheduling、Decision Bundle、synthesis
projection 必须分别测量 wall time、峰值磁盘、失败恢复和未受影响对象复用率。目标阶段
不设未经测量的最大 N；达到资源边界时给出可解释 HOLD。

### NFR-004 本地优先与隐私

默认不上传 PDF、正文、Evidence 或用户编辑；MinerU/Fallback 的网络能力必须由产品
显式配置和 provenance 记录授权。密钥只在运行时受控读取，不能进入项目 artifact 或 UI。

### NFR-005 并发一致性

同一项目的 Agent 与 Dashboard 写入经过同一个 project writer/lock；expected revision/head
校验失败立即 zero-write。不可用或损坏的 current 必须先 HOLD，不得从 legacy 文件猜 current。

### NFR-006 可迁移性

旧单-study preview 可以作为 N=1 输入适配器；旧 URL/API GET 继续可读，旧写路径必须
转发 canonical writer 或显式返回 \`405/NOT_SUPPORTED\`，不维持第二存储协议。

## 8. 首轮验收矩阵（需求级，不等于当前通过）

| 场景 | 输入/扰动 | 必须观察到的结果 | 层级 |
| --- | --- | --- | --- |
| N contract | N=1、3、10、20 的合法 source set | 同一 schema/流程；计数按实际 N；不出现固定旧分母 | Engineering + Product Use |
| Source expansion | 已完成 N 的项目新增 1 个 source | 新 source 增量解析；未变化 digest 不变；下游精确 stale | Product Use |
| Incremental reparse | 替换一个 MAIN 或改变 parser contract | 仅受影响 source 重解析；旧依赖不冒充 current | Engineering |
| Parse fallback | MinerU timeout/invalid output，真实 fallback 可用 | fallback provenance 完整；能力缺口进入 Gap | Product Use |
| Parse fallback unavailable | 两个 backend 都失败 | \`HOLD\`/\`HUMAN_ACTION_REQUIRED\`，current/release zero-write | Engineering |
| Identity errors | duplicate、wrong role、MAIN/SI mismatch、stale hash | 400/409 类稳定失败，项目字节不变 | Engineering |
| Decision Bundle | 同一 Bundle 提交、重复提交、旧 revision 提交 | 一次写入/幂等；旧 revision \`VERSION_CONFLICT\` zero-write | Product Use |
| Chemical uncertainty | molecule/SMILES/molblock 缺失或候选未确认 | \`AI_PROVISIONAL\`/\`BLOCKED\` 与 Gap，不伪造结构 | Scientific boundary |
| Multi-study comparison | 条件不一致、study 冲突、N 变化 | \`NOT_COMPARABLE\`/Gap 可见，claim 保留 locator | Product Use |
| Figure rights | 图件无 license/attribution 或正文 marker 变动 | 内部 candidate 可保留；release 阻断或 stale | Product Use |
| v1 -> v2 | 人类编辑 v1 后 Agent 继续 | \`USER_EDITED\` 保留；v2 只做授权增量 | PUBLIC_E2E |
| Release | Markdown/DOCX 同一 manuscript/version | hash、lineage、figure binding 一致 | Product Use |
| Stale/regenerate | 发布后改变正文或 source | 旧 release stale；必须 regenerate 后才能下载新版本 | PUBLIC_E2E |
| History/resume | compare/undo/冷启动恢复 | 查看不动 current；undo 新节点；恢复同一 authority | PUBLIC_E2E |
| Legacy URL/API | \`?project=\`、旧 GET/API | 读取兼容并规范化到 \`project_id\`；旧写不绕过 writer | Independent Quality |
| Native entry | 用户只发送自然语言入口 | Agent 返回真实 Dashboard URL，不要求用户 CLI/cURL | \`PUBLIC_E2E\` |

## 9. 明确非目标（本版本不做）

- 不把 \`20–40\`、固定 \`1–3\`、旧三篇案例或历史 \`309\` 分母写成公共产品输入上限/默认；
- 不让用户承担 CLI、内部 API、脚本、pytest、浏览器开发工具或手工 JSON 编辑；
- 不自动发现/下载论文，不绕过授权、付费墙或版权限制；
- 不自动确认 MAIN/SI 身份、分子、SMILES、molblock、机制或科学因果；
- 不建立 Provider、RAG、SaaS、多用户云端数据库、通用工作流引擎或第二 session store；
- 不把 Dashboard 展示状态、ready marker、测试报告或 AI 生成文字当作 source truth；
- 不删除/覆盖既有项目、稳定版本、用户编辑、历史节点或 protected path；
- 不自动 PROMOTE、B2、投稿、发布社媒或写生产数据库；
- 不把 figure placeholder、unknown license 或未绑定 asset 当成可发布图件；
- 不以“全量逆向历史系统”作为一次重写授权。先由本 SRS 冻结目标，再做最小适配和
  首失败修复。

## 10. 关键术语

| 术语 | 定义 |
| --- | --- |
| Source Set | 本次综述实际纳入的研究集合；N 为集合当前计数，不是固定产品档位 |
| Source Truth | 由 PDF/hash/parse object/locator 组成的每个 source 事实边界 |
| Evidence | 带 locator、依赖和状态的单研究证据对象；candidate 不等于 confirmed |
| Matrix | Evidence 到 RQ 的 canonical projection，包含跨研究可比性和 digest |
| Gap | 不能安全进入 claim/release 的缺口、冲突或下一步修复动作 |
| Decision Bundle | 为一次人类复核聚合的候选、冲突、影响和决定写集 |
| Candidate | 新生成但尚未 pointer-last 成为 current 的版本或 artifact |
| Current | VersionContext 唯一指向的当前可写/可读版本；不是 Dashboard 内存状态 |
| Stale | artifact 的输入、hash、版本或 binding 已不再对应 current |
| Fallback provenance | 解析器降级发生的事实、原因、backend/version、输入输出 digest |
| \`HUMAN_ACTION_REQUIRED\` | 必须由研究者决定，Agent 不得继续越过的明确暂停状态 |

## 11. 变更与停止规则

需求若新增第二 authority、固定新分母、自动科学批准、公共远程服务、不可逆迁移或
新的写入层，必须先提交产品变更请求；不能在实现阶段默默扩展。实现遵循“直接复现 →
最小修 → 真实测试 → 重测”，一次只修第一个真实 blocker；如果缺少路径、写集、producer、
persistence、public caller 或依赖证明，停在第一处 \`HOLD\`，保留现有项目不变。
