# Review-Writer Current Handoff

## Repository

- GitHub: `kenqia/review-writer`
- Local repo: `/home/kenqia/my_folder/review-writer`
- Last verified date: `2026-07-11` Asia/Shanghai

## Current Branches

- `main`: `506c066` (`origin/main`)
- `feat/chem-review-quality-gates`: `a28e4b2` (`origin/feat/chem-review-quality-gates`)
- `feat/orchestrator-rag-generation-pilot`: functional head `e01d765` on top of `a28e4b2`; this handoff document is the current stack-head documentation update.

## Current Commits

- `a28e4b2 ci: add offline validation workflow`
- `e01d765 feat: add orchestrator retrieval generation pilot`
- Previous expected Phase 6 commit exists: `4a3cac1 feat: complete bailian retrieval qa`
- Previous expected Phase 7 commit was rebased from `5e11fe7` to `e01d765`

## Open PRs

- PR #1: <https://github.com/kenqia/review-writer/pull/1>
  - Base: `main`
  - Head: `feat/chem-review-quality-gates`
  - Status: Open Draft
  - Current head after reconciliation: `a28e4b2`
  - Body updated with Phase 5h-6d summary, Phase 6 final metrics, and controlled-pilot safety wording.
- PR #2: <https://github.com/kenqia/review-writer/pull/2>
  - Base: `feat/chem-review-quality-gates`
  - Head: `feat/orchestrator-rag-generation-pilot`
  - Status: Open Draft
  - Stacked on PR #1.

## Completed Phases

- Phase 1: QoderWork migration baseline.
- Phase 2: chemistry review quality gates.
- Phase 3: QoderWork CN skill install and smoke validation.
- Phase 4: Alibaba/Qwen provider skeletons, hello Qwen dry-run path, Qwen judge safety gates.
- Phase 5a-5g: tiny/real-lite E2E, dashboard QA, eval baseline, portability and merge-readiness.
- Phase 5h-5k: reality audit, QoderWork CN validation, clean 3-paper preparation and vertical slice.
- Phase 6a-6d: Bailian no-upload preflight, local retrieval baseline, sanitized small-KB pilot scaffolding, SDK diagnostics, retrieval QA, and Phase 6 final offline gate.
- CI reconciliation: offline GitHub Actions workflow added for PR/push gates.

## Current Phase 7 Blocker

Phase 7 offline replay passes, but the controlled real pilot is incomplete:

- Bailian retrieval reached EvidencePack generation.
- Qwen generation failed with read timeout.
- No real generated section was validated as complete.
- Next closure work must not convert offline replay success into a real-pilot success claim.

## Offline Gates

Fresh local gates run during reconciliation:

```bash
make release-readiness-check
make bailian-phase6-final-check
make phase7-pilot-dry-run
make offline-ci-workflow-check
```

CI workflow:

```text
.github/workflows/offline-ci.yml
```

CI jobs:

- workflow syntax/static guard
- release readiness
- Phase 6 final offline gate with CI SDK inspection dependencies
- safety and portability checks

## Real-Pilot Status

- Default checks do not call Qwen/Bailian, upload files, or create knowledge bases.
- Controlled real pilots require explicit authorization, sanitized payloads, `/tmp` reports, and best-effort cleanup.
- This reconciliation did not run any real Qwen/Bailian calls.

## Known Caveats

- `release-readiness-check` can use local external demo metadata when `SEARCH_ROOT` points outside the repo. GitHub CI validates deterministic repository gates and safety plumbing, but does not prove local external paper-library availability.
- Phase 6 final SDK contract introspection requires Bailian SDK packages. CI installs the pinned inspection dependencies from `requirements-ci.txt`; local default remains `review-writer-bailian` via `BAILIAN_SDK_PYTHON`.
- PR #1 and PR #2 are Draft and must not be merged without human review.
- AGENTS.md remains reserved for stable project rules; this file owns the current commit/PR/blocker state.

## Next Issue

Continue Phase 7 real generation closure:

- retry or harden Qwen generation only with explicit authorization;
- preserve sanitized payloads and `/tmp` reporting;
- verify claim-evidence coverage and unsupported-claim count on any real output;
- keep `Sections` at human-review checkpoint until validated.
