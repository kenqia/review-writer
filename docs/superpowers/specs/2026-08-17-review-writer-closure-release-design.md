# Review Writer Closure Release 设计

- 日期：2026-08-17
- 决策状态：PM APPROVED
- 路线：D / Closure Release
- 时间盒：自 Leader 接收正式实施指令起最多 48 小时

## 1. 决策

Review Writer 不再扩建当前科研工作台，也不在本轮实施 Generator Mode 重构。

本轮保留现有完整产品面，只做一次有界封版：从 fresh 空白项目走完整条公开科研交付主链，修复阻断交付、损坏数据或造成危险科学误导的 P0，由产品经理亲自体验全部现有公开功能，然后停止开发。

此前讨论的 C1（Generator + Evidence Lens）保留为未来可能的产品方向；不删除相关设计结论，但本轮不实施、不迁移旧项目、不隐藏或重写现有工作台。

## 2. 封版产物与命名边界

若核心主链成功且完成人工走查，最多命名为：

> **v1 Local Research Workbench Preview**

允许陈述：

- 在冻结的本机环境、代码基线和真实语料上完成过一次 fresh 公开主链；
- 当前公开功能经过一次人工走查，并分别记录为 PASS、LIMITED 或 BLOCKED；
- 指定交付物能够保存、重新打开和导出；
- 已知限制被明确保留。

不得陈述：

- commercial production-ready、GA 或稳定商业产品；
- 科学正确、专家验证、同行评审或可直接投稿；
- 对任意主题、任意 PDF、任意规模具有普遍可靠性；
- 所有历史、并发、恢复与故障路径均已证明；
- Gold、PROMOTE、B2、scientific validity 或普遍 HUMAN_ACCEPTANCE 已建立。

若核心主链仍被深层 blocker 阻断，只能封存为：

> **Local Research Workbench Development Snapshot**

## 3. 冻结范围

Leader 启动 Closure Release 时一次性冻结：

- 当前代码与 dirty/untracked baseline；
- 本机运行环境与公开入口；
- 一个 fresh 空白项目和本轮真实测试语料；
- 当前公开 UI/API 功能清单；
- 唯一核心主链、预期 Markdown/DOCX 交付物和人工走查范围。

代码库中存在但没有公开入口的实验模块不进入“全部功能”范围。冻结后不得新增产品功能、角色、页面、状态机、迁移、生产依赖或验收层。

不删除、迁移或改写旧项目，不清理 Q6、Gold、论文、refs、worktrees 或既有 Dashboard 数据；不 stage、commit、push、PROMOTE 或声明 B2。

## 4. 唯一核心主链

必须从公开入口、fresh 空白项目开始，不得使用预制成品、隐藏脚本或手工修改 JSON 代替用户动作：

1. 创建空白项目；
2. 设置 Topic 与 Review Questions；
3. 添加真实 PDF，完成 Source / Parse / Source Truth；
4. 建立 Evidence，并体验 Research / Matrix / Gap；
5. 生成并编辑 Draft；
6. 体验 Figures / attribution；
7. 体验 Quality；
8. 生成同一稿的 Markdown 与 DOCX；
9. Download，并走一次 Outdated / Regenerate；
10. 保存、关闭、冷启动并 Resume 到同一 authoritative current。

核心主链通过要求：

- 最终 Markdown 与 DOCX 均可打开且来自同一稿件/版本；
- 保存、失败、重试、重新生成和重启不会损坏旧 current；
- stale、corrupt、source/version/hash 不一致时 fail-closed；
- 重要化学结论能回到来源与 locator，证据不足或冲突不被冒充为 CONFIRMED；
- 全程只使用公开 UI/API 完成用户动作。

## 5. “体验全部功能”的含义

产品经理对冻结时存在的全部公开功能做一次代表性人工走查。每项只允许记录：

- PASS：本次场景可用；
- LIMITED：可用但有明确限制；
- BLOCKED：本次未闭合或不可安全使用。

人工走查是能力盘点，不是“全部功能必须修到全绿”的门禁。LIMITED/BLOCKED 不自动创建下一轮开发任务；只有符合第 6 节的 P0 才能进入本轮修复。

## 6. 唯一允许修复的三类 P0

### P0-A：核心交付阻断

