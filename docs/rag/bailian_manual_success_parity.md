# Bailian Manual Success Parity

## Conclusion

Manual OpenAPI Explorer validation proves that the Bailian cloud-side knowledge-base path can work. The repo SDK automation is not yet complete because the latest automated run still fails at the parse stage before CreateIndex.

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
| file extension | Markdown-like payload | `.md` | verify with payload readiness |
| parser | Bailian manual default / accepted parser | `DASHSCOPE_DOCMIND` | monitor parse result |
| category_id | manual successful value | `default` unless configured | do not blind-probe |
| category_type | manual successful category flow | `UNSTRUCTURED` | keep |
| use_internal_endpoint | external endpoint | `false` | keep |
| source_type | manual successful index params | `DATA_CENTER_FILE` | keep unless parse/index evidence changes |
| sink_type | manual successful index params | `DEFAULT` | keep |
| structure_type | manual successful index params | `unstructured` | keep |
| document_ids | file id from AddFile | file id from AddFile | only after parse success |
| rerank_mode | omitted in working path | omitted by default | fixed |
| rerank_instruct | omitted in working path | omitted by default | fixed |
| retrieve params | Retrieve successful, nodes non-empty | skipped because parse failed | correct skip |
| cleanup method | manual console cleanup possible | best-effort DeleteIndex/DeleteFile | file cleanup currently failed |

## Current Conclusion

- Manual cloud path works.
- SDK automation still fails at parse.
- Skipped downstream stages are allowed and correct because parse failed.
- Phase 6c SDK automation is not complete.
- Before another real pilot, confirm the minimal payload parses or use explicit manual cleanup for the current temporary file.

## Manual Cleanup Note

The latest automated run created a temporary file resource and automatic DeleteFile failed. The user should either:

- delete the temporary file in the Bailian console using the id stored only in `/tmp/bailian_small_kb_pilot_real.json`, or
- explicitly authorize a future DeleteFile-only cleanup command.

Do not paste the file id into chat unless intentionally requesting a manual cleanup command.
