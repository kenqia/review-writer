# Review Writer 规模化垂直 Benchmark 设计

日期：2026-07-25
状态：已批准，待实施计划

## 1. 产品判断标准

任何新增文件或机制必须至少满足一项：

1. 直接提高综述科学质量；
2. 减少科研用户操作；
3. 支持真实规模。

最终产品必须让化学科研用户在不了解 Agent、Prompt、JSON、Git、hash、schema、worktree 或 Provider 日志的情况下，用少量必要确认得到一份证据可追溯、可编辑、值得继续完善的综述。

不满足上述判断标准的机制不得进入本轮。M2 保留为 golden regression，不再作为产品主线继续扩建。

## 2. 本轮目标

用一个开放获取条件较好、与 M2 不同的真实有机合成主题，完成一次 20–30 篇核心研究的端到端垂直 benchmark，验证：

- 文献发现、合法获取、逐篇证据抽取和跨研究综合能在真实规模运行；
- QoderWork CN/Qwen 的模型能力被用于语义理解、审查和写作，而不是被静态模板替代；
- 所有重要正文、表格和图示结论都能回到原始文献 locator；
- 科研用户只面对范围、证据、风险决定和可编辑成品；
- 人工修订量和 Qoder credits 消耗可接受；
- 同一条产品路径能够继续用于其他化学主题，而不需要 case-specific 代码。

## 3. Benchmark 科学主题

### 3.1 Review question

2017–2025 年，以 Katritzky 型 N-alkylpyridinium 盐作为脱氨碳中心自由基前体的官能团化反应，在 activation mode、反应类型、底物适用性、实用限制和机理证据方面有何差异？

### 3.2 科学范围

纳入：

- peer-reviewed primary synthetic studies；
- photoredox、EDA/catalyst-free、electrochemical、transition-metal 或 dual-catalytic pathways；
- 至少报告一项由 Katritzky 型盐产生脱氨碳中心并形成新键的独立合成结果；
- 合法可得的 MAIN 全文；若定量、scope、negative result 或机理主张依赖 SI，则对应 SI 也必须可得。

辅助材料：

- 2–4 篇 review 仅用于术语、背景和 citation chaining，不计入核心 primary-study 数量。

排除：

- N-centered radical；
- 非脱氨用途；
- 只有摘要且无法核验关键证据；
- 没有独立合成结果的纯计算研究。

机理表述必须区分 `AUTHOR_PROPOSED`、`EXPERIMENTALLY_SUPPORTED`、`CROSS_STUDY_SYNTHESIS` 和 `UNRESOLVED`。

目标为 24 篇核心 primary studies；20–30 篇是科学纳排后的可接受规模，不是抽样配额。超过 30 篇时不得按结果好坏挑选：能够闭合则全部处理，否则因科学范围变化返回 Review Brief 重新确认。少于 20 篇时，只有在可审计检索已经充分且主题确实稀疏时才允许继续。

## 4. 用户体验

正常运行只有三次计划内用户交互：

1. **Review Brief**：用户提供主题和必要背景，并确认一页范围、时间边界、来源边界和交付目标；
2. **Scientific Risk Packet**：集中处理一次真正影响结论的高风险问题；
3. **Final Review**：在动态工作台阅读和修改正文，检查 DOCX，并确认交付版本。

只有以下情况可以增加例外交互：

- 合法全文或关键 SI 无法取得，且会改变纳排或主要结论；
- 科学范围必须实质改变；
- 已确认的预算不足以完成质量底线；
- 领域专家必须裁决但当前不可用。

科研用户界面只显示：

- Review Brief、当前阶段和覆盖率；
- 文献列表与 evidence cards；
- 可编辑正文、citation 和 locator；
- 必须人工决定的 risk packet；
- DOCX 生成和 release status。

用户不得被要求复制 Prompt、选择内部 Agent、编辑 JSON、运行 Git、操作 worktree、寻找输出目录或人工同步 Markdown/DOCX。

## 5. 最小内部架构

### 5.1 Source layer

确定性本地程序负责绑定 canonical DOI、MAIN/SI、文件 hash、页码、原文 excerpt 和 locator。模型只能选择或引用 Source layer 已产生的 locator，不能自行生成“看起来像原文”的 excerpt 或页码。

真实 PDF 和完整 corpus 保持在本地。逐篇语义任务只向 QoderWork 提供当前研究所需的 sealed parse、图表 crop 和 locator map；Writer 只接收已批准 claims，不接收完整 corpus PDF。

