# review-writer

`review-writer` is an offline-first workflow scaffold for chemistry review writing, QoderWork skill orchestration, deterministic quality gates, provider adapters, and demo/eval harnesses.

Core safety boundary:

- generated paper libraries, PDFs, MinerU outputs, local project outputs, and secrets are external data
- default checks do not call Qwen, DashScope, MinerU, Bailian, image APIs, or upload files
- `.env` files and real provider keys must not be committed

Useful gates:

```bash
make release-readiness-check
make clean-3paper-e2e-check
make clean-3paper-eval-check
make dashboard-clean-3paper-check
make bailian-rag-preflight-check
make rag-local-retrieval-check
make bailian-small-kb-payload-check
make bailian-small-kb-pilot-dry-run
make bailian-small-kb-official-sdk-dry-run
```

## Bailian RAG No-upload Preflight

Phase 6a adds a dry-run preflight for a future Bailian RAG pilot. It only builds and checks a small corpus manifest from `demo_projects/clean_3paper_allene_review`; it does not upload data, create a knowledge base, call Bailian, call Qwen, or read PDFs.

Run:

```bash
make bailian-rag-preflight-check
```

The generated manifest is written to `/tmp/bailian_no_upload_corpus_manifest.json` and is intentionally not committed. A real Bailian pilot remains blocked until explicit user authorization in a later phase.

Phase 6b adds an offline local retrieval sanity check over that manifest:

```bash
make rag-local-retrieval-check
```

This check uses token matching only. It does not call Bailian, create a knowledge base, call Qwen, upload files, or mark the clean 3-paper draft as scientifically verified.

Phase 6c adds dry-run gates for a possible Bailian small-KB pilot. Default make targets only build a sanitized `/tmp` payload and verify the pilot wrapper; they do not upload data or create a knowledge base.

Official Bailian KB management uses Alibaba Cloud SDK credentials (`ALIBABA_CLOUD_ACCESS_KEY_ID`, `ALIBABA_CLOUD_ACCESS_KEY_SECRET`, `WORKSPACE_ID`), not only `DASHSCOPE_API_KEY`. The official SDK path is gated behind `--use-official-sdk` plus explicit network/upload flags and stays dry-run in default checks.
