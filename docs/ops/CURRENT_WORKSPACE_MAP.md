# Current Workspace Map

审计日期：2026-08-01（Asia/Shanghai）

本文件是 workspace canonicalization 的只读审计记录与 canonical 入口地图。它不代表综述验收、Chemical 科学批准或 release readiness。

## Canonical 入口

| 项目 | 结论 |
|---|---|
| canonical worktree | `/home/kenqia/my_folder/review-writer/.worktrees/e2r-canonicalization` |
| canonical branch | `codex/e2r-canonicalization` |
| base revision | `31d9dab16edc105b4f03aa7e8d3bf3745ed326fa` |
| base parent | `44e485a2fe3b6161b8b3965d7be5412ad0f005ee` |
| old candidate | `.worktrees/e2r-dual-integration` / `codex/e2r-dual-integration` / `31d9dab`; retained and not modified |
| SI source-only revision | `0aa517cc802a7af714bb39363755b46c137f0b16` / parent `2ae1dcaf354d0dbb6bcdc7644fbb52135fa06cde` |
| repository root | `/home/kenqia/my_folder/review-writer` / `main` / `baa9d1616ed7fac44aad4330261c27f22f2006ee` |

Canonical revision selection used specification coherence, ancestry, corresponding tests, clean state, and runtime receipt scope. Commit date alone was not used.

## Git inventory

Phase 0 baseline, before creating this worktree:

- 57 worktrees and 66 local `refs/heads/*` branches.
- 57 branches were checked out by those worktrees; 9 branch refs had no worktree.
- 3 worktrees were dirty: the old dual integration candidate, `task1-empty-project-waiting`, and `provider-qualification`.
- Branch-tip relation to `31d9dab`: 1 exact tip, 33 ancestors, 32 diverged, 0 descendants.

After creating this non-destructive canonical worktree, the inventory is 58 worktrees and 67 local branches. The 9 branch-only refs remain branch-only. No old worktree or branch was deleted, moved, reset, or overwritten.

The four canonical documents were read from the same `31d9dab` candidate revision:

| Document | SHA-256 |
|---|---|
| `docs/superpowers/specs/2026-07-31-honest-progressive-route.md` | `fc352ccb4c66aeac10b3ea0cb6bb31dd567bf9dee0ff85f9d5fefa5228ce61c6` |
| `docs/superpowers/specs/2026-07-30-dual-parse-evidence-to-release-design.md` | `473f6b0ed893b51d6671e84ae8a0d67630d740a551b0445e55333f7f69f49a67` |
| `docs/superpowers/plans/2026-07-30-dual-parse-evidence-to-release-complete-loop.md` | `76a08e6d87dc739f257925c1460a8de25a04db76b7edadd4954de39308d8bc96` |
| `docs/qa/three-paper-dual-parse-evidence-to-release-playwright.md` | `421f3b30b24bcf4d9369f2fe8237db739b32547d2ef71f9cb89ad38c3f18dd60` |

Only the `31d9dab` commit in the Phase 0 inventory shared all four canonical document blobs. This is why other clean but older/diverged worktrees are not interchangeable with the canonical entry.

## Classification

The categories below are primary roles. `DIRTY_UNTRUSTED` is also a trust flag: a worktree can retain useful history while being ineligible as an authority source.

### CANONICAL_CANDIDATE

- Final entry: `/home/kenqia/my_folder/review-writer/.worktrees/e2r-canonicalization`, created clean from `31d9dab`, containing only the reviewed SI semantics, regression test, and these four ops documents.
- The former candidate `/home/kenqia/my_folder/review-writer/.worktrees/e2r-dual-integration` is retained but no longer trusted as a clean authority because `requirements-ci.txt` is modified.

### SOURCE_ONLY

- `/home/kenqia/my_folder/review-writer/.worktrees/e2r-chemical-integration`
- branch `codex/e2r-chemical-integration`, `0aa517cc802a7af714bb39363755b46c137f0b16`, clean.
- It is a source-only SI patch lane, diverged from the canonical candidate; it is not the integrated head.

### DIRTY_UNTRUSTED

- `/home/kenqia/my_folder/review-writer/.worktrees/e2r-dual-integration` — `M requirements-ci.txt`.
- `/home/kenqia/my_folder/review-writer-task1-empty-project-waiting` — modified `tests/test_qoderwork_native_review_writer.py`, `view/assets/dashboard/review-ui.css`, `view/assets/dashboard/review.html`, and `view/serve_review_dashboard.py`.
- `/home/kenqia/my_folder/review-writer/.worktrees/provider-qualification` — four modified tracked files plus untracked provider-qualification docs, scripts, manifest, and tests.