### 5.2 Evidence layer

每篇核心研究形成一张独立 evidence card，至少覆盖：

- study identity 和 activation mode；
- precursor、product/bond formation 和 reaction class；
- catalyst、additives、conditions、scale；
- yield 与选择性及其类型；
- scope、negative/boundary result 和 practical limitation；
- 作者机理解释、实际机理证据和证据强度；
- 每项 material observation 的 source locator。

Qwen/QoderWork 负责语义抽取和分类。确定性程序负责 DOI、数字、单位、excerpt、页码、source coverage 和结构合同检查。任何 Provider 输出均不得由开发者手工改写后冒充模型结果。

### 5.3 Claim layer

Claim 状态单调：

- `APPROVED`：可进入 Writer whitelist；
- `BLOCKED`：当前证据不足或验证失败，不得进入正文；
- `HUMAN_REQUIRED`：必须进入集中 risk packet。

以下内容至少为 `HUMAN_REQUIRED`：结构或立体化学裁决、机理/因果措辞、跨研究 superiority、冲突或 outlier、negative/generalization、会改变结论的 evidence gap，以及领域专家认为需要收窄的表述。

失败不得通过降级措辞静默进入正文，也不得因单篇失败而让其他研究停工。

### 5.4 Manuscript layer

正文按 evidence clusters 分章节生成。Writer 只能消费 `APPROVED` whitelist、已记录的 exclusions 和明确的 unresolved limits。一个 authoritative manuscript 驱动动态工作台、DOCX、citation/locator lineage 和 release package，避免两套正文漂移。

最小权威对象只有：

1. Review Brief；
2. Corpus/Source records；
3. Evidence cards 与 Claim decisions；
4. authoritative manuscript；
5. 按需生成的 risk packet 和 release package。

不为本轮新增通用 Registry、Hook、receipt 平台、任意 Provider framework 或法证日志系统。

## 6. 端到端数据流

### 6.1 Discovery and acquisition

使用 Crossref、OpenAlex、出版商页面、核心 review 的 backward/forward citation chaining 和必要的补充检索建立候选池。所有候选保留 provenance、去重关系和 screening disposition。下载能力与科学 eligibility 分离；只自动获取公开可达且不需要绕过访问控制的材料。

### 6.2 Three-study calibration

先处理三篇科学差异明显且最终会保留在 corpus 中的研究，覆盖至少三种 activation modes。该批次用于校准 evidence card、Qoder role 和 credits 预测，不创建一次性测试数据。Evidence 字段只允许据此修订一次。

### 6.3 Scaled extraction

其余研究按每批 4–6 篇处理：

1. 本地建立 source/locator package；
2. Qwen 逐篇生成 evidence candidate；
3. 确定性 validation；
4. fresh adversarial semantic review；
5. 注册 approved、blocked 和 human-required claims；
6. 将失败项加入一次集中 exception queue。

除一次有界 schema repair 外，不做自动重试或模型 fallback。校准批次完成后必须按实测 credits 预测全量成本；预测超过用户确认的预算时，在批量调用前停止，不静默削减语料或科学检查。

### 6.4 Cluster synthesis and drafting

通过 activation mode、bond formation、substrate class、practicality 和 mechanism evidence 形成 evidence clusters。每个章节先生成 claim-backed outline，再由 Qwen Writer 写比较性正文。单篇 observation 不得升级为趋势；趋势必须绑定完整可比较集合；`not reported` 不得改写为失败。

### 6.5 Human risk review

Risk packet 去重后集中呈现原文、locator、拟采用措辞、冲突和建议动作。领域化学研究者只需选择 approve、reword、exclude 或 unresolved。为测量模型真实误差，同一次 packet 还包含分层抽取的低风险样本，不增加新的用户交互阶段。

### 6.6 Finalization

批准结果只传播一次到受影响 claims、正文、表格和图示。动态工作台和可编辑 DOCX 从同一 authoritative manuscript 重新生成并执行 citation、lineage、链接、版式和视觉检查。任何实质修改都会使旧 release verdict 失效。

## 7. 动态工作台边界

本轮只交付单个综述作业的完整动态闭环：

- 阶段、候选数、核心研究数、证据覆盖率和 blocked 数随作业状态更新；
- evidence card 可按研究、章节和 claim 展开，并能跳转到 citation/locator；
- risk packet 可在页面中批量作决定；
- 正文可分章节编辑并保存回 authoritative manuscript；
- DOCX 可从当前批准版本生成；
- 页面明确显示 `IN_PROGRESS`、`AI_REVIEWED_BENCHMARK` 或 `DOMAIN_EXPERT_REVIEWED`。

