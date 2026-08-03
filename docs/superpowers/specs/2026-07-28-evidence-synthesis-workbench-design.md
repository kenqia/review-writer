# Review Writer 证据与综合判断工作台设计

日期：2026-07-28
状态：修订设计已批准，待用户审阅书面规格

## 1. 结论

Review Writer 应从线性阶段门禁系统重构为“证据 + 综合判断工作台”。系统的唯一真源不是阶段名称、文件存在、hash 或 claim ID，而是经过验证的以下关系：

```text
Source Record → Source Truth Bundle → verified Paper Evidence → approved Synthesis Claim → Manuscript Argument
```

目标交付物是内部使用、科学质量接近投稿初稿的完整综述，不是投稿包。机器负责规模化处理、格式、一致性与可追溯性；研究者负责范围、代表性、证据强度、跨研究综合、学术措辞和最终验收。

证据中心只能解决“某句话是否正确来自某篇论文”。达到标杆综述还必须解决“多篇论文合起来允许我们得出什么新判断”。因此 `Synthesis Claim` 必须成为与来源证据同等重要的一等对象。

正式主路线是“证据与综合判断工作台 + 高风险人工编辑升级”。系统优化的目标不是无人值守地产出论文，而是提高证据准备、综合判断和错误拒绝的质量。遇到定量、因果、机制、安全、优越性、否定性、冲突或单篇研究泛化等高风险内容时，必须升级为研究者直接编辑和批准。

综合图永久采用人工制作政策：系统只生成可追溯的 `Synthesis Figure Placeholder` 和制图 brief，不自动组合、重绘或生成科学综合图。研究者制作并上传最终图后，系统只负责来源、引用、文件和完整性检查，不替代科学验收。

## 2. 本设计与既有规格的关系

本设计继承现有工作台中的文献发现、PDF 导入、MinerU 解析、metadata、evidence atom、矩阵、蓝图、按节起草、引用检查和 DOCX/PDF 导出能力。

本设计在发生冲突时取代以下旧规则：

1. 取代长时间 `wait-state`、watcher 或 shell 轮询；
2. 取代“选择 ZIP 后立即上传并处理”；
3. 取代独立、低风险抽样式 Scientific Risk Packet；
4. 取代 unknown-license 原图阻塞内部交付的规则；
5. 取代仅凭文件、ID、receipt、lineage 或 LLM judge 即可放行的门禁；
6. 取代由可写阶段字符串作为科学进度真源的状态模型。

既有规格中不冲突的用户界面、来源匹配、解析、证据、正文编辑和导出设计继续有效。

## 3. 产品目标与非目标

### 3.1 目标

1. 防止来源串线、引用错配、补造条件和未读正文却批准；
2. 支持几十至几百篇文献的分层核验；
3. 帮助研究者形成比较、冲突、边界、局限和未来方向等综述级判断；
4. 允许按具体来源、证据、综合判断或段落局部返工；
5. 任意停止 dashboard、QoderWork 回合或机器后均可安全恢复；
6. 把人工操作限制在高价值科学判断，不要求用户处理 JSON、hash、manifest、receipt、schema、Git 或路径；
7. 以标准论文和已知失败稿建立正反两套可重复评估基线。
8. 把解析结果明确限制为可核验索引，保证所有高风险证据能够回到原始 PDF、SI、页面和原图。

### 3.2 非目标

1. 不承诺自动达到或被顶级期刊接收；
2. 不生成可直接投稿的合规包，不处理图片许可或投稿权限；
3. 不让 AI 自动生成化学结构、机理路径、实验装置、科学数据图或跨论文综合图；
4. 不建设云端语料库、账户系统、第二套 dashboard、通用工作流引擎或远端部署；
5. 不用单一总分、LLM judge 或工程 smoke 代替研究者科学验收。
6. 不承诺“完美综述”、期刊接受概率或无人值守的科学正确性。

## 4. 评估标杆

本地 `标准.zip` 是外部评估资料，不提交到仓库。它包含两类基线：

