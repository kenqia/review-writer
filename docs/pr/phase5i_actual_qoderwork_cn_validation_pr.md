# Phase 5i Actual QoderWork CN Validation PR Notes

## Summary

Phase 5i records a real QoderWork CN product-environment validation for the
review-writer skill pack. This corrects the earlier ambiguity between
Codex-simulated manual-flow QA and actual QoderWork CN validation.

## Validation Environment

- Product: QoderWork CN
- Skill: `chem-review-orchestrator`
- Repo: WSL path `<REPO_ROOT_IN_WSL>`; Kenqia's concrete local path is kept in
  `docs/local/KENQIA_LOCAL_VALIDATION.md`
- Branch: `feat/chem-review-quality-gates`
- Runtime HEAD: `7b9a8af docs: add merge readiness audit`

## Passed Gates

```text
smoke
quality-check
qoderwork-check
provider-check
qwen-hello-dry-run
judge-check
tiny-e2e-check
real-lite-preflight
real-lite-e2e-check
dashboard-real-lite-check
eval-baseline-check
```

## Real-Lite Artifacts

- `/tmp/review_writer_real_lite_e2e` existed.
- `checkpoint_log.json` existed.
- `run_summary.json` existed.
- `05_final_audit/quality_report.json` existed.
- `04_first_draft/final_draft.md` existed.
- `03_figure_redraw/figure_manifest.json` existed.

## Checkpoint Interpretation

- Mock/demo output: inspected at Export because the real-lite demo artifacts had
  already been generated and all 9 checkpoints were `approved_mock`.
- Production review start: should stop at Library until paper inputs, MinerU
  parse outputs, metadata, and human checks are trustworthy.

## Safety Boundary

The actual QoderWork CN run reported:

- no PDF read
- no API call
- no upload
- no credential print
- no repository modification

The `run_summary` safety fields `network`, `pdf_read`, `qwen`, `mineru_api`,
and `upload` were all `not_used`.

## Limits

- The run was performed at `7b9a8af`, before the Phase 5h reality-audit commit.
- The run validates QoderWork CN product loading/execution for the offline
  real-lite flow; it does not validate scientific review quality.
- It does not validate all of `chem_papers` or any full RAG corpus.

## Follow-Ups

- Optional: run one lightweight read-only QoderWork CN revalidation on the
  latest HEAD.
- Phase 5j: clean 3-paper human-verified dataset.
- Phase 6a: Bailian RAG no-upload preflight after or alongside the clean
  dataset work, without uploads or knowledge-base creation.
