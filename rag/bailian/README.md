# Bailian RAG Preflight

Phase 6a prepares a dry-run corpus manifest for Alibaba Model Studio / Bailian RAG work without uploading data.

The preflight gate checks:

- `mode: dry_run`
- `no_upload: true`
- maximum 3 clean draft papers
- no PDF, raw image, raw MinerU markdown, or full PDF text fields
- no local absolute paths
- no secret-like values
- `needs_human_review: true` is preserved
- `trusted_for_scientific_quality: false` is preserved

Run:

```bash
python scripts/rag/bailian_preflight.py \
  --clean-root demo_projects/clean_3paper_allene_review \
  --config rag/bailian/preflight_config.example.yaml \
  --output-json /tmp/bailian_rag_preflight.json \
  --output-md /tmp/bailian_rag_preflight.md \
  --strict
```

The generated corpus manifest is written to `/tmp/bailian_no_upload_corpus_manifest.json` and must not be committed.