不建设账户系统、多人实时协作、CMS、云端文献库、analytics、移动端或通用插件市场。动态工作台是科研用户界面，不是内部 Agent 控制台。

## 8. 验收标准

### 8.1 Scientific coverage

- 科学纳排后有 20–30 篇核心 primary studies，或对范围客观稀疏给出可审计证明；
- 100% 候选具有 provenance、去重关系和 screening disposition；
- 100% 核心研究具有 MAIN、evidence card 和至少一个可定位 reaction anchor；
- 所有依赖 SI 的 material claims 均绑定相应 SI；
- 100% material assertions、表格行和 chemistry visuals 绑定 claim 与 locator；
- 0 个虚构 DOI、引用、数字、excerpt 或页码；
- 0 个未标识的 source conflict；
- 0 个把 `not reported` 改写为 `failed` 的实例；
- 机制主张全部区分 proposed、supported、synthesized 和 unresolved。

### 8.2 Scale and reliability

- 三篇 calibration 与全量 corpus 使用同一条 case-neutral pipeline；
- 至少 90% 核心研究无需人工编辑 Provider 输出即可通过或进入明确的 exception/risk 状态；
- 单篇失败不会造成全作业数据丢失或重复处理已完成研究；
- Writer 只能读取 approved whitelist 的约束通过反例测试；
- M2 golden regression 继续通过，且 Case 02 中不得出现 topic、paper ID 或本地绝对路径硬编码。

### 8.3 User effort and scientific correction burden

- 正常流程保持三次计划内用户交互；
- 用户不接触 Prompt、Agent、JSON、Git 或运行目录；
- 集中 risk packet 的目标主动审查时间不超过 90 分钟；若超过，必须报告主要负担来源，不得通过隐藏风险来达标；
- 低风险分层样本中需要 material reword/exclude 的比例不超过 10%；
- 专家审查后不得有 unresolved critical error；
- 终稿不得有需要从头重写的章节，material assertions 的 reword/exclude 比例目标不超过 15%。

这些人工指标必须按真实审查记录计算，不能由 AI 自评替代。没有领域化学研究者完成该次审查时，可以形成 `AI_REVIEWED_BENCHMARK`，但不能宣称已经证明人工修订量可接受。

### 8.4 Deliverables

- 一篇 evidence-driven critical comparative review，篇幅由证据决定，预期约 6,000–9,000 英文词；
- 2–3 张带完整 lineage 的 comparison tables；
- 2–4 幅用于解释 activation mode、反应范围或机理证据的 chemistry visuals；
- 一个可持续更新、可编辑正文并查看 evidence cards 的动态工作台；
- 一份可编辑 DOCX，引用、链接、表格和图片可用；
- 一份简短 benchmark report，报告覆盖率、失败率、人工修订量、Qoder credits 和已知限制。

不得为达到词数或图数填充无证据内容。

## 9. 停止和降级条件

仅在以下情况暂停主链：

- Review Brief 需要实质范围变更；
- 合法 MAIN/SI 缺失使核心纳排或主要结论无法闭合；
- source、locator、结构或立体化学无法可靠核验；
- 校准后预测 credits 超过已确认预算；
- QoderWork 关键语义角色在 calibration 中不能达到 grounding 底线；
- 高风险科学判断需要领域专家而专家暂不可用；
- 最终动态工作台或 DOCX 与 authoritative manuscript 发生 material drift。

以下情况不得阻塞主线：

- 单篇研究抽取失败；
- 一个 discovery source 暂不可用；
- 装饰动画、账户、analytics 或通用云服务未完成；
- 文稿自然短于预期但没有安全证据可扩写；
- 非关键 cosmetic defect。

无法闭合时必须交付明确标记的 partial/AI-reviewed package 和未闭合项，不得静默降低质量底线。

## 10. 实施边界

实施顺序必须沿一条垂直主链：

1. 让现有 QoderWork product entry 能完成 Review Brief；
2. 用三篇 calibration 跑通 source → evidence → claim → section → workbench → DOCX；
3. 修复该链路中真实出现的阻塞；
4. 扩展到 20–30 篇；
5. 完成一次专家 risk review 和最终交付。

任何候选改动在进入计划前必须回答：它是否直接提高综述质量、减少用户操作，或支持真实规模？回答不清楚则不实施。