fresh 空白项目无法到达可读正文、同稿 Markdown/DOCX，或无法保存、关闭、重新打开继续使用。

### P0-B：数据与版本安全

可能覆盖用户编辑、写错项目、丢失稿件、产生错误 current、混写不同版本、用半成品冒充成功，或让失败操作损坏旧结果。

### P0-C：危险科学归属

重要化学结论引用错误论文/locator，无证据的精确结论被显示为有支持，或 AI_PROVISIONAL、BLOCKED、GAP 被错误升级为 CONFIRMED。

以下均不是本轮必修：视觉润色、交互一致性、Matrix/Figure/Version 的非主链增强、benchmark 分数、历史比较体验、Branch/rollback 完善、性能优化、P1/P2 架构债和代码整理。

## 7. Minimum Viable Governance 执行循环

默认循环只有：

> 主链 first failure → 同一个 Luna/max Implementer 最小修复 → focused test → 真实公开 UI/API 重跑 → 必要时继续修同一 first failure → 一个不同 Luna/max Verifier 做一次 fresh verification

约 90% 时间用于真实产品运行、修补和重测；治理只保护唯一 Source/Evidence、唯一 current/version、stale 零写、Release 来源/版本/hash 绑定与一次独立验证。

禁止为本轮新增 gate、receipt、lease、marker、packet、第二套状态机或额外状态文档。默认不开 Explorer/合同冻结包；只有 first failure 无法定位现有 owner/producer 时，才允许一次短时只读定位，随后立即回到同一用户切片。

Leader 只做编排。Implementer 与独立 Verifier 必须是不同的 Codex App 独立对话，显式使用 `gpt-5.6-luna`、`thinking=max`，并核验 `danger-full-access`、`approval_policy=never`、filesystem unrestricted。禁止 Terra、collaboration 子智能体和 `spawn_agent`。

## 8. 深层 blocker 与停止规则

出现以下任一情况，不再扩建，直接记录为深层 blocker：

- 修复需要新增状态机、第二个 current owner、持久化迁移或大型跨模块重构；
- 修复需要新增生产依赖、外部写、发布、生产操作或不可逆操作；
- 同一 P0 经过一次有界最小修复后仍不能稳定重现并通过；
- 已发现超过三类需要独立处理的 P0；
- 剩余时间不足以完成 focused test、公开主链重跑和一次独立验证。

满足以下任一条件立即停止开发：

1. 自正式启动起达到 48 小时；
2. 核心主链通过、独立 fresh verification 通过且产品经理完成人工走查；
3. 出现不能在本时间盒内最小修复的深层 blocker。

成功也停止，失败也停止；不存在“再补最后一个问题”的第三种结果。

## 9. 验收分层

- **Engineering**：focused unit/integration、stale、zero-write、hash/currentness、保存与导出测试。
- **Independent Quality**：实现完成后由不同 Luna/max 对话做一次 fresh verification。
- **Product Use**：从公开 UI/API 完成 frozen 主链，获得可打开的同稿 Markdown/DOCX。
- **PUBLIC_E2E**：fresh 空白项目从创建到冷启动恢复，全程不依赖隐藏操作。
- **HUMAN_ACCEPTANCE**：仅在产品经理实际操作并明确确认后建立；未体验的功能不得算接受。
- **scientific validity**：独立的人类/研究判断，不由上述任何工程或产品测试自动升级。

## 10. 两个合法终态

### Closure PASS

- 核心主链与独立验证通过；
- 产品经理完成全部公开功能走查；
- 发布名称为 `v1 Local Research Workbench Preview`；
- 汇总 PASS / LIMITED / BLOCKED 与已知限制；
- 停止开发，进入真实使用期。

### Closure PARTIAL

- 时间盒结束或遇到深层 blocker；
- 封存为 `Local Research Workbench Development Snapshot`；
- 区分已通过、受限、阻断和未测试能力；
- 不把 PARTIAL 冒充端到端完成；
- 同样停止开发。

## 11. 明确非目标

- 不在本轮实施 C1 Generator Mode；
- 不重写或简化旧工作台架构；
- 不追求商业发布、部署、多用户、通用插件或投稿工作流；
- 不以修完 canonical 23 项或全部 P1/P2 作为停止条件；
- 不因为沉没成本延长时间盒。
