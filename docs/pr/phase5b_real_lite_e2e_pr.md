# Phase 5b Real-Lite Offline E2E PR

## PR Title

`feat: add real-lite offline e2e run`

## Summary

This PR adds a deterministic real-lite runner that uses the prepared allene input package to exercise the review-writer workflow skeleton from Library through Export. It validates checkpoint logs, generated artifacts, a non-empty figure manifest, the offline final quality gate, and Markdown export.

## Added Files

- `scripts/demo/run_real_lite_e2e.py`
- `tests/test_real_lite_e2e_workflow.py`
- `docs/demo/real_lite_e2e_runbook.md`
- `docs/pr/phase5b_real_lite_e2e_pr.md`

## Updated Files

- `Makefile`: adds `real-lite-e2e-check`
- `docs/migration/05_incremental_pr_plan.md`

## Selected Papers

- P410
- P406
- P405
- P403
- P401

## Workflow Coverage

- Library
- Discovery
- Matrix
- Blueprint
- Sections
- Figures
- Draft
- Final
- Export

Each checkpoint records input files, output files, human-review requirement, and the mock approval state used by the offline regression run.

## Quality Gate Coverage

The Final stage runs `scripts/validators/validate_review_quality.py` with `--judge-mode offline` and writes:

```text
05_final_audit/quality_report.json
05_final_audit/quality_report.md
```

The runner does not skip Final. Empty figure manifests and blocking validator errors fail strict mode.

## Not Included

- No full `chem_papers` scan.
- No PDF body read.
- No MinerU API.
- No Qwen call.
- No upload.
- No Bailian knowledge base.
- No image API.

## Validation Commands

```bash
make smoke
make quality-check
make qoderwork-check
make provider-check
make qwen-hello-dry-run
make judge-check
make tiny-e2e-check
make real-lite-preflight
make real-lite-e2e-check
python tests/test_real_lite_e2e_workflow.py
```

## Risks

- The draft is excerpt driven and intentionally compact.
- Figure handling is still pointer/placeholder based.
- Offline judge tasks do not replace real human review or a later Qwen judge pass.

## Next Stage

- Phase 5c: real-lite dashboard QA.
- Phase 5d: promptfoo or custom eval baseline.
- Phase 6: Bailian RAG preflight.
