# Bailian Small KB Pilot Runbook

## Conclusion

Phase 6c prepares a controlled small-KB pilot path. The repo can build a sanitized payload and dry-run the pilot wrapper. Default checks do not upload, create a knowledge base, or call Bailian APIs.

Phase 6c-bis and Phase 6c-quad add an official SDK-gated path. It checks official SDK dependencies and official KB-management environment variables, then can run the official upload/index/retrieve lifecycle only after the user explicitly authorizes `allow official bailian sdk pilot` and the command includes `--allow-network --allow-upload --use-official-sdk`.

## Uploaded Fields Allowed

Only the following fields may be uploaded in a future manual or API-backed pilot:

- `paper_id`
- `title`
- `year`
- `journal`
- `doi_draft`
- `role`
- `claim_draft`
- `figure_note_draft`
- `known_warnings`
- `needs_human_review=true`
- `trusted_for_scientific_quality=false`

The generated payload packages these into compact JSONL records with:

- `compact_text`
- `metadata`
- `upload_scope=small_kb_pilot`

## Not Uploaded

- PDFs
- raw images or figures
- full MinerU markdown
- full PDF text
- local absolute paths
- API keys, tokens, auth files, or secrets
- complete `final_draft.md`
- long untrimmed excerpts

## Commands

Dry-run gates:

```bash
make bailian-small-kb-payload-check
make bailian-small-kb-pilot-dry-run
make bailian-small-kb-official-sdk-dry-run
make bailian-small-kb-official-sdk-real-command
```

Controlled real-mode wrapper using the official SDK:

```bash
python scripts/rag/build_bailian_small_kb_payload.py \
  --clean-root demo_projects/clean_3paper_allene_review \
  --output-jsonl /tmp/bailian_small_kb_payload.jsonl \
  --output-md /tmp/bailian_small_kb_payload.md \
  --output-manifest /tmp/bailian_small_kb_payload_manifest.json \
  --strict

python scripts/rag/bailian_small_kb_pilot.py \
  --payload-jsonl /tmp/bailian_small_kb_payload.jsonl \
  --questions evals/fixtures/rag_expected_questions.json \
  --output-json /tmp/bailian_small_kb_pilot_real.json \
  --output-md /tmp/bailian_small_kb_pilot_real.md \
  --endpoint bailian.cn-beijing.aliyuncs.com \
  --region cn-beijing \
  --category-id default \
  --transport-mode no_proxy \
  --allow-network \
  --allow-upload \
  --use-official-sdk \
  --cleanup \
  --strict
```

This command must not be run until the user replies exactly:

```text
allow official bailian sdk pilot
```

The real path performs:

- ApplyFileUploadLease
- PUT upload of `/tmp/bailian_small_kb_upload_payload.md`
- AddFile
- DescribeFile until `PARSE_SUCCESS`
- CreateIndex
- SubmitIndexJob
- GetIndexJobStatus until `COMPLETED`
- Retrieve over `evals/fixtures/rag_expected_questions.json`
- Retrieve smoke fact check for `review-writer Phase 6c smoke test`
- Best-effort cleanup of created index/file resources when `--cleanup` is supplied
- recall@1, recall@3, and citation coverage calculation
- upload integrity telemetry without exposing full MD5, signed URL, or signed headers
- parse failure diagnostics without exposing file ids or downloaded parse result URLs

## KB ID Policy

KB ids must not be written to the repo. If a real or manual pilot creates a KB, record the id only in `/tmp` output files and delete the KB after evaluation.

## Phase 6c-quad Real Pilot Note

One authorized official SDK pilot was attempted after the implementation was added. The result was:

- status: `fail`
- error_type: `unexpected_error`
- safe summary: `UnretryableException`
- file_id/index_id/job_id: not created
- retrieval: not run
- temporary KB/index cleanup: not required

No retry was performed. No key value was printed, no PDF or raw image was uploaded, and no KB/index id was written to the repo.

## Phase 6c-final Manual Success Alignment

Manual OpenAPI Explorer validation proved the cloud-side path can succeed:

- CreateIndex: success
- SubmitIndexJob: success
- GetIndexJobStatus: `COMPLETED`
- Retrieve: success
- Retrieve nodes: non-empty
- Retrieved text contained `review-writer Phase 6c smoke test`

The manual success record is kept in `docs/rag/bailian_manual_success_record.md` with resource ids and signed URLs redacted.

Code alignment rules:

- Default `CreateIndex` omits `RerankMode`.
- Default `CreateIndex` omits `RerankInstruct`.
- Default `CreateIndex` uses `sink_type=BUILT_IN` for the current official contract. Older `DEFAULT` references are historical.
- `RerankMode` is sent only when explicitly configured as `qa`, `similar`, or `custom`.
- `RerankInstruct` is sent only when `RerankMode=custom`.
- Upload uses the method and upload headers returned by `ApplyFileUploadLease` instead of hard-coded `PUT` plus guessed content type.
- Retrieve succeeds only when nodes are non-empty and the smoke fact is found.

## Phase 6c-final Controlled SDK Pilot Result

After aligning the code with the manual success path, one controlled official SDK pilot was executed with the sanitized small payload and `--cleanup`.

Safe summary:

- lease: pass
- upload: pass
- AddFile: pass
- DescribeFile/parse: fail
- CreateIndex: skipped
- SubmitIndexJob: skipped
- GetIndexJobStatus: skipped
- Retrieve: skipped
- error_type: `parse_failed`
- safe summary: `parse status PARSE_FAILED`
- cleanup_attempted: true
- index_cleanup: not_created
- file_cleanup: fail
- created_resource_ids_cleaned: no

