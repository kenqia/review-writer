# Phase 5j-E: Clean 3-Paper Claims and Figure Notes Draft

## Summary

This phase adds a deterministic, offline draft extractor for Top 3 key claim cues and figure/scheme notes. It prepares a small human-reviewable package for the clean 3-paper workflow without generating review prose or treating inferred claims as final facts.

## Added Files

```text
scripts/demo/extract_clean_3paper_claims_figures.py
tests/test_clean_3paper_claims_figures.py
demo_projects/clean_3paper_allene_review/expected/expected_claims.draft.json
demo_projects/clean_3paper_allene_review/expected/expected_figures.draft.json
docs/demo/clean_3paper_claims_figures_extraction.md
```

## Updated Files

```text
Makefile
scripts/audit/audit_clean_3paper_dataset.py
tests/test_clean_3paper_audit.py
demo_projects/clean_3paper_allene_review/inputs/verified_excerpts/
demo_projects/clean_3paper_allene_review/inputs/figure_notes/
docs/migration/05_incremental_pr_plan.md
```

## Gate

```bash
make clean-3paper-claims-check
```

## Current Draft Counts

- `F3I`: 3 claims, 1 figure note.
- `F47A`: 2 claims, 1 figure note.
- `P403`: 2 claims, 1 figure note.

## Boundaries

- No full PDF corpus read.
- Only approved Top 3 PDF paths are touched.
- No long PDF body text is stored.
- No Qwen, MinerU, Bailian, or image API.
- No upload.
- No knowledge-base creation.
- All claims and figure notes remain `human_verified=false`.
- All claims and figure notes remain `needs_human_review=true`.

## Remaining Risk

The draft relies on metadata/title signals because no reliable standard-library PDF text extractor is used. It intentionally emits `needs_manual_extraction` for details that require paper-body or caption review.
