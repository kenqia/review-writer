# Review-Writer Current Handoff

## Repository

- GitHub: `kenqia/review-writer`
- Local repo placeholder: `<REPO_ROOT>`
- Last verified date: `2026-07-12` Asia/Shanghai

## Current Branches

- `main`: `908239d` (`origin/main`)
- `feat/chem-review-quality-gates`: merged by PR #1.
- `feat/orchestrator-rag-generation-pilot`: merged by PR #2.
- `feat/human-verified-evidence-evaluation`: Phase 8A branch from latest `main`; this task publishes it as a Draft PR only.

## Integrated PRs

- PR #1: <https://github.com/kenqia/review-writer/pull/1>
  - Base: `main`
  - Head: `feat/chem-review-quality-gates`
  - Status: merged
  - Merge commit: `b3b6e3a6a897e44ccc7f106d2823ca5f24ef9ada`
  - Final audit: `docs/pr/pr1_final_merge_audit.md`
- PR #2: <https://github.com/kenqia/review-writer/pull/2>
  - Base after retarget: `main`
  - Head: `feat/orchestrator-rag-generation-pilot`
  - Status: merged
  - Merge commit: `908239d733837352d66e15dd189c7d9f7990b6df`
  - Final audit: `docs/pr/pr2_final_merge_audit.md`

## Completed Phases

- Phase 1: QoderWork migration baseline.
- Phase 2: chemistry review quality gates.
- Phase 3: QoderWork CN skill install and smoke validation.
- Phase 4: Alibaba/Qwen provider skeletons, hello Qwen dry-run path, Qwen judge safety gates.
- Phase 5a-5g: tiny/real-lite E2E, dashboard QA, eval baseline, portability and merge-readiness.
- Phase 5h-5k: reality audit, QoderWork CN validation, clean 3-paper preparation and vertical slice.
- Phase 6a-6d: Bailian no-upload preflight, local retrieval baseline, sanitized small-KB pilot scaffolding, SDK diagnostics, retrieval QA, and Phase 6 final offline gate.
- Phase 7: complete and integrated into `main`; controlled Qwen-only and full Bailian + Qwen E2E completed with `Sections: ready_for_human_review`.

## Phase 8A

Current phase:

```text
Phase 8A: context-isolated three-layer AI adjudication preparation
Checkpoint: PREPARED_FOR_INDEPENDENT_LAYER_1_AND_2_V2
```

Methodology:

```text
HUMAN_SPOT_CHECKED_AI_ADJUDICATION

Context-isolated three-layer AI adjudication with a small human spot check.
Engineering validation and internal demonstration only; not publication-grade
scientific validation.
```

Current local package target:

```text
local/phase8_evidence/
```

Current source status:

- `F3I_MAIN`, `F47A_MAIN`, `F47A_SI`, `P403_MAIN`, and `P403_SI`: V2 weighted
  source identity validated before packaging.
- `F3I_SI`: `NO_SI_PUBLISHED_ON_OFFICIAL_PAGE`.
- `core_review_queue`: 2-4 hour priority subset with core-to-atomic mapping.
- `extended_review_queue`: all atomic review items.
- The first three-layer run is diagnostic-only because semantic input defects
  were identified; its outputs cannot enter final AI decisions.
- V2 uses atomic tasks, dual-mode independent review, locator-quality levels,
  and coordinator-private hidden calibration.

Public status report:

```text
docs/phase8/phase8a_status_report.md
docs/phase8/phase8a_status_report.json
```

The current coordinator turn must stop at:

```text
PREPARED_FOR_INDEPENDENT_LAYER_1_AND_2_V2
```

## Safety Notes

- Phase 8A does not create verified bibliography, verified claims, gold evidence packs, final scientific evaluation reports, or regenerated review prose.
- PDFs, SI, full page text, long excerpts, local image crops, manual decisions, and authenticated caches remain ignored under `local/phase8_evidence/`.
- Default Phase 8 gates are offline and do not call Qwen, download SI, or invoke MinerU cloud.
- AI adjudication results remain separate from the human decision log.
- Effective human decisions take precedence over new AI adjudication and old AI extraction.
- Human spot checks are capped at 10 unique core items.
- The isolation is procedural, not an operating-system sandbox or statistical independence between model weights.

## Next User Action

Run V2 Layer 1 and Layer 2 manually in fresh, separate VS Code Codex sessions
using the external paths recorded in the V2 `COORDINATOR_RESUME.md`. Do not
start Layer 3 until both outputs pass coordinator validation and deterministic
rules. Phase 8B has not started.
