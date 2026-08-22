# 2026-08-04 无人值守并行执行报告

## 一句话结论

本次约八小时窗口完成了附件方案的文档固化、两个最小垂直切片的 Owner 实现、两轮独立修复和多轮全新只读审查；没有把未经 ACCEPT 的候选集成到主集成分支，也没有宣称 READY、CONFIRMED、Gold 或真实 12 小时运行成功。

当前仍是 HOLD，原因是 readiness 和 Artifact Manifest 两条链都还有 fresh Reviewer 发现的 P1 fail-open/误阻断问题。按照项目约束，两个 lane 已达到两轮 bounded repair 上限，暂停时没有继续递归派发第三轮。

## 1. 执行边界与输入

- 附件原文：`/mnt/c/Users/26960/.codex/attachments/ff75ecc4-73f8-4c26-a0b6-b2cbe8957363/pasted-text.txt`
- 附件大小：16,465 bytes，376 行。
- 附件 SHA-256：`5074906bda66d9fde5c8ff6ad0cbec2b82dc051bb4bae6d5ef6d60d747fca3ab`。
- 并行会话模型：按要求使用 `gpt-5.6-luna`，推理强度 `max`；Reviewer 全程只读。
- 权威集成 worktree：`/home/kenqia/my_folder/review-writer/.worktrees/overnight-integration`。
- 集成分支：`codex/overnight-integration`。
- 暂停时集成 HEAD：`0a88e5221605cd60a0c51e91a6ae9f81385e6888`。
- 当前 authority manifest：8/8 校验通过。

所有候选都从 `0a88e522` 分叉，未直接写入主工作树或集成 worktree。主工作树暂停时仍为 `main@1aba27a`，仅保留原有用户未跟踪目录 `docs/superpowers/`。

## 2. 实际完成的工作

### 2.1 附件方案与文档垂直切片

已完成附件的本地固化和哈希核验，并生成了 evidence-first vertical slice 的产品说明与执行计划：

- `9bf2821a`：`docs/product/EVIDENCE_FIRST_VERTICAL_SLICE_HARNESS.md`
- `9bf2821a`：`docs/superpowers/plans/2026-08-04-evidence-first-vertical-slice-harness.md`
- 该文档候选已通过 fresh spec 与 code-quality 两阶段审查，但在本次暂停前没有集成到 `overnight-integration`。

### 2.2 Readiness / terminal report lane

目标是让无人值守入口在 T0 前严格验证模型 receipt、20–40 篇输入门槛、核心论文集合、authority、Git 状态、scheduler lineage 和终止状态；缺失或漂移时固定返回 BLOCKED/NOT_READY。

并行执行结果：

1. 初始 Owner 候选 `59619668` 被 fresh Reviewer 发现 6 项 P1 fail-open。
2. 第一轮 repair `434af5b` 完成 core study identity 绑定。
   - focused：49 passed。
   - scheduler/orchestration：73 passed。
   - fresh spec 结果：HOLD；receipt 侧的 ID 集合、K 和 digest 仍可被绕过。
3. 第二轮 repair `6daad023` 从最新集成 HEAD 重建两文件，实现并绑定：
   - authority/input/receipt 三方 `CORE_STUDY_IDS`；
   - 顺序、重复、缺失、K 和 digest；
   - 多位置 readiness/gate 冲突检测。
   - Owner focused：27 passed。
   - orchestration：29 passed；scheduler：44 passed；离线 policy/package 检查通过。
   - fresh spec 结果：仍为 HOLD。

暂停前最后一轮 readiness Reviewer 的三个 P1 是：

- `status=READY` 与 `input_ready=false`（或反向冲突）可被忽略，仍返回 `READY_FOR_T0`。
- 非法、缺失或空的 `gates`、`gate_state`、`readiness` 别名容器可能被静默跳过。
- `capability_receipt` 与 `qualification_evidence` 冲突时存在首个值优先，`BLOCKED` 值可能被有效值遮蔽。

这些问题均属于同一 readiness fail-closed 边界；由于该 lane 已完成两轮 bounded repair，本次暂停时没有再开第三轮。

### 2.3 Artifact Manifest / 双向审计 lane

目标是把 authoritative manuscript digest、DOCX/PDF 同源产物、Artifact Manifest、claim-to-source 与 source-to-usage/disposition 连接成可重算、双向、fail-closed 的审计链。

并行执行结果：

1. 初始 Owner 候选 `67c89077` 被 fresh Reviewer 发现 7 项 P1 fail-open。
2. 第一轮 repair `140c981` 修复 canonical 写入目标、状态重算、Evidence 深校验、marker/section 绑定、document role、source manifest authority 和路径矩阵。
   - focused：13 passed。
   - release/manuscript/dual/evidence/synthesis/benchmark 相关回归：339 passed。
   - phase8：4 passed、6 failed；失败均因本地 fixture 缺失，未补造数据。
   - fresh spec 结果：HOLD，发现 nested audit、marker lane、section cardinality 和 section drift 问题。
