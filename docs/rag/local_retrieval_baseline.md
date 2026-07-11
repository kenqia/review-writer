# Local Retrieval Baseline

## Conclusion

Phase 6b adds an offline sanity check before any Bailian knowledge-base pilot. The local retriever verifies that the clean 3-paper no-upload corpus can recover expected records for simple RAG-style questions.

## Why This Exists

Before uploading anything to a managed RAG service, the corpus should pass a local retrieval sanity check. This catches obvious problems such as missing warning fields, weak query coverage, or a manifest that cannot retrieve the intended paper IDs.

## Inputs

```text
/tmp/bailian_no_upload_corpus_manifest.json
evals/fixtures/rag_expected_questions.json
evals/fixtures/rag_expected_metrics.json
```

If the manifest is missing, the checker runs the Phase 6a no-upload preflight locally to regenerate it.

## Metrics

- `recall@1`: average fraction of expected paper IDs found in the top 1 result.
- `recall@3`: average fraction of expected paper IDs found in the top 3 results.
- `citation coverage`: fraction of questions whose expected paper IDs are all available in top 3 when citation is required.

## Current Result

- local retrieval status: pass
- recall@1: 0.8125
- recall@3: 1.0
- citation coverage: 1.0
- missed questions: none

## Safety Boundary

- no network
- no Qwen call
- no Bailian API call
- no MinerU API call
- no upload
- no knowledge-base creation
- no PDF read
- `trusted_for_scientific_quality` remains false

## Limits

The local retriever uses lowercase token matching with weighted fields. It is a sanity check, not a substitute for real Bailian retrieval evaluation or human scientific review.

## Next

Phase 6c may run a small Bailian KB pilot only after explicit user authorization:

```text
allow bailian small kb pilot
```

