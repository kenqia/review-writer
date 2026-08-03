# 收敛清理 inventory — 2026-08-03

这是本地 `main` 快进到 `ab3e76b7d040d6bb1e3178778d569e772aa96b8f` 后生成的只读
清理清单。它记录恢复边界，不等于允许删除清单之外的任何内容。

## 仓库状态

```text
branch=main
head=ab3e76b7d040d6bb1e3178778d569e772aa96b8f
relationship=main == origin/main
local_untracked=docs/CONVERGENCE_2026-08-03.md; docs/superpowers/specs/
local_tests=基线快照时未运行；后续基线 smoke/quality-check 均通过
```

当前有 132 个本地 branch 和 118 个注册 worktree。branch 引用仍是恢复记录；
worktree 只是 checkout，不是独立的 Git 历史副本。

## 保留的 dirty worktree

以下位置未移除，因为存在 tracked/untracked 修改，或是明确保留的临时 checkout。
为保持仓库可移植，提交文档只记录相对角色，不写入本机绝对路径；实际恢复路径
保留在当前会话的本地清单中：

- `<WORKTREE_ROOT>/review-writer`
- `<WORKTREE_ROOT>/review-writer-task1-empty-project-waiting`
- `<WORKTREE_ROOT>/review-writer/.worktrees/deliverable-first-rescue`
- `<WORKTREE_ROOT>/review-writer/.worktrees/e2r-dual-integration`
- `<WORKTREE_ROOT>/review-writer/.worktrees/provider-qualification`
- `<WORKTREE_ROOT>/review-writer/.worktrees/repair-scientific-schema-f002a`
- `<WORKTREE_ROOT>/review-writer/.worktrees/review-writer-next-phase-integration`
- `<TEMP_ROOT>/review-writer-repair-scientific-f003b-red`

主 checkout 另有 97 个 ignored entry。ignored 不等于无价值，因此不纳入第一轮清理。

## 已完成的第一轮清理

以下 6 个干净 worktree 没有 untracked 或 ignored 内容；它们的 branch 和 commit 仍保留：

- `codex/canonical-anchor-transactional-repair`
- `codex/e2r-runtime-view-repair`
- `codex/repair-canonical-receipt-p1`
- `codex/repair-generic-si-binding-p1`
- `codex/next-phase-repair-scientific-schema-f003`
- `codex/e2r-chemical-paper-integration`

回滚方式是 `git worktree add <new-path> <existing-branch>`；没有删除 branch 或 commit。

## 干净但带数据的 worktree

剩余干净 worktree 含 ignored runtime/data，部分体积足以让自动移除误删本地证据：

- `m2-qoder-native-benchmark`：约 587 MB
- `e2r-dual-integration`：约 222 MB（同时 dirty，已保留）
- `e2r-chemical-integration`：约 200 MB
- 其他多数 E2R、repair、owner、provider、M0/M1/M2、Phase 8 checkout：约 6–15 MB，含 ignored entry

这些 worktree 必须先生成逐目录 ignored-file manifest。

## 外部项目副本

外部 `review-projects` 目录目前有多个大副本，体积约为：

- `vis-light-olefin-difunctionalization-complete-loop-regression-v3-honest-progressive-fresh`：453 MB
- `vis-light-olefin-difunctionalization-deliverable-first-rescue-a1`：453 MB
- `vis-light-olefin-difunctionalization-deliverable-first-rescue-a2`：453 MB
- `vis-light-olefin-difunctionalization-complete-loop-regression-v3-honest-progressive-fresh-backup-before-mvp-20260801-175720`：388 MB
- `e2r-dual-parse-inputs-20260801`：239 MB
- 较旧 v2/v3 副本：24–25 MB
- `vis-light-olefin-difunctionalization-deliverable-first-rescue-a3`：536 KB

没有删除任何外部项目。确定 canonical copy 前必须有文件/hash inventory 和恢复
位置；体积相同不代表内容等价，也不代表有权威性。

## 下一轮删除闸门

下一轮只可移除已经明确列出的 clean worktree，并且必须先确认其中 ignored
内容只是可再生 cache/runtime。branch 在 archive manifest 记录前继续保留。外部
项目、PDF、SI、MinerU 输出和候选 review package，在 Owner 与 hash-bound 恢复记录
明确前继续保留。
