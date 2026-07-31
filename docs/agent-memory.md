# Project Agent Memory

## 2026-07-31 — Honest Progressive Route is the single chemistry gate

Do not recreate a strict/exploratory pair for Chemical Completion. The only
route is `honest_progressive`: preserve incomplete values and disclose their
uncertainty. A molecule is `CONFIRMED`, `AI_PROVISIONAL`, or `BLOCKED`; the
last one has `value=null` and a visible gap reason. AI candidates require a
PDF/structure-figure locator, confidence, and provenance, and may not be used
as confirmed facts. Continue at the project level when
`(CONFIRMED + AI_PROVISIONAL) / 309 >= 0.80`; always expose the three counts,
per-study coverage, traceability, and gap registry. Append-only actor
mismatches become `actor_provenance_residual` disclosures rather than history
rewrites or project resets.

## 2026-07-31 — Keep Evidence-to-Release execution on the mainline

The dual-parse complete-loop run showed that valid P1 repairs can drift into an open-ended security review when each reviewer adds a new threat-model dimension and long gates are started before contracts stabilize.

Reusable operating rule:

1. Lock the current acceptance objective and its explicit stop line.
2. Close known P0/P1 and science-affecting P2 findings that directly violate the approved design.
3. Treat new non-scientific P2/P3 observations as residual risk unless they block the current end-to-end contract.
4. During repair, run only RED/GREEN and focused Owner tests.
5. Merge cross-Owner contracts once, add one combined regression, then run the prescribed long Task 9 gates once from the final clean revision.
6. Return immediately to a fresh non-overwriting project and a new checkpoint-1 browser run.
7. Never trade scientific truth for completion: unsupported SMILES stays blocked.

WSL test environment:

- Prefer `TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 python3 -m pytest ...` so pytest and `TemporaryDirectory` use native ext4 semantics instead of Windows DrvFS.
- Add `-s` only when capture/tempdir fails, not as a default product workaround.
- The `RequestsDependencyWarning` from the user shell is separate from pytest tempdir behavior; resolve it later in an isolated Python environment, not inside an active acceptance repair.

Parallel session policy for future complete-loop work:

- Use new Codex app sessions with one bounded role per session (Owner, independent spec/quality reviewer, QA Coordinator, or Integration Owner), each on an isolated worktree or an explicitly named existing worktree.
- When the app route is available, select `gpt-5.6-luna` with `max` reasoning for these bounded sessions. The collaboration subagent API may expose a different model list; never claim Luna availability from that API alone.
- Grant full local filesystem access only within the user-authorized WSL/project scope. Do not grant or infer remote write, push, deploy, token access, or destructive reset authority.
- Fan out to the highest number of independent slots the host exposes, but do not parallelize two writers over the same worktree or the same mutable project. Reviewers remain read-only; only the named Owner writes its worktree.
- Use `codex_app__wait_threads`/thread status for new sessions and collect each session's commit, parent, clean status, test counts, and READY/BLOCKED handoff before integration.
- Model choice and parallelism never change the mainline stop rule: stabilize the contract, integrate once, run the prescribed gates once, then create a fresh project and fresh browser run.
