# Real-Lite Offline E2E Runbook

## Goal

Phase 5b runs an offline end-to-end skeleton with a small real-lite allene input package. The goal is to validate workflow wiring, checkpoint artifacts, the final quality gate, and Markdown export using already prepared local excerpts and pointer manifests.

This is not a full scientific review run.

## Selected Papers

The current package uses:

- P410
- P406
- P405
- P403
- P401

These records come from `demo_projects/real_lite_allene_review/` and are limited to metadata, trimmed MinerU markdown excerpts, content_list pointers, and figure pointers.

## Input Structure

```text
demo_projects/real_lite_allene_review/
  README.md
  inputs/
    topic.md
    selected_papers.json
    paper_registry.jsonl
    paper_metadata/
    mineru_markdown/
    content_list/
    figures/
  outputs/
    .gitkeep
```

The runner does not read original PDFs or full paper bodies. It only reads committed excerpts and pointer manifests.

## Run

```bash
python scripts/demo/run_real_lite_e2e.py \
  --demo-root demo_projects/real_lite_allene_review \
  --output-root /tmp/review_writer_real_lite_e2e \
  --strict
```

Or:

```bash
make real-lite-e2e-check
```

## Output Structure

```text
/tmp/review_writer_real_lite_e2e/
  project_status_before.json
  checkpoint_log.json
  00_discovery/discovery_candidates.json
  01_matrix_outline/literature_matrix.json
  01_matrix_outline/outline.md
  section_blueprint.json
  02_section_drafting/section_1.md
  03_figure_redraw/figure_manifest.json
  04_first_draft/final_draft.md
  05_final_audit/final_audit_report.json
  05_final_audit/quality_report.json
  export/final_draft.md
  run_summary.json
```

## Checkpoint Chain

The runner emits nine checkpoint records:

1. Library
2. Discovery
3. Matrix
4. Blueprint
5. Sections
6. Figures
7. Draft
8. Final
9. Export

Each checkpoint records input files, output files, `blocked`, `ready_for_human_review`, and `approved_mock` states. Real projects must replace `approved_mock` with actual human decisions.

## Quality Gate

The Final stage calls:

```bash
python scripts/validators/validate_review_quality.py \
  --judge-mode offline
```

The runner writes `05_final_audit/quality_report.json` and `05_final_audit/quality_report.md`. It fails in strict mode if the static quality gate reports blocking errors or if the figure manifest is empty.

## Safety Boundary

- No PDF read.
- No MinerU API.
- No Qwen call.
- No network.
- No upload.
- No Bailian knowledge base.
- No image generation.

## Current Limits

- Text is trimmed excerpt driven, not a complete literature synthesis.
- Figure output is a pointer placeholder, not a real redraw.
- The judge is offline, not Qwen-backed.
- Export is Markdown only.

## Next Stages

- Phase 5c: real-lite dashboard QA.
- Phase 5d: promptfoo or custom eval baseline.
- Phase 6: Bailian knowledge-base RAG preflight.
