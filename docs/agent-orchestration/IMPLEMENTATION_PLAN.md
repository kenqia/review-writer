# Owner-Review Orchestration Implementation Plan

Task: `ORCH-001`

Baseline timestamp: `2026-07-16T01:25:34+08:00`

## Sequence

1. Preserve the two-directory baseline and local backups.
2. Have one persistent Implementation Owner write focused tests and retain RED evidence.
3. Implement the review-writer orchestration layer only in the allowed paths.
4. Run the offline `make agent-orchestration-check` gate.
5. Run the isolated `/tmp` `codex exec` plus `resume` dry-run with no fallback.
6. Obtain fresh, read-only review and return actionable findings to the same Owner with `resume`.
7. After review-writer static validation, copy only generic components into the project template.
8. Run fresh verification against both directories and protected-path baselines.

## Ownership

- Leader: task package, acceptance decisions, findings merge, and final report.
- Implementation Owner: the only workspace-write model session for `ORCH-001`.
- Reviewers and Final Verifier: fresh sessions, read-only, findings or verification only.

## Rollback

No automatic repository-wide rollback is allowed. Existing modified entry files are backed up under:

```text
.agent-orchestration-runs/20260716T012534+0800/backups/
```

Restore only a named entry file after inspecting its diff. Delete newly created orchestration paths only after separate human approval. Do not use `git reset`, `git checkout`, or `git clean`.
