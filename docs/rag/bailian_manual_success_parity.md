# Bailian Manual Success Parity

## Conclusion

Manual OpenAPI Explorer validation proves that the Bailian cloud-side knowledge-base path can work. The repo SDK automation is not yet complete until the official SDK run passes lease, upload, AddFile, parse, index creation, index job completion, retrieval, and cleanup in one controlled lifecycle.

Downstream stages being skipped is correct: CreateIndex, SubmitIndexJob, and Retrieve must not run when DescribeFile reports parse failure.

## Manual OpenAPI Success Path

The manual path succeeded with sensitive values redacted from repo docs:

- CreateIndex: success
- SubmitIndexJob: success
- GetIndexJobStatus: `COMPLETED`
- Retrieve: success
- Nodes: non-empty
- Smoke fact found: true
- signed_url_present: true
- signed_url_redacted: true

## SDK Automated Path

Latest controlled SDK automation result:

- lease: pass
- upload: pass
- add_file: pass
- parse: failed
- create_index: skipped
- retrieve: skipped
- cleanup: failed
- manual_file_cleanup_required: true

Resource ids remain only in `/tmp/bailian_small_kb_pilot_real.json` for cleanup. They are not committed to the repository.

## Parity Diff

| Item | Manual success path | SDK automated path | Current action |
| --- | --- | --- | --- |
| file content | Minimal smoke document | Now aligned to minimal smoke document | keep aligned |
| file extension | Markdown-like payload | `.md` by default; `.txt` candidate available | use TXT only if MD parse failure evidence persists |
| upload method | lease-provided method | now uses lease `param.method`; falls back to PUT only if method absent | aligned |
| upload headers | lease-provided upload headers | only sends lease-provided `Content-Type` and `X-bailian-extra` when present | aligned |
| upload bytes | exact local file bytes | immutable byte snapshot, size/md5 telemetry, post-upload local verification | aligned |
| parser | Bailian manual default / accepted parser | `DASHSCOPE_DOCMIND` | monitor parse result |
| category_id | manual successful value | `default` unless configured | do not blind-probe |
| category_type | manual successful category flow | `UNSTRUCTURED` | keep |
| use_internal_endpoint | external endpoint | `false` | keep |
| source_type | manual successful index params | `DATA_CENTER_FILE` | keep unless parse/index evidence changes |
| sink_type | current official example / SDK-supported field | `BUILT_IN` | aligned; older `DEFAULT` notes are historical |
| structure_type | manual successful index params | `unstructured` | keep |
| document_ids | file id from AddFile | file id from AddFile | only after parse success |
| rerank_mode | omitted in working path | omitted by default | fixed |
| rerank_instruct | omitted in working path | omitted by default | fixed |
| retrieve params | Retrieve successful, nodes non-empty | skipped because parse failed | correct skip |
| cleanup method | manual console cleanup possible | best-effort DeleteIndex/DeleteFile | file cleanup currently failed |

## Current Conclusion

- Manual cloud path works.
- SDK automation must still prove the whole lifecycle with retrieval and cleanup.
- Skipped downstream stages are allowed and correct when parse fails.
- Phase 6c SDK automation is not complete until the controlled SDK run passes end-to-end.
- Before another upload-capable pilot, resolve any orphan temporary file or prove it can be cleaned by `DeleteFile`.

## Closure Update

The latest controlled SDK closure run advanced past the previous parse and CreateIndex blockers:

- lease: pass
- upload: pass
- AddFile: pass
- parse: `PARSE_SUCCESS`
- CreateIndex: pass
- SubmitIndexJob: pass
- GetIndexJobStatus: completed before retrieval
- Retrieve: failed the smoke-fact assertion
- cleanup: pass for both index and application-data file in the cleanup-only command

Remaining parity gap: manual Retrieve returned a node containing `review-writer Phase 6c smoke test`, while SDK automation did not find that smoke fact in retrieved node text. The next investigation should focus on query formulation, retrieve response parsing, and whether the indexed chunk text contains the exact smoke sentence.

## Manual Cleanup Note

The latest automated run created a temporary file resource and automatic DeleteFile failed. The repo now includes a cleanup-only command that reads the file id only from a `/tmp` report and never prints it:

```bash
zsh -ic 'cd <REPO_ROOT> && conda run -n review-writer-bailian python scripts/rag/bailian_cleanup_orphan_file.py \
  --report-json /tmp/bailian_small_kb_pilot_real.json \
  --output-json /tmp/bailian_orphan_file_cleanup.json \
  --output-md /tmp/bailian_orphan_file_cleanup.md \
  --endpoint bailian.cn-beijing.aliyuncs.com \
  --region cn-beijing \
  --category-id default \
  --transport-mode no_proxy \
  --allow-network \
  --use-official-sdk \
  --strict'
```

If that command fails, the user should either:

- delete the temporary file in the Bailian console using the id stored only in `/tmp/bailian_small_kb_pilot_real.json`, or
- explicitly authorize retaining the temporary resource for the pilot window.

Do not paste the file id into chat unless intentionally requesting a manual cleanup command.
