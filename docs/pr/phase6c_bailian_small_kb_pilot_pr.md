# Phase 6c: Bailian Small KB Pilot

## Summary

This phase adds the controlled small-KB pilot wrapper for Bailian RAG. The default path is still offline: build a sanitized `/tmp` payload, validate it, and dry-run the pilot wrapper without uploading or creating a KB.

Phase 6c-bis adds the official SDK-gated path for the Bailian KB API contract. Phase 6c-quad implements the official create/upload/index/retrieve lifecycle behind explicit real-run flags. Default checks still do not perform a real upload.

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
make bailian-small-kb-official-sdk-real-command
```

## Result

- payload check: pass
- records: 3
- dry-run: pass
- official SDK dry-run: pass
- official SDK real command: printed only by make target
- real API upload: gated behind `--allow-network --allow-upload --use-official-sdk`
- automatic KB creation in default checks: not created
- official SDK dry-run: pass

Authorized real pilot attempt:

- status: `fail`
- error type: `unexpected_error`
- safe summary: `UnretryableException`
- file/index/job id: not created
- retrieval: not run
- no retry was performed
- no cleanup required because no temporary index id was created

Phase 6c-quin adds a narrower diagnostic path:

- safe SDK exception forensics fields
- lease-only probe script
- dry-run make target
- real probe command print target
- no upload, no AddFile, no index creation, no retrieval
- no pre-signed URL or signed header output

Authorized lease-only probe result:

- status: `fail`
- error type: `endpoint_or_region_error`
- exception class: `UnretryableException`
- failed phase: `apply_file_upload_lease`
- operation: `ApplyFileUploadLease`
- lease obtained: `false`
- upload: not attempted
- knowledge base: not created

Phase 6c-six endpoint/region alignment:

- `--endpoint` added to official pilot and lease probe.
- `--region` added and defaults to `cn-beijing`.
- `--category-id` added and defaults to `default`.
- Default endpoint is the official example endpoint: `bailian.cn-beijing.aliyuncs.com`.
- `WORKSPACE_ID` remains the official SDK management workspace variable; `BAILIAN_WORKSPACE_ID` is not used for SDK management calls.
- If lease reprobe still fails, classify as workspace/permission, category, endpoint/region, request model, or auth/permission before any full pilot retry.

Authorized explicit-endpoint reprobe result:

- endpoint: `bailian.cn-beijing.aliyuncs.com`
- region: `cn-beijing`
- category_id: `default`
- status: `fail`
- error type: `endpoint_or_region_error`
- exception class: `UnretryableException`
- failed phase: `apply_file_upload_lease`
- lease obtained: `false`
- upload: not attempted
- knowledge base: not created

Phase 6c-sept transport diagnostics:

- Added unauthenticated endpoint diagnostics for DNS/TCP/TLS/HTTPS-root behavior.
- Added official-minimal `ApplyFileUploadLease` repro that bypasses project client wrappers.
- Minimal repro uses fixed dummy file metadata only and does not upload.
- SDK safe errors now include exception module, redacted repr/str, cause/context, arg count, and attribute-presence booleans.
- No default check uses credentials or uploads files.

Authorized Phase 6c-sept result:

- endpoint diagnostics: DNS/TCP/TLS pass for `bailian.cn-beijing.aliyuncs.com:443`
- HTTPS root probe: failed without status code, likely proxy or endpoint-root behavior
- minimal lease repro: `fail`
- error type: `transport_error`
- exception class: `UnretryableException`
- request id/status code: not present
- lease obtained: `false`
- upload: not attempted
- knowledge base: not created

Implemented official SDK lifecycle:

- ApplyFileUploadLease
- PUT upload to pre-signed URL
- AddFile
- DescribeFile until `PARSE_SUCCESS`
- CreateIndex
- SubmitIndexJob
- GetIndexJobStatus until `COMPLETED`
- Retrieve
- optional reviewed cleanup with `--cleanup --cleanup-index-id`

## Safety

- No PDF upload.
- No raw image upload.
- No full markdown upload.
- No local absolute path upload.
- No secret output.
- No KB id committed to the repo.
- `trusted_for_scientific_quality=false` remains preserved.
- `DASHSCOPE_API_KEY` is not treated as sufficient for KB management.
- KB/index ids are allowed only in `/tmp` reports, not in repo docs.
- Lease probe reports only presence booleans for lease id, upload URL, and headers.

## Next

Phase 6d should only proceed after the temporary KB/index is reviewed and cleaned up, and after retrieval metrics are judged useful enough for a larger real corpus pilot.