3. 第二轮 repair `10cb415` 从最新集成 HEAD 重建三文件，重点修复：
   - nested audit digest 重算与篡改检测；
   - marker 语法、lane 和 ID 绑定；
   - 合法多个 claim 绑定同一 section；
   - section 缺失、duplicate/orphan、heading 文本/level/order 漂移。
   - Owner focused：21 passed。
   - 指定相关回归：400 passed。
   - fresh Reviewer 已确认 focused 21 passed、dual 108+68 passed；phase8 新鲜结果为 109 passed、6 failed，仍是缺少 `local/phase8_evidence/**` fixture。

暂停时已收集但尚未形成最终 ACCEPT/HOLD 文本的 Artifact Reviewer 反例包括：

- canonical `00_sources/source_manifest.*` 缺失时，代码仍可能扫描 `01_evidence/source_truth/*/bundle.json` fallback；
- `excerpt=None` 或空 excerpt 在自洽 digest 下可能被接受；
- 缺少 `section_drafts.jsonl` 时可能仍返回 CURRENT；
- 非 slug section ID 和无 claim 的编辑/过渡 section 可能被误阻断；
- 当前 production release 尚未发现实际调用 `artifact_manifest` 的接线，focused 通过不能替代真实交付闭环。

由于用户在该 Reviewer 完成最终文本前要求暂停，本报告不把这些中间审查信号升级成新的最终 verdict，也不继续派发 repair。

## 3. 并行协作方式

- Coordinator 只负责 authority 核验、派发、等待、读取终态和集成前检查，没有在候选中自行实现代码。
- 每个 Owner 使用独立 worktree，readiness 与 Artifact 的写集不重叠。
- 每个 fresh Reviewer 使用独立新会话、Luna 5.6 max、只读权限；Reviewer 不修改、提交或集成候选。
- 所有 Owner 都在提交前运行了 focused test、相关回归、`git diff --check` 和 clean-worktree 检查。
- 一次工具路径偏差曾在主树误建 50-byte placeholder；创建者立即精确移除，暂停前主树复核仍只保留原有 `?? docs/superpowers/`，没有污染既有文件。

## 4. 没有做、不能宣称的事项

以下事项在本窗口没有执行，或没有达到可宣称的证据门槛：

- 没有 cherry-pick 任一 HOLD 候选到 `overnight-integration`。
- 没有修改主工作树现有用户内容。
- 没有 push、PR、部署、发布或远程写入。
- 没有读取或暴露 token、API key、cookie、session、auth 或真实私密日志。
- 没有下载、导入或处理真实 corpus；没有真实 model/network 运行。
- 没有完成 T0、真实 12 小时 unattended run、两次 takeover、真实 Playwright 科学流程或研究者授权。
- 没有 Gold calibration、`CONFIRMED` 分子状态、`READY` 或 `RESEARCHER_AUTHORIZED_RELEASE`。
- phase8 相关失败没有通过伪造 fixture 降级或补齐。
- 旧 Export `ea12d0e` 和 Runtime `b60c461` HOLD 没有被复用或递归修复。

## 5. 暂停时文件与候选状态

| 对象 | 分支 / HEAD | 状态 | 结论 |
|---|---|---|---|
| 主工作树 | `main@1aba27a` | 保留原有 `?? docs/superpowers/` | 未被本次代码修改 |
| 集成 worktree | `codex/overnight-integration@0a88e522` | clean | 未集成任何新候选 |
| readiness repair 1 | `434af5b` | clean | fresh spec HOLD |
| readiness repair 2 | `6daad023` | clean | fresh spec HOLD，未进入 code-quality |
| artifact repair 1 | `140c981` | clean | fresh spec HOLD |
| artifact repair 2 | `10cb415` | clean | Reviewer 在暂停时仍处于只读审查收口，未 ACCEPT |

## 6. 暂停后的安全恢复点

恢复时应从当前事实重新 preflight，而不是从聊天摘要猜测：

1. 先确认主树、集成树和四个候选 worktree 的实际 HEAD、dirty 状态和 Git 操作状态。
2. 重新校验 authority manifest 8/8，并读取当前 Core Contract、Approved Spec 与本报告。
3. 不要直接集成任何 `HOLD` 候选；先由肯恰大人确认是否允许新一轮修复，或调整 stop line。
4. readiness 先处理三类 alias conflict；Artifact 先处理 source-manifest fallback、excerpt/section 语义和实际 release 接线。
5. 真实 corpus、T0、12 小时运行和研究者授权仍需单独的人类 checkpoint，不能由本报告代替。

报告生成时的最终判断：代码候选和测试证据已产生，但主集成尚未推进；系统处于诚实的 `HOLD / 暂停`，不是 READY。
