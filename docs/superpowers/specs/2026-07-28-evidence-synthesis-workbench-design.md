# Review Writer 证据与综合判断工作台设计

日期：2026-07-28
状态：设计已批准，待用户审阅书面规格

## 1. 结论

Review Writer 应从线性阶段门禁系统重构为“证据 + 综合判断工作台”。系统的唯一真源不是阶段名称、文件存在、hash 或 claim ID，而是经过验证的以下关系：

```text
Source → Paper Evidence → Synthesis Claim → Manuscript Argument
```

目标交付物是内部使用、科学质量接近投稿初稿的完整综述，不是投稿包。机器负责规模化处理、格式、一致性与可追溯性；研究者负责范围、代表性、证据强度、跨研究综合、学术措辞和最终验收。

证据中心只能解决“某句话是否正确来自某篇论文”。达到标杆综述还必须解决“多篇论文合起来允许我们得出什么新判断”。因此 `Synthesis Claim` 必须成为与来源证据同等重要的一等对象。

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

### 3.2 非目标

1. 不承诺自动达到或被顶级期刊接收；
2. 不生成可直接投稿的合规包，不处理图片许可或投稿权限；
3. 不让 AI 自动生成化学结构、机理路径、实验装置或科学数据图；
4. 不建设云端语料库、账户系统、第二套 dashboard、通用工作流引擎或远端部署；
5. 不用单一总分、LLM judge 或工程 smoke 代替研究者科学验收。

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

## 5. 核心数据模型

### 5.1 Review Brief

记录研究问题、目标读者、时间边界、纳排标准、比较维度、目标篇幅、标杆论文和质量门槛。Brief 必须说明综述不覆盖什么，以及为什么此时值得综述。

### 5.2 Source Record

表示一项研究及其主文、SI、metadata、DOI/标题身份、文件 hash、来源层级、入选/排除理由和完整性状态。

来源分为：

- `core`：逐篇精审；
- `background`：机器处理并按规则抽查；
- `candidate`：尚未决定是否纳入；
- `excluded`：保留排除理由，防止重复发现或选择性遗忘。

### 5.3 Paper Evidence

记录单篇论文具体报告了什么，包括原文片段、页码/章节/图表 locator、实验条件、定量结果、机制证据、限制、来源版本和人工核验状态。MinerU 或 LLM 输出只能生成候选证据，不能自动成为已验证事实。

### 5.4 Synthesis Claim

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

### 5.5 Section Contract

每节起草前记录该节要回答的问题、主要比较对象、预期综合判断、必须覆盖的反例/局限、图表职责和证据预算。没有已批准 Section Contract，不允许生成该节正文。

### 5.6 Manuscript Claim

正文中的科学主张必须连接到 Paper Evidence 或已批准 Synthesis Claim。纯过渡和写作性语句可以无证据，但不得承载新的科学事实。

### 5.7 Figure Item

记录原论文图片、图号、页码、caption、来源、用途、裁切/组合历史和关联证据。内部工作台与内部稿可直接使用原图，不检查许可。

禁止 AI 生成或擅自补画科学内容。允许不改变科学含义的裁切、排版、标注和原图 panel 组合。综合性图板由研究者定义表达目标和组成；系统负责来源管理与版面辅助。

### 5.8 Verification Decision 与 Impact Edge

所有人工批准记录对象版本、决定、理由和时间。Source、Evidence、Synthesis Claim、Section Contract、Manuscript Claim 与 Figure Item 之间建立影响边；上游变化只使受影响下游对象失效。

## 6. 目标全流程

### 6.1 Brief

机器整理主题、提出边界与比较维度、分析标杆结构并形成 Brief 草案。研究者确认问题、范围、纳排标准、目标读者和质量标尺。

检查点 H1：Brief 已确认。

### 6.2 Source Set

机器完成发现/导入、去重、身份匹配、主文/SI 配对、核心/背景分层建议和 Coverage Map。研究者确认代表性、关键遗漏、核心来源、背景来源和排除理由。

