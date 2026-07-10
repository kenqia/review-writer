# Bailian SDK Transport Matrix

## Conclusion

Phase 6c-oct narrows the Bailian failure to SDK transport behavior. Endpoint diagnostics already showed DNS/TCP/TLS reachability to `bailian.cn-beijing.aliyuncs.com:443`, while the SDK minimal lease repro failed without a service `request_id`. That means payload, PDF content, Qwen, MinerU, and RAG corpus quality are not the first suspects.

## What Changed

- Added SDK transport introspection for OpenAPI `Config` and Tea `RuntimeOptions`.
- Added transport modes for the minimal lease repro: `inherited_proxy`, `no_proxy`, and `explicit_proxy`.
- Added a matrix runner that performs at most three `ApplyFileUploadLease` attempts when explicitly allowed.
- Kept all default checks dry-run/offline.

The matrix never performs PUT upload, AddFile, CreateIndex, SubmitIndexJob, Retrieve, or knowledge-base creation.

## Introspection Result

The isolated `review-writer-bailian` conda environment can import the official SDK modules. Introspection reports that both OpenAPI `Config` and Tea `RuntimeOptions` expose proxy and timeout fields, so `explicit_proxy` is a valid diagnostic mode for this installed SDK.

## Interpreting The Matrix

- `no_proxy` succeeds: inherited proxy variables are likely polluting SDK transport.
- `inherited_proxy` succeeds: the normal shell environment is usable for SDK transport.
- `explicit_proxy` succeeds: the SDK needs explicit proxy/runtime fields instead of relying on inherited environment behavior.
- Any mode returns a service `request_id` but no lease: the request reached Bailian; next inspect RAM permission, workspace, category, or request model.
- No mode returns a service `request_id`: transport is still blocked; inspect conda SDK transport, proxy, TLS, or use a manual console pilot.

## Commands

Dry-run only:

```bash
make bailian-sdk-transport-introspection
make bailian-transport-matrix-dry-run
```

Print the reviewed real command:

```bash
make bailian-transport-matrix-real-command
```

The real command must be run only after explicit approval. It writes `/tmp` reports and must not be committed.

## Safety

- No PDF read.
- No raw image read.
- No Qwen, MinerU, or image API call.
- No upload or PUT.
- No AddFile, CreateIndex, SubmitIndexJob, Retrieve, or KB creation.
- No AccessKey, proxy URL, pre-signed URL, headers, Authorization, or `X-bailian-extra` output.

## Next Decision

If a working mode obtains a lease, the next step is one reviewed full pilot retry using that mode. If the matrix reaches the service but fails with a request id, fix permission/workspace/category/request fields. If the matrix remains transport-blocked, avoid full-pilot retries and either fix SDK/proxy transport or use a manual Bailian console pilot.

## Phase 6c-oct Real Matrix Result

One authorized real matrix was executed. It made at most one lease-only `ApplyFileUploadLease` attempt per mode and did not upload or create a knowledge base.

Safe summary:

- `inherited_proxy`: transport error before service request id
- `no_proxy`: service reached, request id present, status code `400`, error code `InvalidCategoryType`, no lease
- `explicit_proxy`: transport error before service request id
- working transport mode: none yet
- overall status: `service_reached`
- lease obtained: false
- upload attempted: false
- knowledge base created: false

Interpretation: process-local `no_proxy` reaches Bailian service, so the next issue is no longer pure endpoint reachability. The next fix should inspect `category_type` / `category_id` / SDK request contract before any full pilot retry.
