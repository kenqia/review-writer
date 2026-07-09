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

## Endpoint And Region

The official Python examples use:

```text
bailian.cn-beijing.aliyuncs.com
```

The repo now makes endpoint selection explicit:

1. `--endpoint` wins.
2. Without `--endpoint`, `--region` builds `bailian.<region>.aliyuncs.com`.
3. Without `--region`, the default is `cn-beijing`.
4. The default endpoint is `bailian.cn-beijing.aliyuncs.com`.

`WORKSPACE_ID` is the official SDK management workspace variable. `BAILIAN_WORKSPACE_ID` remains only for older no-upload preflight/config compatibility and is not used for official SDK management calls.

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

This repo implements the official SDK-gated lifecycle behind explicit real-run flags. Default checks still dry-run and do not upload or create a knowledge base.

## Supported Now

- sanitized upload markdown generation at `/tmp/bailian_small_kb_upload_payload.md`
- official SDK dependency presence check
- official env presence check
- dry-run official SDK path
- fail-closed behavior for missing SDK/env/API contract
- official SDK request model calls for upload lease, add file, parse polling, index creation, index job polling, retrieval, and reviewed cleanup
- KB id policy: `/tmp` only, never repo

## Still Gated

- real upload requires `--allow-network --allow-upload --use-official-sdk`
- cleanup requires both `--cleanup` and `--cleanup-index-id`
- no default make target performs a real upload

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
  --endpoint bailian.cn-beijing.aliyuncs.com \
  --region cn-beijing \
  --category-id default \
  --allow-network \
  --allow-upload \
  --use-official-sdk \
  --strict
```

The Makefile can print the real command without executing it:

```bash
make bailian-small-kb-official-sdk-real-command
```

## Cleanup

If a KB is created manually or by the official SDK pilot:

1. Save the KB id only under `/tmp`.
2. Run retrieval/eval.
3. Delete the KB from Bailian console or the reviewed cleanup path:

```bash
python scripts/rag/bailian_small_kb_pilot.py \
  --use-official-sdk \
  --allow-network \
  --allow-upload \
  --cleanup \
  --cleanup-index-id '<index_id_from_tmp_report>' \
  --output-json /tmp/bailian_small_kb_cleanup.json \
  --output-md /tmp/bailian_small_kb_cleanup.md
```

4. Confirm no PDFs, raw images, full markdown, local paths, or secrets were uploaded.
