# Phase 5c Real-Lite Dashboard QA PR

## PR Title

`feat: add real-lite dashboard QA`

## Summary

This PR adds dashboard support and tests for the real-lite E2E output root. The
dashboard can now expose a direct output package such as `<OUTPUT_ROOT>` without
requiring a nested `review-projects/<project_id>` layout.

## Added Files

- `tests/test_dashboard_real_lite_payload.py`
- `docs/demo/real_lite_dashboard_qa.md`
- `docs/pr/phase5c_real_lite_dashboard_qa_pr.md`

## Updated Files

- `view/serve_review_dashboard.py`
- `view/assets/dashboard/final.html`
- `view/assets/dashboard/figures.html`
- `view/assets/dashboard/matrix.html`
- `view/assets/dashboard/blueprint.html`
- `Makefile`
- `docs/migration/05_incremental_pr_plan.md`

## Dashboard Coverage

- Final payload includes `final_draft_md`, `quality_report`, `quality_report_md`, `final_audit_report`, and `checkpoint_log`.
- Figures payload includes `figure_manifest`.
- Matrix payload supports real-lite `literature_matrix.rows`.
- Blueprint payload supports root-level `section_blueprint.json`.
- Sections payload supports top-level `section_*.md`.
- `/api/checkpoints` exposes the 9 real-lite checkpoints.

## File Access Regression

Validated:

- `/file?path=/etc/passwd` returns `403`
- `/file?path=../../../../etc/passwd` returns `403`
- review-root-local files are readable

## Validation

```bash
make dashboard-real-lite-check
python tests/test_dashboard_real_lite_payload.py
```

Full local QA:

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
make dashboard-real-lite-check
```

## Not Included

- No full `chem_papers` scan.
- No PDF body read.
- No MinerU API.
- No Qwen call.
- No upload.
- No Bailian knowledge base.
- No image generation.

## Risks

- The test verifies payload and endpoint behavior rather than screenshot-level visual polish.
- Real-lite draft and figure outputs remain skeleton artifacts.

## Next Stage

- Phase 5d: eval baseline.
- Phase 5e: QoderWork CN manual real-lite flow.
- Phase 6: Bailian RAG preflight.
