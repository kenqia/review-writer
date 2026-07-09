# Bailian Small KB Pilot Runbook

## Conclusion

Phase 6c prepares a controlled small-KB pilot path. The repo can build a sanitized payload and dry-run the pilot wrapper. Default checks do not upload, create a knowledge base, or call Bailian APIs.

Phase 6c-bis and Phase 6c-quad add an official SDK-gated path. It checks official SDK dependencies and official KB-management environment variables, then can run the official upload/index/retrieve lifecycle only after the user explicitly authorizes `allow official bailian sdk pilot` and the command includes `--allow-network --allow-upload --use-official-sdk`.

## Uploaded Fields Allowed

Only the following fields may be uploaded in a future manual or API-backed pilot:

- `paper_id`
- `title`
- `year`
- `journal`
- `doi_draft`
- `role`
- `claim_draft`
- `figure_note_draft`
- `known_warnings`
- `needs_human_review=true`
- `trusted_for_scientific_quality=false`

The generated payload packages these into compact JSONL records with:

- `compact_text`
- `metadata`
- `upload_scope=small_kb_pilot`

## Not Uploaded

- PDFs
- raw images or figures
- full MinerU markdown
- full PDF text
- local absolute paths
- API keys, tokens, auth files, or secrets
- complete `final_draft.md`
- long untrimmed excerpts

## Commands

Dry-run gates:

```bash
make bailian-small-kb-payload-check
make bailian-small-kb-pilot-dry-run
make bailian-small-kb-official-sdk-dry-run
make bailian-small-kb-official-sdk-real-command
```

Controlled real-mode wrapper using the official SDK:

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

This command must not be run until the user replies exactly:

```text
allow official bailian sdk pilot
```

The real path performs:

- ApplyFileUploadLease
- PUT upload of `/tmp/bailian_small_kb_upload_payload.md`
- AddFile
- DescribeFile until `PARSE_SUCCESS`
- CreateIndex
- SubmitIndexJob
- GetIndexJobStatus until `COMPLETED`
- Retrieve over `evals/fixtures/rag_expected_questions.json`
- recall@1, recall@3, and citation coverage calculation

## KB ID Policy

KB ids must not be written to the repo. If a real or manual pilot creates a KB, record the id only in `/tmp` output files and delete the KB after evaluation.

## Phase 6c-quad Real Pilot Note

One authorized official SDK pilot was attempted after the implementation was added. The result was:

- status: `fail`
- error_type: `unexpected_error`
- safe summary: `UnretryableException`
- file_id/index_id/job_id: not created
- retrieval: not run
- temporary KB/index cleanup: not required

No retry was performed. No key value was printed, no PDF or raw image was uploaded, and no KB/index id was written to the repo.

## Manual Cleanup

If a temporary KB is created manually or by the official SDK pilot:

1. Read the temporary index id only from `/tmp/bailian_small_kb_pilot_real.json`.
2. Delete it in the Bailian console, or run the reviewed cleanup command with both `--cleanup` and `--cleanup-index-id`.
3. Export or save only non-secret evaluation metrics if needed.
4. Confirm no PDFs, raw images, or full markdown were uploaded.

## Phase 6d Readiness

Proceed only if:

- sanitized payload check passes
- local retrieval baseline passes
- small-KB retrieval can recover expected paper IDs
- no secrets or raw files are uploaded
- clean 3-paper corpus remains not scientifically verified