1. ACS Chemical Reviews 与 Nature Reviews 的作者指南、文章格式、图稿和化学结构规范；
2. Angewandte Chemie、Chemical Reviews、Nature Reviews Chemistry、Chemical Society Reviews 和 Green Chemistry 的代表性综述。

这些论文不作为同一种模板机械模仿，而按能力分工使用：

- Angewandte Chemie 的问题驱动文章用于评估比较与校准结论；
- Chemical Reviews 和 Nature Reviews Chemistry 用于评估机制/概念体系、权威性和可读性；
- Chemical Society Reviews 和 Green Chemistry 用于评估主题覆盖、分类和导航价值；
- 官方指南用于评估明确范围、综合性、批判性、可读性、挑战、未来方向和图表职责。

标杆包显示，顶级综述通常不是论文摘要的串联。它们以问题、机制或反应模式组织大量研究，并通过图、scheme、表格、结论和展望形成作者自己的领域判断。

### 4.1 MinerU 标杆复审

`标准.zip` 中 14 份 PDF 已使用精确模式完成 14/14 解析，保留 Markdown、图片、caption、`page_idx`、`bbox`、content list、layout 和 model sidecar。复审确认 MinerU 明显提高了检索、定位和图文恢复能力，但仍会出现双栏顺序错乱、章节合并或漏级、Scheme caption 被误判为标题、作者简介插入正文、化学式/符号误识别、caption 与图片邻接不稳定等问题。

因此 MinerU Markdown 是高质量索引，不是论文真相。任何解析器输出都只能生成候选证据，不能单独构成 Source Truth 或科学批准依据。

### 4.2 外部方法标杆

设计吸收但不误用以下工作流证据：

- Cochrane/PRISMA 的 protocol、预先定义范围、筛选、数据提取、偏倚和可复现记录用于约束 Source Set；
- SANRA 的重要性、目标、检索描述、引用、科学推理和关键数据呈现用于审查叙述性综述；
- OpenScholar 的专业语料库、retrieval、reranking、self-feedback 和 citation verification 用于检索与证据准备；
- PaperQA2 的 citation traversal、contextual summary 和矛盾发现用于候选证据与冲突提示；
- STORM 的多视角提问和 pre-writing outline 用于提出候选分类与缺口；
- AI 系统性综述评测显示筛选和文本抽取可显著节省时间，但表格、数值和低基率任务仍需领域验证和人工复核。

这些系统主要验证问答、筛选、摘要或 Wikipedia-style synthesis，不能证明完整顶级化学综述可以自动生成。外部指标只用于选择可吸收的组件，不得外推为整篇综述质量保证。

截至 2026-07-28 的关键依据：

