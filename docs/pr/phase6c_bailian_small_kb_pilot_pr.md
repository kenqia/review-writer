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

Phase 6c-oct SDK proxy / transport matrix:

- Added SDK transport introspection for OpenAPI `Config` and Tea `RuntimeOptions`.
- Added `inherited_proxy`, `no_proxy`, and `explicit_proxy` modes to the minimal lease repro.
- Added a dry-run transport matrix target and a real-command print target.
- Introspection in `review-writer-bailian` shows proxy and timeout fields are available on both Config and RuntimeOptions.
- The real matrix is limited to at most three `ApplyFileUploadLease` attempts.
- The matrix still does not upload, AddFile, CreateIndex, SubmitIndexJob, Retrieve, or create a knowledge base.

Authorized Phase 6c-oct result:

- inherited proxy: transport error, no request id
- no proxy: service reached with request id, status code `400`, error code `InvalidCategoryType`
- explicit proxy: transport error, no request id
- no lease obtained
- no upload attempted
- no knowledge base created
- next target: category/request-model alignment under no-proxy mode

Phase 6c-nov category discovery:

- Added SDK category introspection for `ListCategoryRequest` and `list_category_with_options`.
- Added dry-run category discovery.
- Added `--category-id-from` to the minimal lease repro so the next reprobe can consume `recommended_category_id`.
- Discovery uses `no_proxy`, because that is the only transport mode that reached Bailian service.
- Discovery is read-only and does not call ApplyFileUploadLease, upload, AddFile, CreateIndex, SubmitIndexJob, Retrieve, or create a knowledge base.

Authorized Phase 6c-nov discovery result:

- `ListCategory` reached service with request id.
- status code: `400`
- error code: `MissingCategoryType`
- categories returned: `0`
- no recommended category yet
- no lease reprobe was executed
- no upload or KB creation
- next target: confirm valid `category_type` values, then rerun ListCategory with an explicit category type

Phase 6c-deepfix category type autodiscovery:

- SDK source confirms `category_type` is serialized as `CategoryType`.
- SDK source comments and official docs identify `UNSTRUCTURED` and `SESSION_FILE`; knowledge-base/application-data flow should use `UNSTRUCTURED`.
- Added category type matrix over conservative candidates, using `ListCategory` only.
- Default SDK wrapper category type changed from invalid `document` to official `UNSTRUCTURED`.
- Full pilot remains blocked until a lease-only reprobe succeeds.

Authorized Phase 6c-deepfix matrix result:

- `UNSTRUCTURED`: accepted by `ListCategory`, but returned zero categories.
- `SESSION_FILE`, `DOCUMENT`, `DATA_CENTER_FILE`, `DATA_CENTER_CATEGORY`, and `DEFAULT`: rejected with `InvalidCategoryType`.
- `INDEX` and `KNOWLEDGE_BASE`: rejected with `Throttling.Api`.
- no recommended category id was discovered
- no lease-only reprobe was executed
- no upload, AddFile, index, Retrieve, or knowledge base creation occurred
- next target: create/select a Bailian console category, then run one lease-only reprobe with `UNSTRUCTURED`

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

Phase 6c-final manual success alignment:

- Manual OpenAPI Explorer run proved CreateIndex, SubmitIndexJob, GetIndexJobStatus, and Retrieve can succeed.
- Retrieved nodes were non-empty and contained `review-writer Phase 6c smoke test`.
- Root cause 1: workspace membership / RAM permission was initially incomplete.
- Root cause 2: explicit invalid `RerankMode` breaks CreateIndex.
- Code now defaults to no `RerankMode` and no `RerankInstruct`.
- `RerankMode` is allowed only when explicitly set to `qa`, `similar`, or `custom`.
- `RerankInstruct` is allowed only when `RerankMode=custom`.
- Retrieve success now checks non-empty nodes and the smoke fact.
- Resource ids and signed URLs remain out of repo docs; `/tmp` reports are the only place for ids needed for cleanup.

Controlled Phase 6c-final SDK pilot result:

- lease: pass
- upload: pass
- AddFile: pass
- parse: fail with `parse_failed` / `PARSE_FAILED`
- CreateIndex / SubmitIndexJob / Retrieve: skipped
- cleanup attempted: true
- index cleanup: not_created
- file cleanup: fail
- no PDF, raw image, or full markdown was uploaded
- no signed URL, header, or key was printed

This means the original workspace/RAM and rerank blockers are no longer the observed automation blocker. The next investigation should focus on parser configuration or payload file type for the sanitized markdown payload, and on manual cleanup of the temporary file resource using the id stored only in `/tmp`.

Phase 6c-final-bis parse-failure parity:

- Added manual-vs-SDK parity documentation.
- Added payload parse readiness checker and test.
- Updated the generated upload markdown to a minimal smoke document.
- Parser status handling now reports `parse_status`, `parse_error_present`, and `skipped_because_upstream_parse_failed`.
- Cleanup reports now expose `file_id_present`, `cleanup_error_type`, and `manual_cleanup_required` without printing ids.
- Downstream CreateIndex/Retrieve remain skipped when parse fails; this is expected and safe.

Phase 6 closure autonomous root-cause hardening:

- Added upload artifact immutability before `ApplyFileUploadLease`.
- Upload now uses the lease-returned method and only lease-returned upload headers.
- Added safe upload telemetry: lease file name, byte size, MD5 prefix, method source, header presence, uploaded byte count, and post-upload local MD5 match.
- Changed current default `CreateIndex` sink contract to `BUILT_IN`; older `DEFAULT` references are historical.
- Added `DescribeFile` parse diagnostics and parse-failure classification.
- Added Markdown and TXT smoke payload candidates for a controlled A/B parse test.
- Added `scripts/rag/bailian_cleanup_orphan_file.py` for cleanup-only `DeleteFile` from `/tmp` reports without printing ids.
- Added `make bailian-sdk-e2e-closure-check`.

Completion standard:

- Phase 6c is complete only if the SDK automated pilot passes lease, upload, AddFile, parse, CreateIndex, SubmitIndexJob, GetIndexJobStatus, Retrieve with non-empty nodes, smoke fact match, and cleanup.
- If parse or cleanup still fails, write `Phase 6 engineering prerequisites complete; Bailian SDK automation incomplete at <stage>`.

Closure result:

- Attempt 1 fixed upload integrity but exposed CreateIndex id parsing.
- Attempt 2 fixed id parsing but exposed the official `Name` length contract.
- Attempt 3 fixed the short-name contract and reached Retrieve.
- Final blocker: Retrieve smoke fact assertion failed.
- Cleanup-only command successfully deleted both the temporary index and application-data file.
- Current correct status: `Phase 6 engineering prerequisites complete; Bailian SDK automation incomplete at Retrieve smoke fact validation.`

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
- Signed URLs and lease upload headers are never written to repo docs.
- Orphan cleanup reports only id presence and cleanup status, never the id value.

## Phase 6d Closure

Phase 6d completed the retrieval QA closure:

- Added Retrieve contract introspection.
- Added robust dict/object and PascalCase/snake_case response parsing.
- Added normalized smoke fact matching from node text and `Metadata.content`.
- Added retrieval query/mode matrix dry-run and real lifecycle support.
- Added clean 3-paper compact retrieval QA support.
- Added `make bailian-retrieval-contract-check`, `make bailian-retrieval-qa-dry-run`, and `make bailian-phase6-final-check`.

Safe latest real results:

- smoke lifecycle: pass
- working query: `review-writer Phase 6c smoke test`
- working mode: `official_minimal`
- root cause classification: `index_readiness_delay`
- clean 3-paper recall@1: `0.875`
- clean 3-paper recall@3: `1.0`
- clean 3-paper citation coverage: `1.0`
- missed questions: none
- cleanup: pass for both smoke and clean lifecycles

One interrupted experimental matrix run produced no `/tmp` report before termination, so there is no local resource id to clean from that run. Later successful smoke and clean lifecycles both cleaned their created temporary index/file resources.