No dirty file was copied into the canonical worktree.

### HISTORICAL

These clean worktrees are retained historical product, migration, provider, or release lanes and are not inputs to this canonicalization:

- `main`
- `codex/m0-product-contract`
- `codex/m1-case01-v5`
- `codex/m1-local-product-base`
- `codex/m2-qoder-native-benchmark`
- `feat/fresh-qoderwork-qwen-readiness`
- `feat/phase8b-grounded-review-integration`
- `feat/provider-qualification-noschema`
- `feat/qoderwork-native-review-workbench`
- `feat/windows-word-visual-review-runner`

### STALE

These clean e2r/honest/dual/round/resolved-SMILES lanes are retained but stale for this task because they do not share the complete four-document canonical snapshot and/or are diverged or superseded by the candidate:

```text
codex/e2r-chemical-paper-import
codex/e2r-chemical-paper-integration
codex/e2r-chemical-paper-ui
codex/e2r-dashboard-ui
codex/e2r-dual-dashboard
codex/e2r-dual-qa-protocol
codex/e2r-dual-release
codex/e2r-dual-repair-cp03-dashboard
codex/e2r-dual-repair-cp03-scientific
codex/e2r-dual-repair-cp04-dashboard
codex/e2r-dual-repair-cp05-release
codex/e2r-dual-repair-cp05-scientific
codex/e2r-dual-repair-dashboard-cp02
codex/e2r-dual-repair-scientific-cp02
codex/e2r-dual-rerun3-pdf-repair
codex/e2r-dual-rerun4-completion-ui
codex/e2r-dual-rerun5-locator-view
codex/e2r-dual-scientific
codex/e2r-dual-ui-partial-batch
codex/e2r-honest-progressive-contract-repair
codex/e2r-honest-progressive-downstream-repair
codex/e2r-independent-qa
codex/e2r-release-evaluation
codex/e2r-resolved-smiles-dashboard
codex/e2r-resolved-smiles-dashboard-repair
codex/e2r-resolved-smiles-release
codex/e2r-resolved-smiles-scientific
codex/e2r-resolved-smiles-scientific-repair
codex/e2r-round1-release-backend
codex/e2r-round2-chemical-release
codex/e2r-round2-credits-ui
codex/e2r-round2-scientific-state-content-list-v2
codex/e2r-round2-scientific-state-repair
codex/e2r-round2-scientific-state-repair-f002
codex/e2r-round2-scientific-state-repair-f003
codex/e2r-runtime-view-repair
codex/e2r-scientific-state
codex/honest-progressive-api-bridge
codex/honest-progressive-docs-alignment
codex/honest-progressive-domain-v2
codex/honest-progressive-downstream-v2
codex/honest-progressive-ui-v2
codex/honest-progressive-unknown-repair
```

The baseline stale count is 43; the new canonical worktree is excluded from that baseline count.

### Branch-only refs

The following 9 local branches had no worktree at the Phase 0 snapshot. They remain untouched:

- stale: `codex/e2r-honest-docs-alignment`, `codex/e2r-round1-scientific-state-repair`, `codex/honest-progressive-domain`, `codex/honest-progressive-downstream`, `codex/honest-progressive-ui`;
- historical: `feat/chem-review-quality-gates`, `feat/orchestrator-rag-generation-pilot`, `qoderwork-migration-baseline`, `snapshot/pre-provider-qualification-20260716`.

## External input boundary

The following are external data, not Git worktrees, and were audited by path/metadata only:

- fresh project: `/home/kenqia/my_folder/review-projects/vis-light-olefin-difunctionalization-complete-loop-regression-v3-honest-progressive-fresh`;
- input staging: `/home/kenqia/my_folder/review-projects/e2r-dual-parse-inputs-20260801`;
- three main PDFs and three Chemical ZIPs are preserved in place; their evidence is recorded in `DRIFT_REPORT.md`;
- no PDF or ZIP was opened, unpacked, moved, replaced, or committed.

## Runtime map

| Port | PID | cwd / source lane | configured root | read-only observation |
|---:|---:|---|---|---|
| 63822 | 135420 | `.worktrees/e2r-chemical-integration` | `/home/kenqia/my_folder/review-projects` | `/api/projects` returned an empty array |
| 8765 | 42007 (last observed) | `.worktrees/e2r-dual-integration` | `/home/kenqia/my_folder` | initial probe advertised 4 projects; root was broader than the target project; final probe was refused |

No runtime was stopped or restarted. The final probe still found 63822 alive and found 8765 unavailable; neither exposed a project-scoped authority receipt, so neither is a canonical runtime authority.
