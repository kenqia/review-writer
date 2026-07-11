# Clean 3-Paper Allene Review Candidate Package

This directory is a candidate-selection package, not a verified dataset.

It helps a non-specialist user choose three papers for a later clean,
human-verified review fixture. The current files are based on PDF filenames and
committed real-lite metadata only. No PDF body has been read, no external API
has been called, and no claim, citation, or figure has been verified.

## Files

```text
inputs/selected_papers.candidates.json
inputs/human_selection_needed.md
expected/expected_claims.schema.json
expected/expected_citations.schema.json
expected/expected_figures.schema.json
outputs/.gitkeep
```

## Current Top 3 Candidate Set

- `F3I`: review/background candidate.
- `F47A`: representative asymmetric/chiral allene method candidate.
- `P403`: 2025 recent-progress candidate from real-lite metadata.

Every candidate has:

- `human_verified: false`
- `needs_pdf_read_verification: true`

## Next Step

The user should approve the Top 3 or request replacements before any PDF is
read. Phase 5j-B records that selection. Phase 5j-C can then perform read-only
verification for only the approved three PDFs.
