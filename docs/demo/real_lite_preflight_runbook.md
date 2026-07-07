# Real-Lite Data Preflight Runbook

## Goal

Phase 5b-preflight inventories existing parsed assets and builds a small real-lite input package for 3-5 already parsed allene-related papers. It does not generate a review, read PDFs, call MinerU, call Qwen, upload files, create a Bailian knowledge base, or call image APIs.

## Why Preflight First

The repository now has an offline tiny E2E demo. Before running a real-lite workflow, we need to know which real parsed assets already exist and whether they can support a small reproducible run. Preflight avoids accidentally scanning all PDFs or invoking external services.

## Asset Summary

The local validation preflight found parsed assets. Use placeholders in generic
documentation:

- MinerU outputs: `<MINERU_OUTPUT_ROOT>`
- MinerU markdown: present
- content_list JSON: present
- images directories: present
- metadata JSON: `<REVIEW_LIBRARY>/metadata`
- registry JSONL: `<REVIEW_LIBRARY>/registry`

Latest preflight selected 5 allene-related records from 410 registry/metadata records.

## Run

```bash
make real-lite-preflight
```

Equivalent command:

```bash
python scripts/demo/build_real_lite_manifest.py \
  --search-root <DATA_SEARCH_ROOT> \
  --repo-root <REPO_ROOT> \
  --output-json /tmp/real_lite_asset_manifest.json \
  --output-md /tmp/real_lite_asset_manifest.md \
  --max-papers 5 \
  --strict
```

## Input Package

When at least 3 eligible papers are found, the script creates:

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

The package stores:

- copied metadata JSON
- trimmed MinerU markdown excerpts with original `source_path`
- content_list pointer JSON
- figure directory pointer JSON

It does not copy PDFs or full image directories.

## If Blocked

If fewer than 3 eligible records are found, the script writes:

```text
docs/demo/real_lite_asset_gap_report.md
```

and explains which assets are missing.

## Safety

- PDF body read: no
- MinerU API: no
- Qwen/API calls: no
- Uploads: no
- Bailian knowledge base creation: no
- Image generation: no

## Next Stages

- Phase 5b: run real-lite E2E using this input package.
- Phase 5c: introduce promptfoo or a custom eval baseline.
- Phase 6: Bailian knowledge-base RAG preflight.
