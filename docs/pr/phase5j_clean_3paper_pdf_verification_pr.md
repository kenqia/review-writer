# Phase 5j-C: Clean 3-Paper PDF Verification Draft

## PR Summary

This phase adds a read-only Top 3 PDF verification draft for the clean allene dataset. It converts the approved candidates into a structured `verified_draft` package while preserving the human-review boundary.

## Files

```text
scripts/demo/verify_clean_3paper_pdfs.py
scripts/audit/audit_clean_3paper_dataset.py
tests/test_clean_3paper_pdf_verification.py
tests/test_clean_3paper_audit.py
demo_projects/clean_3paper_allene_review/inputs/selected_papers.verified_draft.json
demo_projects/clean_3paper_allene_review/inputs/verified_metadata/
demo_projects/clean_3paper_allene_review/inputs/verified_excerpts/
demo_projects/clean_3paper_allene_review/inputs/figure_notes/
docs/demo/clean_3paper_pdf_verification.md
```

## Safety Boundary

- No full 205-paper PDF scan.
- Only the approved Top 3 PDF paths are checked.
- No MinerU API.
- No Qwen or Bailian call.
- No upload.
- No knowledge-base creation.
- No image API.
- No `human_verified=true`.

## Gate

```bash
make clean-3paper-pdf-verify-check
```

## Result

The Top 3 are represented as verified drafts:

- `F3I`: `verified_draft`
- `F47A`: `verified_draft`
- `P403`: `verified_draft`

All entries remain `human_verified=false` and `needs_human_review=true`.

## Remaining Risk

This does not prove scientific correctness. It only confirms that the approved candidate files exist locally and are plausible from filenames/committed metadata. Human review is still required for DOI, authors, claims, and figures.
