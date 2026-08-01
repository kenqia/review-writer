# Archive Candidates

本文件只登记未来可归档/隔离的候选，不执行 archive、delete、move、rename、overwrite 或 branch cleanup。

## Candidate groups

| Group | Examples | Why it is a candidate | Action in this task |
|---|---|---|---|
| former canonical candidate | `.worktrees/e2r-dual-integration` | exact base revision but dirty (`requirements-ci.txt`) | retain in place; do not clean or reset |
| source-only SI lane | `.worktrees/e2r-chemical-integration` | useful minimal source patch, not integrated and runtime-owned | retain in place; do not cherry-pick whole branch |
| stale e2r/honest lanes | baseline `codex/e2r-*` and `codex/honest-*` entries listed in `CURRENT_WORKSPACE_MAP.md`, except the canonical/source-only/dirty entries | superseded, diverged, or incomplete document snapshot | retain in place; no deletion |
| historical product/release lanes | `m0`, `m1`, `m2`, phase8, provider, QoderWork, and Windows runner worktrees | historical scope rather than the current dual-parse contract | retain in place; no deletion |
| dirty unrelated lanes | `review-writer-task1-empty-project-waiting`, `.worktrees/provider-qualification` | uncommitted user work and unrelated ownership | never treat as authority; do not touch |
| external project data | fresh v3 project, PDF/SI libraries, Chemical ZIPs, staging directories | generated or source data outside Git | preserve byte-for-byte; no relocation |

## Safe future archive preconditions

Any future archive operation requires a separate explicit authorization, a read-only manifest of exact targets, a recoverable backup/restore path, and a fresh status check. This task intentionally leaves all old objects recoverable and visible.
