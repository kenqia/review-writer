# Bailian Small KB Pilot Runbook

## Conclusion

Phase 6c prepares a controlled small-KB pilot path. The repo can build a sanitized payload and dry-run the pilot wrapper. It does not implement an automatic Bailian KB upload because the KB API contract is not encoded in this repo.

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
```

Controlled real-mode wrapper:

```bash
python scripts/rag/bailian_small_kb_pilot.py \
  --payload-jsonl /tmp/bailian_small_kb_payload.jsonl \
  --questions evals/fixtures/rag_expected_questions.json \
  --output-json /tmp/bailian_small_kb_pilot_real.json \
  --output-md /tmp/bailian_small_kb_pilot_real.md \
  --allow-network \
  --allow-upload \
  --strict
```

If the API contract is not available, the wrapper returns `blocked_manual_console_required` and does not upload anything.

Current Phase 6c real-mode wrapper result:

- status: `blocked_manual_console_required`
- error type: `missing_dependency_or_api_contract`
- upload: `not_used`
- knowledge base: `not_created`
- retrieval: `not_run`

## KB ID Policy

KB ids must not be written to the repo. If a real or manual pilot creates a KB, record the id only in `/tmp` output files and delete the KB after evaluation.

## Manual Cleanup

If a temporary KB is created manually:

1. Open the Bailian console.
2. Find the temporary KB created for the clean 3-paper pilot.
3. Export or save only non-secret evaluation metrics if needed.
4. Delete the KB.
5. Confirm no PDFs, raw images, or full markdown were uploaded.

## Phase 6d Readiness

Proceed only if:

- sanitized payload check passes
- local retrieval baseline passes
- small-KB retrieval can recover expected paper IDs
- no secrets or raw files are uploaded
- clean 3-paper corpus remains not scientifically verified