Coverage Map 必须展示领域分类、各分类核心来源、搜索饱和度或停止理由、已知遗漏及其影响。它不能把“下载到的论文”冒充“足够代表领域的论文”。

检查点 H2：Source Set 已确认。

### 6.3 Evidence + Synthesis

机器生成逐篇候选证据、条件标准化、比较矩阵、冲突提示、机制证据等级和候选 Synthesis Claims。研究者逐篇精审核心论文，抽查背景论文，确认高风险主张，并决定分类体系、比较逻辑、反例、边界和文章主线。

独立的 Risk Packet 不再作为全局阶段。风险是 Evidence 与 Synthesis Claim 的属性，并在同一工作区集中处理。

检查点 H3：Evidence、Synthesis Claims、整体 outline 与 Section Contracts 已确认。

### 6.4 Manuscript Loop

AI 每次只依据已批准 Section Contract、Paper Evidence 和 Synthesis Claims 起草一节。研究者逐节通读、修改并批准，决定因果措辞、机制强度、批判性判断、图表和过渡。

证据不足或论证失败时，只退回该节关联的 Evidence、Synthesis Claim 或 Section Contract；不得重启整个项目。

### 6.5 Release

机器完成交叉引用、数字、单位、图号、参考文献、术语、覆盖和失效状态检查，合并正文并导出内部 DOCX/PDF。研究者全文科学验收并确认未解决的不确定性。

检查点 H4：全文与导出物已验收。

## 7. 人工与自动化边界

机器默认执行：

- 来源导入、匹配、去重和完整性检查；
- PDF/MinerU 解析、段落/表格/原图定位；
- 候选证据抽取、术语与条件标准化；
- 比较矩阵、冲突提示、覆盖统计和候选分类；
- 基于批准输入按节起草；
- 确定性引用、数字、单位、图号、格式和导出检查。

研究者必须决定：

- 研究问题、范围、纳排标准和标杆；
- 哪些论文具有代表性；
- 核心论文证据和全部高风险主张是否成立；
- 机制证据属于观察、支持、强支持还是已证实；
- 论文冲突、局限、知识空白和领域结论如何解释；
- 文章主线、措辞强度、逐节正文和最终图表；
- 全文科学验收。

以下情况自动升级为人工处理：来源身份歧义、主文/SI 不一致、解析残缺、定量/因果/机制/安全/优越性/否定性主张、研究间冲突、单篇研究泛化、跨论文串线或模型超出原文。

## 8. 运行状态与恢复

### 8.1 状态模型

所有关键对象统一使用：

- `proposed`；
- `needs_review`；
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
- 解析失败：保留 PDF，允许换解析器或人工 locator；
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

范围确认、发现与导入、PDF/MinerU、metadata、去重、证据抽取、比较矩阵、按节起草、引用检查和 DOCX/PDF 导出。

### 10.2 合并

- library audit、discovery、下载/ZIP 和 metadata 合并进 Source Set；
- matrix、outline、blueprint 和 risk review 合并进 Evidence + Synthesis；
- merge、polish、final audit 和 export 作为 Release Workspace 内部任务。

### 10.3 弱化

- manifest、receipt、hash 和 lineage 保留为内部 provenance 与缓存失效机制，不面向用户；
- figure redraw 改为人工选择的可选工具；
- LLM judge 只提供建议，不得批准科学正确性；
- 阶段条只作导航，不作真源。

### 10.4 删除

- 长时间 watcher、shell 轮询和回合内守候；
- 文件存在或 ID 存在即放行；
- `paper_body_read=not_read` 或 `references_checked=false` 仍 APPROVE；
- agent 手工修 manifest、receipt、schema、lineage 和路径；
- 强制用户使用固定 ZIP 名称；
- AI 自动生成科学图片。

### 10.5 新增

Coverage Map、Synthesis Claim、Synthesis Studio、Figure Board、Section Contract、Impact Graph、Editorial Challenge、Evidence/Synthesis Gold Set 和永久负向回归集。

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

