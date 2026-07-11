# Phase 5b-preflight Real-Lite Data Asset PR

## PR Title

`feat: add real-lite data preflight`

## Summary

This PR adds a standard-library preflight script that inventories existing parsed assets and builds a small real-lite allene review input package. It does not run the review workflow; it only prepares safe inputs for the next phase.

## Added Files

- `scripts/demo/build_real_lite_manifest.py`
- `tests/test_real_lite_manifest.py`
- `demo_projects/real_lite_allene_review/`
- `docs/demo/real_lite_preflight_runbook.md`
- `docs/pr/phase5b_real_lite_preflight_pr.md`

## Updated Files

- `Makefile`: adds `real-lite-preflight`
- `docs/migration/05_incremental_pr_plan.md`

## Assets Found

- MinerU outputs: present
- markdown: present
- content_list JSON: present
- images directories: present
- metadata JSON: present
- registry JSONL: present

The latest run selected 5 allene-related papers from 410 registry/metadata records.

## Input Package

```text
demo_projects/real_lite_allene_review/
  inputs/selected_papers.json
  inputs/paper_registry.jsonl
  inputs/paper_metadata/
  inputs/mineru_markdown/
  inputs/content_list/
  inputs/figures/
  outputs/.gitkeep
```

Markdown is trimmed into excerpts and keeps original `source_path`. `content_list` and `figures` are pointer manifests only.

## Validation

```bash
make real-lite-preflight
python tests/test_real_lite_manifest.py
```

## Safety Boundary

- No PDF read.
- No MinerU API.
- No Qwen/API call.
- No upload.
- No Bailian knowledge base.
- No image generation.
- No full image directory copy.

## Next Stage

Phase 5b should run a real-lite E2E flow using this package. Phase 5c can add promptfoo or custom eval baselines. Phase 6 can start Bailian RAG preflight.
