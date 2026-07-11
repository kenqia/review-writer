# Phase 6a: Bailian RAG No-upload Preflight

## Summary

This phase adds a dry-run Bailian RAG preflight gate. It builds a tiny no-upload corpus manifest from the clean 3-paper draft package and verifies that the manifest is safe to review before any real RAG pilot.

## Added Files

```text
rag/README.md
rag/bailian/README.md
rag/bailian/data_policy.md
rag/bailian/preflight_config.example.yaml
rag/bailian/no_upload_corpus_manifest.example.json
scripts/rag/bailian_preflight.py
tests/test_bailian_preflight.py
evals/fixtures/rag_expected_questions.json
docs/rag/bailian_rag_preflight.md
```

## Updated Files

```text
Makefile
README.md
docs/migration/05_incremental_pr_plan.md
```

## Gate

```bash
make bailian-rag-preflight-check
```

## Result

- status: pass
- selected_count: 3
- blocked_items: 0
- allowed_items: F3I, F47A, P403
- generated manifest: `/tmp/bailian_no_upload_corpus_manifest.json`

## Safety

- No network.
- No Bailian API.
- No Qwen API.
- No MinerU API.
- No upload.
- No knowledge-base creation.
- No PDF read.
- No raw images or full markdown are included in the generated manifest.
- `needs_human_review=true` and `trusted_for_scientific_quality=false` are preserved.

## Next

Phase 6b can be a small Bailian KB pilot only after explicit authorization, with a tiny corpus, no secret logging, and a cleanup plan.

