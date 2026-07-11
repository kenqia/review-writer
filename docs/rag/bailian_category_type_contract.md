# Bailian CategoryType Contract

## Conclusion

The current blocker is the `CategoryType` contract, not PDF content, payload content, Qwen, MinerU, or pure transport.

Previous real probes showed:

- `no_proxy` reaches Bailian and returns a service request id.
- `ListCategory` without `CategoryType` fails with `MissingCategoryType`.
- `ApplyFileUploadLease` with the old `document` category type fails with `InvalidCategoryType`.

## SDK Evidence

Installed SDK introspection shows:

- `ListCategoryRequest(category_type=...)`
- `ApplyFileUploadLeaseRequest(category_type=...)`
- `AddFileRequest(category_type=...)`
- `ListCategoryResponseBodyDataCategoryList(category_type=...)`
- client method `list_category_with_options(...)`

SDK source serializes `category_type` as `CategoryType`. SDK source comments in `AddFileRequest` identify:

- `UNSTRUCTURED`: normal application-data category used for knowledge-base scenarios
- `SESSION_FILE`: session file category, using `default`

The old `document` value is not a valid SDK/API category type.

## Official Documentation Evidence

The official `ListCategory` API documentation marks `CategoryType` as required and lists `UNSTRUCTURED` for category listing.

The official `AddFile` documentation lists `UNSTRUCTURED` and `SESSION_FILE`. For `UNSTRUCTURED`, `CategoryId` should be the category id returned by `AddCategory`, and `default` is also allowed for the system default category.

References:

- https://help.aliyun.com/zh/model-studio/api-bailian-2023-12-29-listcategory
- https://help.aliyun.com/zh/model-studio/api-bailian-2023-12-29-addfile

## Matrix Design

`scripts/rag/bailian_category_type_matrix.py` tests category types through `ListCategory` only. It never uploads and never calls `ApplyFileUploadLease`.

Candidate order:

1. SDK/doc-derived candidates: `UNSTRUCTURED`, `SESSION_FILE`
2. Conservative historical probes: `DOCUMENT`, `DATA_CENTER_FILE`, `DATA_CENTER_CATEGORY`, `DEFAULT`, `INDEX`, `KNOWLEDGE_BASE`

Interpretation:

- `category_type_found`: a candidate returned categories and a recommended category id.
- `category_type_valid_but_empty`: a candidate was accepted but no category exists; create/select a category before upload.
- `category_type_unknown`: all candidates failed; use API Explorer or manual console pilot.

## Safety Boundary

- No PDF read.
- No Qwen, MinerU, or image API call.
- No upload or PUT.
- No AddFile, CreateIndex, SubmitIndexJob, Retrieve, DeleteIndex, or KB creation.
- No AccessKey, proxy URL, pre-signed URL, headers, Authorization, or `X-bailian-extra` output.

## Next Decision

If the matrix finds a `recommended_category_type` and `recommended_category_id`, run exactly one lease-only reprobe. Only after a lease is obtained should a reviewed full pilot retry be considered.

## Phase 6c-deepfix Real Matrix Result

One authorized `ListCategory` category-type matrix was executed through `no_proxy`. It did not upload, call `AddFile`, create an index, retrieve, or create a knowledge base.

Safe summary:

- `UNSTRUCTURED`: accepted by `ListCategory`; returned `0` categories and no recommended category id.
- `SESSION_FILE`: rejected with `InvalidCategoryType`.
- `DOCUMENT`: rejected with `InvalidCategoryType`.
- `DATA_CENTER_FILE`: rejected with `InvalidCategoryType`.
- `DATA_CENTER_CATEGORY`: rejected with `InvalidCategoryType`.
- `DEFAULT`: rejected with `InvalidCategoryType`.
- `INDEX`: rejected with `Throttling.Api`.
- `KNOWLEDGE_BASE`: rejected with `Throttling.Api`.

Conclusion:

- The valid category type for the current knowledge-base path is `UNSTRUCTURED`.
- The current workspace did not return a usable category id through `ListCategory`.
- No lease-only reprobe was executed, because the matrix did not produce a `recommended_category_id`.
- The next safe step is to create or select a Bailian console category, then rerun the lease-only probe with `category_type=UNSTRUCTURED` and the selected category id.
