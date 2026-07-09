# Bailian SDK Error Forensics

## Conclusion

The previous full official SDK pilot failed before a file, index, or job id was created. Phase 6c-quin therefore does not retry the full flow. It narrows the blast radius to a lease-only probe that stops after `ApplyFileUploadLease`.

## Why No Blind Retry

A full retry can accidentally move past the failing call and upload a sanitized payload, add a file, create an index, or require cleanup. The safer diagnostic order is:

1. Check SDK/env gates.
2. Build the sanitized `/tmp` payload.
3. Run one `ApplyFileUploadLease` probe.
4. Inspect only safe error fields.
5. Fix auth/workspace/category/endpoint/request model before any full pilot retry.

## What The Probe Does

The lease-only probe performs only:

```text
create_client
calculate_md5
get_file_size
ApplyFileUploadLease
```

It does not perform:

```text
PUT upload
AddFile
DescribeFile
CreateIndex
SubmitIndexJob
Retrieve
DeleteIndex
```

## Safe Fields

Reports may include:

- `exception_class`
- `error_code`
- `status_code`
- `request_id` presence or value when returned by the SDK
- `message_redacted`
- `data_keys`
- `endpoint`
- `operation_name`
- `first_failed_phase`
- `recommended_fix`

Reports must not include:

- AccessKey values
- signed headers
- pre-signed URL
- `Authorization`
- `X-bailian-extra`
- raw request body

## Interpreting Errors

- `auth_error_401`: verify AccessKey status and permissions.
- `access_denied_workspace`: grant the principal access to the Bailian workspace.
- `invalid_workspace`: check `WORKSPACE_ID` and endpoint region alignment.
- `invalid_category`: check `category_id` and category type.
- `invalid_request_model`: compare request fields with the installed SDK version and the official API guide.
- `endpoint_or_region_error`: verify `bailian.cn-beijing.aliyuncs.com` or the selected regional endpoint.
- `unexpected_error`: inspect `safe_error` and avoid full retry until the failing phase is understood.

## Next Decision

If lease succeeds, the next reviewed step may be one full pilot retry. If lease fails, fix the issue indicated by `safe_error.recommended_fix` before any upload-capable run.

## Phase 6c-quin Real Probe Result

One authorized lease-only probe was executed. The safe result was:

- status: `fail`
- error_type: `endpoint_or_region_error`
- exception_class: `UnretryableException`
- first_failed_phase: `apply_file_upload_lease`
- operation_name: `ApplyFileUploadLease`
- request_id: not present
- lease_obtained: `false`
- upload attempted: `false`
- knowledge base created: `false`

Recommended next fix: verify endpoint and `BAILIAN_REGION` alignment before any full pilot retry.
