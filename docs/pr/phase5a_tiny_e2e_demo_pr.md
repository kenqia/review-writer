# Phase 5a Tiny Offline E2E Demo PR

## PR Title

`feat: add tiny offline e2e demo`

## Summary

This PR adds a tiny synthetic allene-review demo project and a deterministic runner that exercises the review-writer workflow skeleton from discovery through export. It validates artifacts, checkpoint logging, quality gate output, and Markdown export without using real PDFs or real APIs.

## Added Files

- `demo_projects/tiny_allene_review/`: synthetic demo inputs and expected checkpoint notes.
- `scripts/demo/run_tiny_e2e.py`: offline E2E skeleton runner.
- `tests/test_tiny_e2e_workflow.py`: direct Python regression test.
- `docs/demo/tiny_e2e_runbook.md`: operator runbook.
- `docs/pr/phase5a_tiny_e2e_demo_pr.md`: PR notes.
- `Makefile`: `tiny-e2e-check`.

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

Each checkpoint is logged with `ready_for_human_review` and `approved_mock`.

## Quality Gate Coverage

The demo writes `05_final_audit/quality_report.json` through the existing validator in offline mode. The Final gate is not skipped.

## Not Included

- No full `chem_papers` scan.
- No MinerU API.
- No Qwen API.
- No PDF read.
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
python tests/test_tiny_e2e_workflow.py
```

## Risks

- The demo proves workflow wiring, not review quality.
- The export step is Markdown-only.
- Mock checkpoint approval must not be confused with real human review.

## Next Stage

- Phase 5b: use 3-5 real, already parsed MinerU markdown records for a real-lite run.
- Phase 5c: add promptfoo or a custom eval baseline.
