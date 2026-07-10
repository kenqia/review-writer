# Bailian Category Discovery

## Conclusion

Phase 6c-nov moves the blocker from transport to Bailian category/request-model alignment. The Phase 6c-oct matrix showed that `no_proxy` reaches the service and receives a request id, but `ApplyFileUploadLease` fails with `400 InvalidCategoryType`.

The next safe diagnostic is `ListCategory`, not a full pilot retry.

## Why ListCategory First

`ApplyFileUploadLease` and `AddFile` must use the same category. The official examples use `default`, but a workspace can require another category id or category type. `ListCategory` is the least invasive way to inspect the current workspace categories before another lease-only probe.

## Safety Boundary

Allowed:

- create official SDK client
- call `ListCategory`
- summarize category ids, names, types, parent-id presence, status, and default-candidate flag
- run one lease-only reprobe with the recommended category

Forbidden:

- PUT upload
- AddFile
- CreateIndex
- SubmitIndexJob
- Retrieve
- DeleteIndex
- knowledge-base creation
- Qwen, MinerU, image API calls
- PDF reads
- printing keys, signed headers, pre-signed URLs, Authorization, or `X-bailian-extra`

## SDK Capability

In the isolated `review-writer-bailian` conda environment:

- `ListCategoryRequest`: available
- `list_category_with_options`: available
- create-category request: available, but not called

`ListCategoryRequest` exposes category name/type, connector id, max results, next token, and parent category id fields. The real Phase 6c-nov probe showed that this API version requires an explicit `category_type`, so follow-up discovery must set the official value `UNSTRUCTURED`.

## Interpretation

- Discovery succeeds and returns a recommended category: run one no-proxy lease reprobe with that category.
- Discovery succeeds but returns no suitable category: create or select a document-search category in Bailian console before any upload-capable pilot.
- Discovery fails with request id: inspect workspace permission or ListCategory API permissions.
- Discovery fails without request id: return to transport/proxy diagnostics.
- Lease reprobe succeeds: only then consider one reviewed full pilot retry.
- Lease reprobe fails with request id: inspect category type/id and request contract before upload.

## Phase 6c-nov Real Discovery Result

One authorized `ListCategory` discovery was executed with `no_proxy`. It did not upload or create a knowledge base.

Safe summary:

- status: `fail`
- error type: `category_type_required`
- service request id: present
- status code: `400`
- error code: `MissingCategoryType`
- categories returned: `0`
- recommended category: none
- upload attempted: false
- knowledge base created: false

Interpretation: the workspace/service is reachable through `no_proxy`, but this API version requires an explicit `category_type` even for `ListCategory`. The next step is to confirm the valid category type values for this workspace/API contract, then run one more `ListCategory --category-type <value>` before any lease or full pilot retry.

SDK source and official documentation identify `UNSTRUCTURED` as the required `CategoryType` for normal categories. `SESSION_FILE` is also valid for session files, but the knowledge-base workflow should prefer `UNSTRUCTURED`.

## Phase 6c-deepfix Real Matrix Result

The authorized category-type matrix confirmed that `UNSTRUCTURED` is accepted by `ListCategory`, but the workspace returned no categories. Because no `recommended_category_id` was found, no lease-only reprobe was executed.

Next safe action: create or select a category in Bailian console, then run one lease-only reprobe with `category_type=UNSTRUCTURED` and that category id.

## Commands

Dry-run:

```bash
make bailian-category-introspection
make bailian-category-discovery-dry-run
```

Reviewed real commands:

```bash
make bailian-category-discovery-real-command
make bailian-category-lease-reprobe-real-command
```

The make targets only print commands. They do not perform real network calls by default.