- [Cochrane Handbook Chapter 1](https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-01) 与 [Chapter 5](https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-05)；
- [PRISMA 2020](https://www.bmj.com/content/372/bmj.n71)；
- [SANRA](https://link.springer.com/article/10.1186/s41073-019-0064-8)；
- [OpenScholar](https://www.nature.com/articles/s41586-025-10072-4)：验证 retrieval、reranking、self-feedback 与 citation verification 对多论文长答案有显著价值，但任务不是完整综述生产；
- [PaperQA2](https://arxiv.org/pdf/2409.13740)：验证 citation traversal、contextual summary 和 contradiction detection，但其代表性长文任务是 Wikipedia-style article；
- [STORM](https://arxiv.org/abs/2402.14207)：相对 outline-driven RAG，组织性提高 25 个百分点、覆盖广度提高 10 个百分点，同时仍存在来源偏差传递和无关事实过度关联；
- [ISLaR 2.0 评测](https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2025.1662202/full)：全文筛选 sensitivity 为 0.91、文本提取 sensitivity 为 0.98，但表格数据相对原文金标准仅 48.3% 正确，支持“机器批量处理 + 高风险人工复核”。

## 5. 核心数据模型

### 5.1 Review Brief

记录研究问题、目标读者、时间边界、纳排标准、比较维度、目标篇幅、标杆论文和质量门槛。Brief 必须说明综述不覆盖什么，以及为什么此时值得综述。

### 5.2 Source Record

表示一项研究及其主文、SI、metadata、DOI/标题身份、文件 hash、来源层级、来源类型、入选/排除理由和完整性状态。

来源类型必须至少区分：

- `primary_study`：可直接支撑实验观察、条件和结果；
- `review`：用于发现、背景、分类候选和领域语境，不能替代一手证据；
- `guideline`：用于方法、格式或质量规则；
- `benchmark`：用于评估结构、叙事、图表和最终质量，不进入主题证据计数。

来源分为：

- `core`：逐篇精审；
- `background`：机器处理并按规则抽查；
- `candidate`：尚未决定是否纳入；
- `excluded`：保留排除理由，防止重复发现或选择性遗忘。

标杆综述与主题 Primary Corpus 必须分离展示和计量，防止将“优秀综述如何写”混同为“主题事实由什么支撑”。

### 5.3 Source Truth Bundle

每个纳入来源建立可独立核验的 Source Truth Bundle，至少包含：

- 原始主文 PDF 和可用 SI；
- MinerU Markdown 与结构化 sidecar；
- 页面索引、`bbox`、layout 和页面渲染；
- 原始图、表、caption 及其页码/图号关系；
- 版本、文件 hash、解析器版本和解析时间；
- 身份匹配、主文/SI 配对和已知缺失。

原始 PDF/SI 是最高等级来源。Markdown、OCR、LLM 摘要或结构化抽取与原始页面冲突时，以原始页面为准，并把冲突记录为解析缺陷。

### 5.4 Parse Quality Gate

解析完成后、证据抽取前执行 Parse Quality Gate。它检查正文顺序、章节边界、图文对应、表格结构、公式/化学符号、参考文献边界和 SI 完整性，并产生按对象定位的质量状态：

- `usable`：可用于候选抽取；
- `usable_with_review`：允许抽取，但相关字段必须人工回看 PDF；
- `incomplete`：只允许使用已确认部分；
- `failed`：不得从解析文本生成科学证据，改用原始 PDF 人工 locator 或其他解析器。

Parse Quality Gate 不能只给论文级总分。表格、公式、图、正文段落可以有不同状态；局部失败只阻塞依赖对象。

### 5.5 Paper Evidence

记录单篇论文具体报告了什么，包括原文片段、页码/章节/图表 locator、实验条件、定量结果、机制证据、限制、来源版本、解析质量和人工核验状态。MinerU 或 LLM 输出只能生成候选证据，不能自动成为已验证事实。

每条证据必须标记 epistemic type：

- `experimental_observation`：论文直接报告的观察或数据；
- `author_interpretation`：原作者对观察的解释；
- `proposed_mechanism`：论文提出但未充分证明的机制；
- `review_synthesis`：综述作者基于多来源形成的判断，只能存在于已批准 Synthesis Claim 中。

系统不得把作者解释提升为实验事实，不得把推测机制写成已证实机制，也不得把 review 中的转述当作 primary study 的直接证据。

### 5.6 Synthesis Claim

记录多篇研究合起来允许综述作出的判断。至少包含：

- proposition；
- comparison axis；
- supporting evidence；
- counter-evidence 与冲突；
- applicability boundary；
- mechanism/evidence grade；
- uncertainty/confidence；
- risk class；
- human decision；
- upstream versions。

`Synthesis Claim` 不能只是 claim ID 列表。若结论只来自单篇研究，必须显式标记为 single-study，不得伪装成领域共识。

### 5.7 Section Contract

每节起草前记录该节要回答的问题、主要比较对象、预期综合判断、必须覆盖的反例/局限、证据预算，以及需要的 Source Figure 或 Synthesis Figure Placeholder。没有已批准 Section Contract，不允许生成该节正文。

### 5.8 Manuscript Claim

正文中的科学主张必须连接到 Paper Evidence 或已批准 Synthesis Claim。纯过渡和写作性语句可以无证据，但不得承载新的科学事实。

### 5.9 Source Figure 与 Synthesis Figure Placeholder

`Source Figure` 记录原论文图片、图号、页码、caption、来源、用途和关联证据。内部工作台与内部稿可直接使用原图，不检查许可；允许不改变科学内容的确定性裁切和尺寸适配，但不得改变数据、结构或机理含义。

`Synthesis Figure Placeholder` 是综合图的唯一系统产物。系统禁止自动组合、重绘、生成或补全跨论文科学图。每个占位符必须提供：

- 图要回答的科学问题和预期读者收获；
- 建议的 A/B/C/D panel 信息结构；
- 每个 panel 对应的已批准 Synthesis Claim；
- 来源论文、页码、图号、caption 和 evidence locator；
- 比较轴、必要标签、单位、边界条件和冲突证据；
- 禁止表达的过度结论和仍未解决的不确定性；
- caption 草案、目标尺寸和输出格式；
- `awaiting_human_figure`、`uploaded`、`verified` 状态。

研究者自行制作并上传最终综合图。系统只检查文件可读性、分辨率、panel/引用完整性、占位符需求覆盖和证据链接；研究者负责科学内容、视觉表达和最终批准。缺少必需综合图时可以继续编辑正文，但不能通过最终 Release。

### 5.10 Verification Decision 与 Impact Edge

所有人工批准记录对象版本、决定、理由和时间。Source、Source Truth Bundle、Parse Quality、Evidence、Synthesis Claim、Section Contract、Manuscript Claim、Source Figure 与 Synthesis Figure Placeholder 之间建立影响边；上游变化只使受影响下游对象失效。

## 6. 目标全流程

### 6.1 Review Contract / Brief

机器整理主题、提出边界与比较维度、分析标杆结构并形成 Review Contract 草案。研究者确认问题、范围、纳排标准、目标读者、来源类型、比较轴、停止条件和质量标尺。Review Contract 在工作台中以 Brief 呈现，是后续判断的稳定合同，不是自由变化的提示词。

检查点 H1：Brief 已确认。

### 6.2 Source Set

机器完成发现/导入、去重、身份匹配、主文/SI 配对、来源类型、核心/背景分层建议和 Coverage Map。标杆综述、方法指南和主题 Primary Corpus 分开管理。研究者确认代表性、关键遗漏、核心来源、背景来源和排除理由。

Coverage Map 必须展示领域分类、各分类核心来源、搜索饱和度或停止理由、已知遗漏及其影响。它不能把“下载到的论文”冒充“足够代表领域的论文”。

检查点 H2：Source Set 已确认。

### 6.3 Source Truth + Parse Quality

机器为每项纳入研究建立 Source Truth Bundle，并执行 Parse Quality Gate。研究者只处理身份歧义、缺失 SI、严重版面错误、表格/公式/化学结构风险和解析器无法可靠定位的部分。

解析质量必须在证据抽取前可见。机器可以对 `usable` 内容批量处理；`usable_with_review` 的高风险字段必须回看原始页面；`incomplete` 和 `failed` 不得被缓存或 LLM 摘要掩盖。

该步骤是 Source Set 与 Evidence + Synthesis 之间的内部质量子流程，不新增第六个用户阶段或新的全局人工门禁；只有异常对象才要求研究者处理。

### 6.4 Evidence + Synthesis

机器生成逐篇候选证据、epistemic type、条件标准化、比较矩阵、冲突提示、机制证据等级和候选 Synthesis Claims。研究者逐篇精审核心论文，抽查背景论文，确认高风险主张，并决定分类体系、比较逻辑、反例、边界和文章主线。

比较必须遵循 Review Contract 中预先批准的 Comparison Protocol。协议至少记录比较对象、比较轴、单位/归一化规则、缺失值处理、不可比条件、反例纳入规则和结论强度。系统不得事后只选择支持预期结论的指标。

独立的 Risk Packet 不再作为全局阶段。风险是 Evidence 与 Synthesis Claim 的属性，并在同一工作区集中处理。

检查点 H3：Evidence、Comparison Protocol、Synthesis Claims、整体 outline、Section Contracts 与 Synthesis Figure Placeholders 已确认。

### 6.5 Manuscript Loop

AI 每次只依据已批准 Section Contract、Paper Evidence 和 Synthesis Claims 起草一节。研究者逐节通读、修改并批准，决定因果措辞、机制强度、批判性判断、图表和过渡。

证据不足或论证失败时，只退回该节关联的 Evidence、Synthesis Claim 或 Section Contract；不得重启整个项目。

高风险人工编辑升级不是可选提醒。凡触发高风险规则，AI 草稿必须进入 `needs_human_edit`，研究者直接修改并批准后才能继续。综合图位置只显示占位符和制图 brief；系统不得临时生成图片填空。

### 6.6 Release

机器完成交叉引用、数字、单位、图号、参考文献、术语、覆盖和失效状态检查，检查必需综合图已由研究者上传并完成来源关联，合并正文并导出内部 DOCX/PDF。研究者验收综合图和全文科学内容，并确认未解决的不确定性。

检查点 H4：全文与导出物已验收。

## 7. 人工与自动化边界

机器默认执行：

- 来源导入、匹配、去重和完整性检查；
- Source Truth Bundle 组装、PDF/MinerU 解析、段落/表格/原图定位和 Parse Quality 候选判定；
- 候选证据抽取、术语与条件标准化；
- 比较矩阵、冲突提示、覆盖统计和候选分类；
- Synthesis Figure Placeholder 与人工制图 brief；
- 基于批准输入按节起草；
- 确定性引用、数字、单位、图号、格式和导出检查。

研究者必须决定：

- 研究问题、范围、纳排标准和标杆；
- 哪些论文具有代表性；
- 核心论文证据和全部高风险主张是否成立；
- 机制证据属于观察、支持、强支持还是已证实；
- 论文冲突、局限、知识空白和领域结论如何解释；
- Comparison Protocol、文章主线、措辞强度和逐节正文；
- 所有综合图的科学内容、绘制、上传和最终批准；
- 全文科学验收。

以下情况自动升级为人工处理：来源身份歧义、主文/SI 不一致、解析残缺、表格/公式/化学符号不可靠、定量/因果/机制/安全/优越性/否定性主张、研究间冲突、单篇研究泛化、跨论文串线或模型超出原文。升级后状态必须是 `needs_human_edit` 或 `needs_review`；LLM judge 不得解除升级。

## 8. 运行状态与恢复

### 8.1 状态模型

所有关键对象统一使用：

- `proposed`；
- `needs_review`；
- `needs_human_edit`；
- `approved`；
- `stale`；
- `blocked`。

项目阶段仅是对象状态的只读投影：Brief、Source Set、Evidence + Synthesis、Manuscript、Release。未知状态必须显示 `needs_attention` 与真实原因，禁止映射为第一阶段。

### 8.2 持久状态 + next-action

每个自动动作是短时、幂等、可恢复任务。任务开始前完成确定性 preflight，完成后原子写回。`next-action` 根据持久对象返回唯一建议动作、阻塞原因和可安全重试信息。

dashboard、QoderWork 回合或机器可以任意关闭。重新打开后从持久状态继续，不依赖 12–24 小时 watcher、后台 Bash 或进程组存活。

### 8.3 ZIP/PDF 导入

ZIP 外层名称和内部 PDF 名称均可任意。流程为：

1. 选择 ZIP；
2. 预检成员、格式、重复、DOI/标题、主文/SI 和歧义；
3. 用户点击“确认导入”；
4. 原子写入 Source Set；
5. 只有歧义项要求人工选择。

选择文件不能自动触发导入。用户无需重命名为 `source_bundle.zip`，也无需准备 manifest 或映射表。

### 8.4 失败处理

- 身份歧义：不猜测，显示候选项；
- 主文/SI 缺失：标记影响，只阻塞依赖内容；
- 解析失败：保留 Source Truth Bundle，允许换解析器或人工 PDF locator；失败字段不得从摘要或其他论文补齐；
- 综合图缺失：保留占位符和正文编辑能力，Release 明确阻塞在 `awaiting_human_figure`；
- 上游变化：仅相关对象变为 `stale`；
- 模型/API 失败：保留已完成结果，有限重试并给出一个恢复动作；
- 状态/schema 不支持：preflight 失败，不进入模型调用。

## 9. Credits 与执行成本

1. 执行前显示任务、预计调用数、缓存命中与需要人工处理的项；
2. 路径、schema、CLI、输入和状态由确定性 preflight 验证；
3. 同一失败不得无界重试；
4. LLM 输出按输入版本、提示版本和模型配置缓存；
5. QoderWork 只调用维护好的命令和语义角色，不猜 CLI、不手造 receipt、不临时修 schema；
6. 确定性任务与模型任务分开计量，失败报告必须显示已消耗预算和剩余动作。

## 10. 现有步骤处置

### 10.1 保留并强化

范围确认、发现与导入、PDF/MinerU、metadata、去重、证据抽取、比较矩阵、按节起草、引用检查和 DOCX/PDF 导出。MinerU 被强化为 Source Truth Bundle 内的索引层，并新增 Parse Quality Gate。

### 10.2 合并

- library audit、discovery、下载/ZIP 和 metadata 合并进 Source Set；
- matrix、outline、blueprint 和 risk review 合并进 Evidence + Synthesis；
- merge、polish、final audit 和 export 作为 Release Workspace 内部任务。

### 10.3 弱化

- manifest、receipt、hash 和 lineage 保留为内部 provenance 与缓存失效机制，不面向用户；
- 原论文 Source Figure 提取保留为内部稿辅助；所有综合图制作改为研究者职责；
- LLM judge 只提供建议，不得批准科学正确性；
- 阶段条只作导航，不作真源。
- 100 分量表只作内部回归和差距定位，不解释为投稿质量、期刊接受概率或科学正确证书。

### 10.4 删除

- 长时间 watcher、shell 轮询和回合内守候；
- 文件存在或 ID 存在即放行；
- `paper_body_read=not_read` 或 `references_checked=false` 仍 APPROVE；
- agent 手工修 manifest、receipt、schema、lineage 和路径；
- 强制用户使用固定 ZIP 名称；
- AI 自动生成、重绘、补画或组合科学综合图。

### 10.5 新增

Source Truth Bundle、Parse Quality Gate、来源类型、epistemic type、Comparison Protocol、Coverage Map、Synthesis Claim、Synthesis Studio、Synthesis Figure Placeholder、Section Contract、Impact Graph、Editorial Challenge、Parse/Evidence/Synthesis/Figure Placeholder Gold Set 和永久负向回归集。

## 11. 科学验收

### 11.1 100 分量表

| 维度 | 分值 |
| --- | ---: |
| 范围与问题价值 | 10 |
| Source Set 覆盖 | 15 |
| 证据忠实度 | 20 |
| 综合与批判性 | 20 |
| 结构与叙事 | 15 |
| 图表的信息价值 | 10 |
| 引用与可追溯性 | 10 |

内部标准稿可暂以 80/100 且无 Hard Fail 作为项目回归门槛，但该阈值必须用标杆与失败稿校准后才可稳定使用。分数只用于回归、差距定位和人工评审，不代表科学正确性、期刊接受概率或“完美综述”。人工验收可以推翻总分，任何 Hard Fail 都不能由高分抵消。

### 11.2 Hard Fail

出现任一项立即拒绝 Release：

1. 正文主张绑定错误论文、图或参考文献；
2. 支撑正文/SI 未读，或参考文献未检查仍批准；
3. 高风险主张未人工确认；
4. 上游变化后沿用失效批准；
5. 补造条件、把假设写成事实或把单篇结果泛化为共识；
6. 磁盘、API、dashboard 和 release verdict 对完成状态不一致；
7. 正文存在无来源的科学主张或引用不蕴含主张。
8. 必需综合图仍为占位符、由系统自动生成/组合，或用户上传图未完成科学验收。

### 11.3 Editorial Challenge

生成正文的同一判断链不得自我批准。Release 前必须进行独立挑战，至少检查：核心来源遗漏、反例与冲突、过度概括、分类偏差、段落是否只在罗列论文、人工综合图是否承担既定科学任务、非专家可读性和结论是否回答 Review Contract。

独立挑战可以由第二模型或人工执行，但最终决定属于研究者。

## 12. 测试策略

1. 确定性单元测试：状态投影、schema、hash、locator、失效传播、引用和 release 条件；
2. 导入/恢复集成测试：任意 ZIP 名、确认导入、重复 PDF、歧义匹配、kill/restart/resume；
3. Parse Gold Set：人工标注双栏顺序、章节、化学式/符号、表格单元格、图-caption-page 关系和 SI 边界，分别评估解析对象，不用单一论文级分数掩盖局部失败；
4. Evidence Gold Set：人工标注正确证据、epistemic type、实验条件、机制等级与错误诱饵；
5. Synthesis Gold Set：评估预先定义的 Comparison Protocol、多论文比较、反证、边界和 Review-level claims，而非只测摘要相似度；
6. Figure Placeholder Gold Set：检查科学问题、panel brief、Synthesis Claim、来源 locator、边界和 caption 是否足以让研究者独立制图；不评价机器生成图片；
7. 端到端负例：当前三篇失败稿中的来源串线、页码错误、催化剂泛化、未读正文、未查引用、自动综合图和无价值图必须全部触发 Hard Fail；
8. 人工标杆评审：使用 `标准.zip` 的分层标杆和 100 分量表逐节评估；
9. 成本回归：固定语料下记录模型调用数、缓存命中、失败重试和总 credits；
10. UI 回归：未知状态不得显示为“确认研究范围”，磁盘/API/dashboard/release 状态一致；综合图必须显示 `awaiting_human_figure`、上传和验收状态。

## 13. 迁移与实现边界

本设计是产品级总设计，不应作为一次大改直接实施。实现必须拆成四个可独立验收的子项目，前一项稳定后再进入下一项：

1. **可靠运行底座**：删除 watcher 依赖，修复状态投影和 release 真源，加入 `next-action`、确定性 preflight、任意 ZIP 名预检与确认导入；
2. **Source Truth + Evidence 真源**：统一来源类型、Source Record、Source Truth Bundle、主文/SI 完整性、Parse Quality Gate、epistemic type、Paper Evidence、人工决定和局部失效传播，并用 adapter 读取现有项目产物；
3. **Synthesis Workspace**：加入 Comparison Protocol、Coverage Map、Synthesis Claim、候选分类、冲突/反证、Section Contract 和 Synthesis Figure Placeholder；不得实现自动综合图生成、重绘或组合；
4. **Manuscript + Release 质量闭环**：加入高风险人工编辑升级、逐节批准、人工综合图上传/验收、Editorial Challenge、Hard Fail、Parse/Evidence/Synthesis/Figure Placeholder gold sets、成本回归和内部标准稿验收。

每个子项目必须有自己的实现规格、迁移方案、测试和回滚边界。迁移期间不得批量重写现有项目目录；优先用只读 adapter 解释旧产物，只有用户确认升级具体项目时才写入新状态。旧工作流在新子项目未通过验收前保持可回退，但不得继续宣称已知假阳性的 `APPROVE` 代表科学正确。

## 14. 完成定义

实现完成必须同时满足：

1. 五阶段工作流和四个主检查点均由持久对象状态驱动；
2. Source Truth Bundle、Parse Quality Gate、`Synthesis Claim`、Comparison Protocol、Coverage Map、Section Contract 与影响失效可实际使用；
3. ZIP 经预检和显式确认后导入，名称任意；
4. dashboard/QoderWork 被杀死后可无损恢复；
5. 原论文 Source Figure 可用于内部稿且来源完全可追溯；综合图只能由系统生成占位符并由研究者制作、上传和批准，自动生成、重绘或组合综合图的路径不存在；
6. 当前已知失败稿稳定被 Hard Fail 拒绝；
7. 新生成内部稿达到经标杆校准的内部回归门槛、无 Hard Fail，并通过研究者最终验收；
8. `make smoke` 与 `make quality-check` 通过，并有新鲜的端到端恢复、负例和成本报告。
