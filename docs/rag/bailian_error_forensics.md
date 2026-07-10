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

## Endpoint / Region / Category

Phase 6c-six makes the probe parameters explicit:

```bash
--endpoint bailian.cn-beijing.aliyuncs.com
--region cn-beijing
--category-id default
```

Resolution rules:

1. `--endpoint` wins.
2. Without `--endpoint`, `--region` builds `bailian.<region>.aliyuncs.com`.
3. Without either value, the default is `cn-beijing`.
4. If `BAILIAN_REGION` differs from the selected region, reports warn and keep using the explicit endpoint.

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

- `auth_or_permission_error`: verify AccessKey status, RAM permissions, and workspace access.
- `workspace_or_permission_error`: check `WORKSPACE_ID`, business-space membership, and RAM permissions.
- `category_error`: check whether the `default` category exists or whether the workspace expects another category id.
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

## Phase 6c-six Explicit Endpoint Reprobe

One authorized reprobe was executed with:

```text
endpoint: bailian.cn-beijing.aliyuncs.com
region: cn-beijing
category_id: default
```

The safe result was:

- status: `fail`
- error_type: `endpoint_or_region_error`
- exception_class: `UnretryableException`
- first_failed_phase: `apply_file_upload_lease`
- operation_name: `ApplyFileUploadLease`
- request_id: not present
- lease_obtained: `false`
- upload attempted: `false`
- knowledge base created: `false`

Since the explicit official endpoint still failed before a lease was obtained, do not retry the full pilot. Next debugging should check network/proxy reachability to the Bailian OpenAPI endpoint, account-region/workspace binding, and whether the installed SDK expects another endpoint form for this account.

## Phase 6c-sept Transport Split

Phase 6c-sept separates the problem into two smaller questions:

1. Is `bailian.cn-beijing.aliyuncs.com:443` reachable from WSL/conda at DNS, TCP, and TLS layers?
2. Does the official SDK minimal `ApplyFileUploadLeaseRequest` fail with a service response or before a service response?

The endpoint diagnostics are unauthenticated and do not call Bailian business APIs. The minimal lease repro uses only fixed dummy file metadata and does not upload.

Decision rule:

- DNS/TCP/TLS failure: fix WSL/conda/proxy/DNS/TLS first.
- DNS/TCP/TLS success + SDK failure without request id: inspect proxy/SDK endpoint transport or endpoint form.
- SDK failure with request id: inspect RAM permission, workspace, category, or request model.
- SDK lease success: only then consider a reviewed full pilot retry.

## Phase 6c-sept Real Result

Endpoint diagnostics showed DNS/TCP/TLS success against `bailian.cn-beijing.aliyuncs.com:443`. The unauthenticated HTTPS root probe failed without a status code, likely because of proxy or endpoint root behavior.

The official minimal lease repro still failed before a service response:

- status: `fail`
- error_type: `transport_error`
- exception_class: `UnretryableException`
- request_id: not present
- status_code: not present
- lease_obtained: `false`
- upload attempted: `false`
- knowledge base created: `false`

This argues against payload/PDF/Qwen/MinerU causes. The next hypothesis is SDK transport/proxy handling or endpoint form used by the official SDK in this conda environment.

## Phase 6c-oct Proxy / Transport Matrix

The next diagnostic step compares SDK behavior across three modes:

- inherited proxy environment
- process-local no-proxy environment
- explicit SDK proxy/runtime fields

The installed SDK exposes proxy and timeout fields on both OpenAPI `Config` and Tea `RuntimeOptions`, so explicit proxy mode is supported by this local SDK contract.

The real matrix is limited to three `ApplyFileUploadLease` attempts, one per mode. It does not upload, add files, create indexes, submit jobs, retrieve, or create a knowledge base. Reports include only safe fields such as mode, status, error category, exception class, service request-id presence, status code, error code, and whether a lease was obtained.

If no mode obtains a request id, the working hypothesis remains transport/proxy/runtime failure rather than RAM/workspace/category. If any mode obtains a request id, the investigation moves up to Bailian service-side authorization or request validation.

Authorized Phase 6c-oct matrix result:

- inherited proxy: transport error, no request id
- no proxy: service reached, status code `400`, error code `InvalidCategoryType`, request id present
- explicit proxy: transport error, no request id
- no lease obtained
- no upload attempted
- no knowledge base created

This shifts the next debugging target to category or request-model alignment while using `no_proxy` as the working service-reachability mode.

## Phase 6c-nov Category Discovery

The SDK exposes `ListCategoryRequest` and `list_category_with_options`. Category discovery is therefore the correct next diagnostic before any upload-capable retry.

Rules:

- Use `no_proxy`, because it is the only mode that reached the service.
- Call only `ListCategory`.
- If discovery returns a recommended category, run one `ApplyFileUploadLease` reprobe with that category id/type.
- If discovery returns no category, use Bailian console to create or select a valid document-search category.
- Do not run full pilot until lease reprobe succeeds.

The first real `ListCategory` attempt reached the service and returned `MissingCategoryType`, with no upload or KB creation. This narrows the next step to finding the valid `category_type` value required by the current Bailian API/workspace contract.
