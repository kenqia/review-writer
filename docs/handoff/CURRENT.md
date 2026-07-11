# Review-Writer Current Handoff

## Repository

- GitHub: `kenqia/review-writer`
- Local repo placeholder: `<REPO_ROOT>`
- Last verified date: `2026-07-11` Asia/Shanghai

## Current Branches

- `main`: `506c066` (`origin/main`)
- `feat/chem-review-quality-gates`: `35c078c` (`origin/feat/chem-review-quality-gates`)
- `feat/orchestrator-rag-generation-pilot`: stacked on `feat/chem-review-quality-gates`; local closure commits include provider routing, real preflight, grounded validation hardening, Qwen runtime dependency documentation, and Phase 7 real E2E closure.

## Current Commits

- `a28e4b2 ci: add offline validation workflow`
- `e0d4ce9 ci: make release readiness portable`
- `35c078c ci: pin release readiness to repo fixtures`
- `e01d765 feat: add orchestrator retrieval generation pilot`
- `fbee482 Merge branch 'feat/chem-review-quality-gates' into feat/orchestrator-rag-generation-pilot`
- `73a7245 Merge branch 'feat/chem-review-quality-gates' into feat/orchestrator-rag-generation-pilot`
- Previous expected Phase 6 commit exists: `4a3cac1 feat: complete bailian retrieval qa`
- Previous expected Phase 7 commit was rebased from `5e11fe7` to `e01d765`

## Open PRs

- PR #1: <https://github.com/kenqia/review-writer/pull/1>
  - Base: `main`
  - Head: `feat/chem-review-quality-gates`
  - Status: Open Draft
  - Current head after reconciliation: `35c078c`
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

None for Phase 7 real E2E closure. The controlled real pilot completed in the
unified `review-writer-bailian` environment.

Latest verified real closure:

- `review-writer-bailian` has Bailian SDK and `openai==1.93.0`.
- `python -m pip check`: pass.
- `make phase7-real-preflight`: pass with `network_calls=0`.
- Qwen-only streaming smoke: pass.
- Full Bailian + Qwen E2E: pass.
- Model: `qwen3.7-plus`.
- Region reported safely as `cn-beijing`; dedicated endpoint used; endpoint redacted.
- Full E2E retrieval evidence count: `3` (`F3I`, `F47A`, `P403`).
- Full E2E stream: `stream_started=true`, `chunks_received=86`.
- Full E2E grounding: claim-evidence coverage `1.0`, unsupported claims `0`, unsupported citations `0`, prompt leakage `0`.
- Checkpoint: `Sections: ready_for_human_review`.
- Temporary file/index cleanup: pass.
- Real-call counts in this closure run: Qwen-only requests `1`, full E2E runs `1`, total Qwen requests `2`, Bailian lifecycles `1`, evidence-backed retries `0`.

## Offline Gates

Fresh local gates run during reconciliation and Phase 7 closure:

```bash
make release-readiness-check
make bailian-phase6-final-check
make phase7-pilot-dry-run
make phase7-real-preflight
make offline-ci-workflow-check
make quality-check
make smoke
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
- Latest closure attempt used one Qwen-only real call and one full Bailian + Qwen E2E call.
- Full E2E created one temporary Bailian file/index lifecycle from the clean 3-paper compact payload and cleaned it up successfully.
- Reports are under `/tmp/review_writer_phase7_real_qwen_only_1.*` and `/tmp/review_writer_phase7_real_full_e2e_1.*`; they contain only redacted/safe fields.

## Known Caveats

- `release-readiness-check` can use local external demo metadata when `SEARCH_ROOT` points outside the repo. GitHub CI validates deterministic repository gates and safety plumbing, but does not prove local external paper-library availability.
- Phase 6 final SDK contract introspection requires Bailian SDK packages. CI installs the pinned inspection dependencies from `requirements-ci.txt`; local default remains `review-writer-bailian` via `BAILIAN_SDK_PYTHON`.
- PR #1 and PR #2 are Draft and must not be merged without human review.
- AGENTS.md remains reserved for stable project rules; this file owns the current commit/PR/blocker state.

## Next Issue

Proceed only to human scientific evidence review or PR review if desired. Do
not treat `Sections: ready_for_human_review` as a final scientific review.
