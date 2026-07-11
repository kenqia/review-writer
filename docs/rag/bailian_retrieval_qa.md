# Bailian Retrieval QA

## Conclusion

Phase 6d closed the prior Retrieve smoke-fact blocker with a bounded SDK retrieval matrix and a separate clean 3-paper retrieval QA lifecycle.

Safe latest evidence:

- smoke SDK lifecycle: pass
- smoke Retrieve nodes: non-empty
- smoke_fact_found: true
- working query: `review-writer Phase 6c smoke test`
- working retrieval mode: `official_minimal`
- root cause classification: `index_readiness_delay`
- clean 3-paper recall@1: `0.875`
- clean 3-paper recall@3: `1.0`
- clean 3-paper citation coverage: `1.0`
- missed questions: none
- smoke cleanup: pass for temporary index and file
- clean cleanup: pass for temporary index and file

Resource ids and signed URLs are intentionally absent from this document. They remain only in ignored `/tmp` run reports.

## Retrieve Contract

The installed official SDK supports these `RetrieveRequest` fields:

```text
query
index_id
dense_similarity_top_k
sparse_similarity_top_k
enable_reranking
rerank_top_n
rerank_min_score
enable_rewrite
save_retriever_history
```

The default smoke matrix uses only fields that introspection confirms. Default Make targets remain offline/dry-run.

## Matrix

The smoke matrix reuses one temporary smoke index and runs these queries:

- exact smoke fact
- project-name question
- smoke title query
- expected-answer question

It runs these modes when supported:

- `official_minimal`
- `hybrid_no_rerank`
- `sparse_exact_no_rerank`
- `dense_semantic_no_rerank`
- `rerank_qa`

The latest successful matrix had 20 query/mode results and 20 smoke-fact hits. One result needed a bounded readiness check on the same index, so the root cause classification is `index_readiness_delay`.

## Safety

- No PDF upload.
- No raw image upload.
- No full paper Markdown upload.
- No final draft upload.
- No Qwen, MinerU, or image API call.
- No secret, signed URL, `X-bailian-extra`, workspace id, file id, index id, or job id is committed.
- `trusted_for_scientific_quality=false` remains part of the clean payload and interpretation.

## Gates

```bash
make bailian-retrieval-contract-check
make bailian-retrieval-qa-dry-run
make bailian-phase6-final-check
```

The real SDK lifecycle remains explicit and writes reports only under `/tmp`.