Interpretation: the manual success proves the cloud path can work, and the code now matches the rerank/current-index contract. The remaining automated SDK blocker is now file parsing for the sanitized payload, plus cleanup verification for the temporary file resource. Resource ids, if needed for cleanup, are only in `/tmp/bailian_small_kb_pilot_real.json`.

## Phase 6c-final-bis Parse Failure Parity

`docs/rag/bailian_manual_success_parity.md` compares the manual success path with the SDK automated path.

Current SDK automation result:

- lease/upload/AddFile pass
- parse fails with `PARSE_FAILED`
- CreateIndex/SubmitIndexJob/Retrieve are skipped correctly
- cleanup is attempted
- temporary file cleanup failed
- manual_file_cleanup_required: true

The upload markdown is now generated as a minimal smoke-test document with:

- H1 title
- `## Purpose`
- `## Test Facts`
- explicit `Project name: review-writer Phase 6c smoke test.`
- no PDF, raw image, full paper Markdown, secrets, tokens, API keys, or private data

Use `make bailian-payload-parse-readiness-check` before any future real pilot.

Phase 6 closure adds a stricter SDK parity path:

- immutable upload artifact snapshot before lease
- lease-provided method and headers honored during binary upload
- no guessed `Content-Type` when the lease omits it
- Markdown and TXT smoke payload candidates
- `DescribeFile` parse diagnostics and parse failure classification
- orphan file cleanup-only command that reads ids only from `/tmp` and never prints them
- `make bailian-sdk-e2e-closure-check`

## Phase 6 Closure Controlled SDK Results

Three evidence-backed upload-capable attempts were used for closure, with cleanup-only calls between attempts:

1. Hardened upload contract attempt: lease, upload, AddFile, and parse passed; CreateIndex failed because the automation did not parse the returned index id shape.
2. CreateIndex id-shape attempt: lease, upload, AddFile, and parse passed; CreateIndex still returned a 400 response without a parsed id. The next evidence-backed fix was the official 1-20 character `Name` limit.
3. Short-name attempt: lease, upload, AddFile, parse, CreateIndex, SubmitIndexJob, and index job completion reached retrieval; Retrieve returned nodes but did not hit the required smoke fact.

Cleanup after the final attempt:

- index_id_present: true
- file_id_present: true
- index_cleanup: pass
- file_cleanup: pass
- created_resource_ids_cleaned: yes

Current status:

```text
Phase 6 engineering prerequisites complete;
Bailian SDK automation incomplete at Retrieve smoke fact validation.
```

Do not call Phase 6c complete until Retrieve nodes are non-empty and at least one node text contains `review-writer Phase 6c smoke test`.

## Phase 6c-quin Lease-only Probe

The next diagnostic step is intentionally smaller than the full pilot. It calls only `ApplyFileUploadLease` and stops before any PUT upload, `AddFile`, `CreateIndex`, `SubmitIndexJob`, or retrieval call.

Dry-run:

```bash
make bailian-lease-probe-dry-run
make bailian-lease-probe-real-command
```

Real lease-only probe, after explicit authorization:

```bash
zsh -ic 'cd <REPO_ROOT> && conda run -n review-writer-bailian python scripts/rag/bailian_lease_probe.py \
  --payload-md /tmp/bailian_small_kb_upload_payload.md \
  --output-json /tmp/bailian_lease_probe_real.json \
  --output-md /tmp/bailian_lease_probe_real.md \
  --endpoint bailian.cn-beijing.aliyuncs.com \
  --region cn-beijing \
  --category-id default \
  --allow-network \
  --use-official-sdk \
  --strict'
```

The report includes `safe_error`, `first_failed_phase`, `operation_name`, and `recommended_fix`. It never writes the lease id, pre-signed URL, signed headers, or key values.

The authorized Phase 6c-quin probe failed safely at `ApplyFileUploadLease` with `endpoint_or_region_error` / `UnretryableException`. No lease was obtained, no upload was attempted, and no knowledge base was created. Fix endpoint/region alignment before considering a full pilot retry.

Phase 6c-six adds explicit endpoint, region, and category parameters. The default endpoint is the official example endpoint `bailian.cn-beijing.aliyuncs.com`; if `BAILIAN_REGION` differs from the selected region, the report emits a warning but keeps the explicit endpoint.

The authorized Phase 6c-six reprobe used `bailian.cn-beijing.aliyuncs.com`, `cn-beijing`, and `default`. It still failed safely at `ApplyFileUploadLease` with `endpoint_or_region_error` / `UnretryableException`, before any lease, upload, or KB creation. Do not retry the full pilot until endpoint reachability, workspace-region binding, and SDK endpoint expectations are checked.

## Manual Cleanup

If a temporary KB is created manually or by the official SDK pilot:

1. Read the temporary index id only from `/tmp/bailian_small_kb_pilot_real.json`.
2. Delete it in the Bailian console, or run the reviewed cleanup command with both `--cleanup` and `--cleanup-index-id`.
3. Export or save only non-secret evaluation metrics if needed.
4. Confirm no PDFs, raw images, or full markdown were uploaded.

## Phase 6d Readiness

Proceed only if:

- sanitized payload check passes
- local retrieval baseline passes
- small-KB retrieval can recover expected paper IDs
- no secrets or raw files are uploaded
- clean 3-paper corpus remains not scientifically verified
