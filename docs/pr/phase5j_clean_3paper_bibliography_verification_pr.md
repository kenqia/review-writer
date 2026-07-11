# Phase 5j-D: Clean 3-Paper Bibliographic Metadata Verification

## PR Summary

This phase adds a bibliographic metadata verification layer for the approved clean 3-paper candidate set. It combines committed local draft metadata with optional public metadata lookup from Crossref, OpenAlex, and Semantic Scholar.

## Why

The user should not need to manually judge paper metadata from scratch. The verifier provides a structured draft with evidence, confidence, conflicts, and missing fields while keeping final human verification explicit.

## Files

```text
review_writer/metadata_sources/
scripts/demo/verify_clean_3paper_bibliography.py
tests/test_clean_3paper_bibliography_verification.py
demo_projects/clean_3paper_allene_review/inputs/bibliography_verification_summary.json
demo_projects/clean_3paper_allene_review/inputs/bibliography_verification_summary.md
demo_projects/clean_3paper_allene_review/inputs/verified_metadata/*.metadata.verified_draft.json
docs/demo/clean_3paper_bibliography_verification.md
```

## Gates

```bash
make clean-3paper-biblio-check
make clean-3paper-biblio-web-check
```

The first target is offline and deterministic. The second target is manual and uses public metadata APIs only.

## Safety

- No Qwen, Bailian, MinerU, or image API.
- No PDF upload.
- No long PDF body extraction.
- No knowledge-base creation.
- No secret or token access.
- No `human_verified=true`.

## Current Result

- `F3I`: bibliographic verified draft, medium confidence.
- `F47A`: bibliographic verified draft, medium confidence.
- `P403`: bibliographic verified draft, medium confidence, with authors/DOI still missing.

## Remaining Risk

Public metadata sources can be incomplete or return nearby papers. Conflicts are retained in the report and must be reviewed before scientific-quality use.
