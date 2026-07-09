# Bailian Official API Contract

## Conclusion

Bailian knowledge-base management is not the same as the OpenAI-compatible Qwen chat endpoint. Managing a document-search knowledge base requires the Alibaba Cloud Bailian SDK/OpenAPI path and Alibaba Cloud account credentials.

## Required SDK

The official SDK-gated path checks these modules:

```text
alibabacloud_bailian20231229
alibabacloud_tea_openapi
alibabacloud_tea_util
requests
```

If they are missing, the script returns `missing_dependency_or_api_contract` and does not upload.

Suggested local install command, not run by default:

```bash
pip install alibabacloud-bailian20231229 alibabacloud-tea-openapi alibabacloud-tea-util requests
```

## Required Environment

The KB management path requires:

```text
ALIBABA_CLOUD_ACCESS_KEY_ID
ALIBABA_CLOUD_ACCESS_KEY_SECRET
WORKSPACE_ID
```

Optional:

```text
BAILIAN_REGION
BAILIAN_MODEL
```

`DASHSCOPE_API_KEY` can be useful for model calls, but it is not sufficient for managing Bailian knowledge bases.

Do not write these values into the repo, `.env`, shell rc files, logs, or reports. Reports only show `SET` / `MISSING`.

## Official Flow

The documented KB-management flow includes:

```text
ApplyFileUploadLease
upload file to pre-signed URL
AddFile
DescribeFile until parse success
CreateIndex
SubmitIndexJob
GetIndexJobStatus
```

This repo currently implements the gates and request lifecycle skeleton only. It does not guess request model names or upload endpoints when the SDK/API contract is not available locally.

## Supported Now

- sanitized upload markdown generation at `/tmp/bailian_small_kb_upload_payload.md`
- official SDK dependency presence check
- official env presence check
- dry-run official SDK path
- fail-closed behavior for missing SDK/env/API contract
- KB id policy: `/tmp` only, never repo

## Still Blocked

- concrete SDK request model calls for KB creation/upload/indexing
- retrieval API contract for evaluating recall from the actual KB
- automatic cleanup/delete API

## Real Pilot Authorization

Run the real wrapper only after the user replies:

```text
allow official bailian sdk pilot
```

Then run:

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
  --allow-network \
  --allow-upload \
  --use-official-sdk \
  --strict
```

## Cleanup

If a KB is created manually or by a future SDK implementation:

1. Save the KB id only under `/tmp`.
2. Run retrieval/eval.
3. Delete the KB from Bailian console or a reviewed cleanup API.
4. Confirm no PDFs, raw images, full markdown, local paths, or secrets were uploaded.

