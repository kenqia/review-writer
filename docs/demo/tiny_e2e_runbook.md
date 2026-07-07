# Tiny End-to-End Offline Demo Runbook

## Goal

Phase 5a provides a tiny, deterministic, offline demo project for the review-writer workflow skeleton. It validates stage wiring, checkpoints, quality gate output, and Markdown export without claiming real review quality.

## Why Not Full `chem_papers`

The demo deliberately avoids full `chem_papers` and real PDFs because Phase 5a is a workflow regression test, not a literature-reading run. It must be fast, safe, and repeatable on any machine without MinerU, Qwen, DashScope, Bailian, or image services.

## Demo Input Structure

```text
demo_projects/tiny_allene_review/
  README.md
  inputs/
    topic.md
    paper_registry.jsonl
    paper_metadata/
    mock_mineru_markdown/
    figures/
  expected/
    expected_checkpoints.md
  outputs/
    .gitkeep
```

The inputs contain three synthetic allene-ligand paper records, tiny mock markdown snippets, and one placeholder SVG. They are not real paper正文.

## Run

```bash
python scripts/demo/run_tiny_e2e.py \
  --demo-root demo_projects/tiny_allene_review \
  --output-root /tmp/review_writer_tiny_e2e \
  --strict
```

Or:

```bash
make tiny-e2e-check
```

## Output Structure

```text
/tmp/review_writer_tiny_e2e/
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
```

## Checkpoint Chain

The demo emits nine checkpoint records:

1. Library
2. Discovery
3. Matrix
4. Blueprint
5. Sections
6. Figures
7. Draft
8. Final
9. Export

Each checkpoint records `blocked`, `ready_for_human_review`, and `approved_mock` states. Real projects must still stop for human approval.

## Quality Gate

The runner calls `scripts/validators/validate_review_quality.py` in offline mode. It writes:

```text
05_final_audit/quality_report.json
05_final_audit/quality_report.md
```

The Final gate is not skipped. The demo draft is designed to pass static checks without prompt leakage.

## Safety

- No network.
- No real Qwen call.
- No MinerU API.
- No real PDF body read.
- No upload.
- No Bailian knowledge base.
- No image generation.

## Current Limits

- Metadata and markdown are synthetic.
- The figure is a placeholder SVG.
- Export is Markdown only.
- Human approval is represented by `approved_mock` checkpoints.

## Next Stages

- Phase 5b: run a real-lite demo with 3-5 already parsed MinerU markdown files.
- Phase 5c: introduce promptfoo or a custom eval baseline for repeatable quality scoring.
