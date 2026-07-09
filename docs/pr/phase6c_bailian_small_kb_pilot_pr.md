# Phase 6c: Bailian Small KB Pilot

## Summary

This phase adds the controlled small-KB pilot wrapper for Bailian RAG. The default path is still offline: build a sanitized `/tmp` payload, validate it, and dry-run the pilot wrapper without uploading or creating a KB.

Phase 6c-bis adds the official SDK-gated path for the Bailian KB API contract. The path checks official SDK modules and the required Alibaba Cloud credentials but does not perform a real upload in default checks.

## Added Files

```text
scripts/rag/build_bailian_small_kb_payload.py
scripts/rag/bailian_small_kb_pilot.py
review_writer/retrieval/bailian_official_client.py
tests/test_bailian_small_kb_payload.py
tests/test_bailian_small_kb_pilot_safety.py
docs/rag/bailian_small_kb_pilot_runbook.md
docs/rag/bailian_official_api_contract.md
docs/pr/phase6c_bailian_small_kb_pilot_pr.md
```

## Updated Files

```text
Makefile
README.md
docs/migration/05_incremental_pr_plan.md
```

## Gates

```bash
make bailian-small-kb-payload-check
make bailian-small-kb-pilot-dry-run
make bailian-small-kb-official-sdk-dry-run
```

## Result

- payload check: pass
- records: 3
- dry-run: pass
- real-mode wrapper: `blocked_manual_console_required`
- error type: `missing_dependency_or_api_contract`
- real API upload: not attempted
- automatic KB creation: not created
- official SDK dry-run: pass

## Safety

- No PDF upload.
- No raw image upload.
- No full markdown upload.
- No local absolute path upload.
- No secret output.
- No KB id committed to the repo.
- `trusted_for_scientific_quality=false` remains preserved.
- `DASHSCOPE_API_KEY` is not treated as sufficient for KB management.

## Next

Phase 6d should only proceed after either a successful manual console pilot or a reviewed API contract implementation for Bailian KB creation/retrieval.
