# review-writer 收敛说明 — 2026-08-03

状态：`PROPOSED_CONVERGENCE_FREEZE`

本说明记录项目暂停旧路线后的第一次大收敛边界。它不是发布结论，也不授权
联网、调用 provider、修改 corpus、发布内容或作出科学决定。

## 1. 唯一主线

项目现在只沿着一条产品主线前进：

> 面向化学研究者的、案例中立、离线优先的项目契约；它保护来源、证据、
> 用户决定、检查点状态和不可变的产物链路，让用户能知道结果从哪里来、
> 哪些地方仍需要自己判断。

当前本地主线基线为：

```text
ab3e76b7d040d6bb1e3178778d569e772aa96b8f
```

本地 `main` 已快进到已经存在的本地 `origin/main`，没有联网和远端写入。

当前唯一产品问题是 M0/PR A 验收问题：同一个最小、案例中立的本地项目契约，
能否同时验证合成的非 allene 项目和冻结的 Case 01，并防止可编辑配置污染
既有证据、用户决定、快照和历史发布产物。

用户能得到的改变是：项目先把“输入是什么、哪些证据可信、哪些结论能写进
综述、配置变化影响什么”说清楚，再考虑更复杂的自动化。

## 2. 保留为核心

以下内容继续保留，直到另有明确审查结论：

- `docs/product/PRODUCT_NORTH_STAR.md`
- `docs/product/PRODUCT_ROADMAP.md`
- `docs/product/CHECKPOINT_CONTRACT.md`
- `docs/decisions/ADR-001-chemistry-first-evidence-governed-workbench.md`
- `review_writer/project/` 与 `schemas/project/`
- M0 fixture 和测试覆盖的离线校验、路径安全、快照、发布闭包和证据边界
- 冻结的 Case 01 adapter 与合成非 allene 验收 fixture
- 唯一公开入口及其 Owner/Reviewer/安全约束

这些资产对用户的价值是减少“同一个项目为什么得到不同结果”的不确定性。
保留它们不等于开始建设通用 workflow engine。

## 3. 冻结并停车

以下内容只作为历史证据或未来候选，不再作为当前开发线：

- Phase 8A/8B adjudication 与 grounded revision 分支
- Bailian、RAG、provider qualification 和在线执行路径
- QoderWork 迁移实验与 native workbench 分支
- 旧 E2R、dashboard、resolved-SMILES、chemical-completion 和 release 修复波次
- deliverable-first 的 a1/a2/a3 外部候选与 SI migration 结果

它们不能成为 M0 权威，也不能因为已有文件或旧报告就对用户宣称 READY。

冻结期间不启动新的综述运行、新 provider、新主题专用生产代码、DOCX/PDF
导出或 SI binding 修复。

## 4. 清理边界

清理按可恢复性分阶段进行：

1. 只移除已经确认没有未跟踪文件和 ignored 文件的干净 worktree；分支引用保留。
2. 对仍有 ignored runtime/data 的干净 worktree，先生成只读清单，再决定是否移除。
3. dirty worktree 和外部候选/来源目录在记录 Owner、hash 和恢复价值前不得删除。
4. 外部重复项目必须先完成文件/hash inventory，确定 canonical copy 和恢复位置后才能处理。
5. 未合并 branch/commit 不因为“没有合并”就删除；branch 清理需要单独的 archive manifest
   和精确目标清单。

第一轮已移除 6 个没有未跟踪数据的干净 worktree；它们的分支和 commit 均保留。

## 5. 报告规则

以后每份报告先用用户语言说明：

- 用户遇到的问题；
- 本次改变给用户带来的结果；
- 用户如何使用；
- 仍然会被什么阻断；
- 用户下一步需要做什么。

开发者过程、代理数量、内部抽象、branch、worktree、测试数量和 hash 只能作为
验证证据，不能替代用户结果。若没有直接用户可见变化，必须明确写出“无直接
用户可见变化”及保留它的理由。新写文档默认使用中文。

## 6. 停止线

收敛边界被接受前：

- 不为旧路线运行测试或调用模型/API；
- 不做远端写入、push、deploy、发布或 provider 调用；
- 不读 PDF，不修改外部项目；
- 不清理、reset、覆盖、重命名或移动 dirty worktree；
- 不在精确、先核验的目标清单之外删除任何内容。

下一项不可逆动作不是开发，而是：在记录恢复证据后，明确选择哪些剩余
worktree 和外部目录可以归档或删除。
