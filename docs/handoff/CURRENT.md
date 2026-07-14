# Review-Writer Current Handoff

## Repository

- GitHub: `kenqia/review-writer`
- Local repo placeholder: `<REPO_ROOT>`
- Last verified date: `2026-07-14` Asia/Shanghai

## Current Branches

- `main`: `baa9d16` (`origin/main`), including the squash merge of PR #3.
- `feat/phase8b-grounded-review-integration`: active Phase 8B vertical-slice branch.
- `feat/chem-review-quality-gates`: merged by PR #1.
- `feat/orchestrator-rag-generation-pilot`: merged by PR #2.
- `feat/human-verified-evidence-evaluation`: Phase 8A complete; PR #3 is prepared for formal review and remains unmerged.

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
- PR #3: <https://github.com/kenqia/review-writer/pull/3>
  - Base: `main`
  - Head: `feat/human-verified-evidence-evaluation`
  - Status: squash merged
  - Merge commit: `baa9d1616ed7fac44aad4330261c27f22f2006ee`

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

Final phase status:

```text
Phase 8A: complete
Checkpoint: PHASE8A_COMPLETE_PR3_READY_FOR_REVIEW
```

Methodology:

```text
HUMAN_SPOT_CHECKED_AI_ADJUDICATION

Context-isolated source-first inventory and exact-claim verification with a
small human spot check. Engineering validation and internal demonstration
only; it does not establish publication-level scientific validation or
complete human review.
```

Local package target:

```text
local/phase8_evidence/
```

Current source status:

- `F3I_MAIN`, `F47A_MAIN`, `F47A_SI`, `P403_MAIN`, and `P403_SI`: V2 weighted
  source identity validated before packaging.
- `F3I_SI`: `NO_SI_PUBLISHED_ON_OFFICIAL_PAGE`.
- `core_review_queue`: 2-4 hour priority subset with core-to-atomic mapping.
- `extended_review_queue`: all atomic review items.
- The first three-layer run and V2 are diagnostic-only. V2's 41 tasks are an
  adversarial task-validation set, not a scientific adjudication queue.
- The audited V3 preparation is frozen with a `NO-GO` verdict and remains
  diagnostic-only. It must not be started.
- The frozen V3.1 run also has an independent `NO-GO` acceptance verdict. It is
  retained unchanged and must not be started.
- V3.1.1 calibration passed. Scientific Layer A completed 8 rows / 44 claims.
- Exact-claim Layer B completed 44/44 with 29 `SUPPORTED`, 4 locator errors,
  2 reaction-stage errors, 1 entity-binding error, 7 faithfully recorded
  source conflicts, and 1 insufficient-evidence result.
- Deterministic reconciliation and four bounded human spot checks produced 44
  final records: 37 usable or deterministically corrected non-conflict claims
  and 7 retained source-internal conflicts.
- Human budget is 10/10. Layer C was skipped as unnecessary. Phase 8B has not
  started.

Public status report:

```text
docs/phase8/phase8a_status_report.md
docs/phase8/phase8a_status_report.json
```

Final checkpoint:

```text
PHASE8A_COMPLETE_PR3_READY_FOR_REVIEW
```

## Safety Notes

- Phase 8A closure does not create regenerated review prose or claim complete human review.
- PDFs, SI, full page text, long excerpts, local image crops, manual decisions, and authenticated caches remain ignored under `local/phase8_evidence/`.
- Default Phase 8 gates are offline and do not call Qwen, download SI, or invoke MinerU cloud.
- Diagnostic AI results and scientific claim-verification results remain
  separate from the human decision log.
- Effective human decisions take precedence over new AI adjudication and old AI extraction.
- Human spot checks are capped at 10 unique core items.
- The isolation is procedural, not an operating-system sandbox or statistical independence between model weights.

## Phase 8B

Phase 8B started on its own feature branch after PR #3 was merged. The first
bounded vertical slice is complete:

```text
PHASE8B_GROUNDED_REVISION_VERTICAL_SLICE_COMPLETE
```

It reconstructs and assesses the 10 preserved Phase 7 sentences, accounts for
all 44 Phase 8A final claims, uses 12 non-conflict claims in one representative
section, and keeps all 7 source-internal conflicts outside revised prose. It
does not revise the full review. See `docs/phase8/phase8b_vertical_slice.md`.

## Next User Action

Review the one-section revision and its claim-to-sentence mapping before
expanding Phase 8B beyond this vertical slice.