内部标准稿建议门槛为 80/100，且无 Hard Fail。分数用于回归、差距定位和人工评审，不代表期刊接受概率。

### 11.2 Hard Fail

出现任一项立即拒绝 Release：

1. 正文主张绑定错误论文、图或参考文献；
2. 支撑正文/SI 未读，或参考文献未检查仍批准；
3. 高风险主张未人工确认；
4. 上游变化后沿用失效批准；
5. 补造条件、把假设写成事实或把单篇结果泛化为共识；
6. 磁盘、API、dashboard 和 release verdict 对完成状态不一致；
7. 正文存在无来源的科学主张或引用不蕴含主张。

### 11.3 Editorial Challenge

生成正文的同一判断链不得自我批准。Release 前必须进行独立挑战，至少检查：核心来源遗漏、反例与冲突、过度概括、分类偏差、段落是否只在罗列论文、图表是否承担科学任务、非专家可读性和结论是否回答 Brief。

独立挑战可以由第二模型或人工执行，但最终决定属于研究者。

## 12. 测试策略

1. 确定性单元测试：状态投影、schema、hash、locator、失效传播、引用和 release 条件；
2. 导入/恢复集成测试：任意 ZIP 名、确认导入、重复 PDF、歧义匹配、kill/restart/resume；
3. Evidence Gold Set：人工标注正确证据、实验条件、机制等级与错误诱饵；
4. Synthesis Gold Set：评估多论文比较、反证、边界和 Review-level claims，而非只测摘要相似度；
5. 端到端负例：当前三篇失败稿中的来源串线、页码错误、催化剂泛化、未读正文、未查引用和无价值图必须全部触发 Hard Fail；
6. 人工标杆评审：使用 `标准.zip` 的分层标杆和 100 分量表逐节评估；
7. 成本回归：固定语料下记录模型调用数、缓存命中、失败重试和总 credits；
8. UI 回归：未知状态不得显示为“确认研究范围”，磁盘/API/dashboard/release 状态一致。

## 13. 迁移与实现边界

本设计是产品级总设计，不应作为一次大改直接实施。实现必须拆成四个可独立验收的子项目，前一项稳定后再进入下一项：

1. **可靠运行底座**：删除 watcher 依赖，修复状态投影和 release 真源，加入 `next-action`、确定性 preflight、任意 ZIP 名预检与确认导入；
2. **Source + Evidence 真源**：统一 Source Record、主文/SI 完整性、Paper Evidence、人工决定和局部失效传播，并用 adapter 读取现有项目产物；
3. **Synthesis Workspace**：加入 Coverage Map、Synthesis Claim、候选分类、冲突/反证、Section Contract 和 Figure Board；
4. **Manuscript + Release 质量闭环**：逐节批准、Editorial Challenge、Hard Fail、正反 gold sets、成本回归和内部标准稿验收。

每个子项目必须有自己的实现规格、迁移方案、测试和回滚边界。迁移期间不得批量重写现有项目目录；优先用只读 adapter 解释旧产物，只有用户确认升级具体项目时才写入新状态。旧工作流在新子项目未通过验收前保持可回退，但不得继续宣称已知假阳性的 `APPROVE` 代表科学正确。

## 14. 完成定义

实现完成必须同时满足：

1. 五阶段工作流和四个主检查点均由持久对象状态驱动；
2. `Synthesis Claim`、Coverage Map、Section Contract 与影响失效可实际使用；
3. ZIP 经预检和显式确认后导入，名称任意；
4. dashboard/QoderWork 被杀死后可无损恢复；
5. 原论文图片可用于内部稿，来源完全可追溯，AI 科学生图不在主流程；
6. 当前已知失败稿稳定被 Hard Fail 拒绝；
7. 新生成内部稿达到 80/100 且通过研究者最终验收；
8. `make smoke` 与 `make quality-check` 通过，并有新鲜的端到端恢复、负例和成本报告。
