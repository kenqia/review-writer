# Bailian Transport Diagnostics

## Conclusion

The previous lease probes failed before receiving a service `request_id`, status code, or error code. That points first to transport, endpoint, proxy, or SDK endpoint behavior rather than review payload content. Phase 6c-sept adds two smaller checks before any full pilot retry.

## Checks

### Endpoint Diagnostics

`scripts/rag/bailian_endpoint_diagnostics.py` performs unauthenticated transport checks:

- DNS resolve
- TCP connect to port 443
- TLS handshake and certificate summary
- HTTPS HEAD/GET-style root probe
- proxy environment presence by variable name only
- Python executable and conda env name

It does not read keys, send credentials, upload files, or call a Bailian business API.

### Minimal Lease Repro

`scripts/rag/bailian_minimal_lease_repro.py` mirrors the official first SDK call as closely as possible:

- create OpenAPI config with endpoint
- instantiate official Bailian client
- create `ApplyFileUploadLeaseRequest`
- call `apply_file_upload_lease_with_options`

It uses fixed dummy file metadata only. It does not PUT upload, AddFile, CreateIndex, SubmitIndexJob, Retrieve, or create a knowledge base.

## Interpretation

- If endpoint diagnostics fail at DNS/TCP/TLS: fix WSL, conda, proxy, DNS, or certificate trust.
- If endpoint diagnostics pass but minimal lease repro fails without `request_id`: inspect proxy/SDK transport and endpoint form.
- If minimal lease repro fails with `request_id`: investigate RAM permissions, workspace binding, category id, or request model.
- If minimal lease repro succeeds: a reviewed full pilot retry may be considered.

## Current Real Diagnostics

The authenticated-free endpoint diagnostics reached DNS/TCP/TLS successfully for:

```text
bailian.cn-beijing.aliyuncs.com:443
```

The HTTPS root probe may still fail depending on proxy or endpoint root behavior, but DNS/TCP/TLS success means basic transport to the host is available.

The official minimal lease repro must still be interpreted separately because it exercises SDK signing and workspace/category parameters.

## Phase 6c-sept Real Result

Endpoint diagnostics:

- dns_status: `ok`
- tcp_status: `ok`
- tls_status: `ok`
- https_status: `https_failed`
- https_status_code: `None`
- proxy env: present by variable name

Interpretation: basic DNS/TCP/TLS transport to `bailian.cn-beijing.aliyuncs.com:443` is available. The HTTPS root probe failure is likely proxy behavior or endpoint root behavior and is not by itself evidence that the SDK request is malformed.

Official minimal lease repro:

- status: `fail`
- error_type: `transport_error`
- exception_class: `UnretryableException`
- request_id: not present
- status_code: not present
- lease_obtained: `false`
- upload attempted: `false`
- knowledge base created: `false`

Interpretation: because the minimal SDK request still fails before a service `request_id`, the next step is to inspect conda/SDK proxy transport behavior or SDK endpoint expectations before changing workspace/category/request payload assumptions.

## Phase 6c-oct Transport Matrix

Phase 6c-oct adds a matrix over three SDK transport modes:

- `inherited_proxy`: leave proxy environment behavior unchanged.
- `no_proxy`: clear proxy environment variables only inside the current child process.
- `explicit_proxy`: read a proxy URL from the selected env variable and pass it through SDK `Config`/`RuntimeOptions` fields if the installed SDK exposes those fields.

SDK introspection in the isolated `review-writer-bailian` conda environment reports proxy and timeout support on both OpenAPI `Config` and Tea `RuntimeOptions`.

The matrix still stops at `ApplyFileUploadLease`. It never performs PUT upload, AddFile, CreateIndex, SubmitIndexJob, Retrieve, or knowledge-base creation.

Decision rules:

- A lease in any mode means the SDK transport path works in that mode.
- A request id without a lease means the service was reached and the next investigation should focus on permission, workspace, category, or request model.
- No request id in all modes means transport/proxy/TLS/SDK runtime remains the likely blocker.

Real matrix result: `no_proxy` reached the service and returned `InvalidCategoryType` with status code `400`; inherited and explicit proxy modes still failed before a service request id. This points the next investigation toward Bailian category/request-model semantics under the working no-proxy transport path.
