# Bailian RAG No-upload Preflight

## Conclusion

Phase 6a prepares a no-upload dry-run gate for a future Bailian RAG pilot. The clean 3-paper package can be transformed into a tiny corpus manifest for engineering inspection, but it remains untrusted for final scientific quality.

## Inputs

```text
demo_projects/clean_3paper_allene_review/
rag/bailian/preflight_config.example.yaml
evals/fixtures/rag_expected_questions.json
```

Only clean draft metadata, short claim drafts, short figure-note drafts, and warning fields are used.

## Outputs

```text
/tmp/bailian_rag_preflight.json
/tmp/bailian_rag_preflight.md
/tmp/bailian_no_upload_corpus_manifest.json
```

These outputs are temporary and must not be committed.

## Safety Boundary

- no PDF read
- no raw image read
- no raw MinerU markdown ingestion
- no full PDF text
- no Qwen call
- no Bailian API call
- no upload
- no knowledge-base creation
- no local absolute paths in the generated manifest
- no secret-like values in the generated manifest

## Checks

The preflight checker verifies:

- `mode: dry_run`
- `no_upload: true`
- selected corpus size is at most 3
- every item has `upload_status: not_uploaded`
- every item has `api_used: false`
- every item has `knowledge_base_created: false`
- every item keeps `needs_human_review: true`
- every item keeps `trusted_for_scientific_quality: false`
- P403 warning metadata is preserved

## Run

```bash
make bailian-rag-preflight-check
```

## Next

Phase 6b may run a small Bailian knowledge-base pilot only after explicit user authorization. It should still start with a single tiny corpus and a rollback/cleanup plan.

