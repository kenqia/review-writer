# Bailian Manual Success Record

## Conclusion

The Bailian cloud-side create/index/retrieve path is viable. A manual OpenAPI Explorer run succeeded after workspace membership and RAM permissions were corrected, and after avoiding an invalid `CreateIndex` rerank configuration.

This record is intentionally redacted. It does not store AccessKey values, signed URLs, headers, file ids, index ids, job ids, or workspace id values in the repository.

## Manual Success Facts

- CreateIndex: success
- SubmitIndexJob: success
- GetIndexJobStatus: `COMPLETED`
- Retrieve: success
- Retrieve `Data.Nodes`: non-empty
- Retrieved text contained: `review-writer Phase 6c smoke test`
- manual_index_id_present: true
- manual_job_id_present: true
- signed_url_present: true
- signed_url_redacted: true

## Root Causes

- Workspace membership / RAM permission was initially incomplete for the target Bailian business space.
- `CreateIndex` fails when an invalid `RerankMode` is explicitly passed.
- The code path should align with the manual success path rather than continuing blind endpoint/category probing.

## Code Alignment

- Default `CreateIndex` should omit `RerankMode`.
- Default `CreateIndex` should omit `RerankInstruct`.
- `RerankMode` may be sent only when explicitly configured.
- Allowed `RerankMode` values are `qa`, `similar`, and `custom`.
- `RerankInstruct` may be sent only when `RerankMode=custom`.
- Retrieve success must require non-empty nodes and the smoke fact `review-writer Phase 6c smoke test`.

## Safety Boundary

- No PDF upload.
- No raw image upload.
- No full markdown upload.
- Only the sanitized small payload may be uploaded in the controlled pilot.
- No Qwen, MinerU, or image API calls are involved.
- Resource ids may appear only in `/tmp` reports for cleanup, not in committed repo files.
