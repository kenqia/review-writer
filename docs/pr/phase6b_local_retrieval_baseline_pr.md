# Phase 6b: Local Retrieval Baseline

## Summary

This phase adds an offline retrieval sanity check for the Phase 6a no-upload Bailian RAG corpus manifest. It verifies that simple local retrieval can recover the intended clean 3-paper records before any real Bailian KB pilot.

## Added Files

```text
scripts/rag/local_retrieval_baseline.py
tests/test_local_retrieval_baseline.py
evals/baselines/rag_local_retrieval_v1.yaml
evals/fixtures/rag_expected_metrics.json
docs/rag/local_retrieval_baseline.md
docs/pr/phase6b_local_retrieval_baseline_pr.md
```

## Updated Files

```text
Makefile
README.md
docs/rag/bailian_rag_preflight.md
docs/migration/05_incremental_pr_plan.md
evals/fixtures/rag_expected_questions.json
scripts/rag/bailian_preflight.py
rag/bailian/no_upload_corpus_manifest.example.json
```

## Gate

```bash
make rag-local-retrieval-check
```

## Current Result

- local retrieval status: pass
- recall@1: 0.8125
- recall@3: 1.0
- citation coverage: 1.0
- missed questions: none
- recommendation: proceed_to_bailian_pilot

## Safety

- No network.
- No Qwen API.
- No Bailian API.
- No MinerU API.
- No upload.
- No knowledge-base creation.
- No PDF read.
- `trusted_for_scientific_quality=false` remains preserved.

## Next

Phase 6c can begin only after the user explicitly authorizes a small Bailian KB pilot and confirms what data may be uploaded.

