# Clean 3-Paper Claims and Figure Notes Draft

## Conclusion

Phase 5j-E creates a small, review-ready draft package of key claim cues and figure/scheme notes for the approved Top 3 papers:

- `F3I`
- `F47A`
- `P403`

The package is suitable for engineering workflow and human review preparation. It is not final scientific evidence.

## Extraction Scope

The current implementation is intentionally conservative:

- It only touches the approved Top 3 PDF paths.
- It does not scan the full `chem_papers` directory.
- It does not OCR or parse long PDF body text.
- It uses filename, bibliographic metadata draft, and local PDF existence/size checks.
- Every uncertain claim or figure note keeps `needs_human_review=true`.

Because no reliable standard-library PDF text extractor is available, figure labels and exact source claims remain `needs_manual_extraction`.

## Draft Outputs

```text
demo_projects/clean_3paper_allene_review/expected/expected_claims.draft.json
demo_projects/clean_3paper_allene_review/expected/expected_figures.draft.json
demo_projects/clean_3paper_allene_review/inputs/verified_excerpts/
demo_projects/clean_3paper_allene_review/inputs/figure_notes/
```

## Current Counts

| paper | claim drafts | figure note drafts |
| --- | ---: | ---: |
| `F3I` | 3 | 1 |
| `F47A` | 2 | 1 |
| `P403` | 2 | 1 |

## Safety Boundary

- No Qwen call.
- No MinerU API.
- No Bailian API.
- No upload.
- No knowledge-base creation.
- No image generation.
- No raw source figure copy.
- No final `human_verified=true`.

## Verification

```bash
make clean-3paper-claims-check
```

## Human Review Needed

Before scientific use, the user or a reviewer must confirm:

- whether each claim is materially supported by the paper body
- exact reaction scope and limitations
- figure/scheme labels and captions
- whether any source figure can be redrawn or summarized without copying
- whether `P403` authors and article DOI should be corrected from the PDF or publisher page

## Next

- Phase 5j-F: user review / accept metadata + claims draft.
- Phase 5k: Clean 3-paper E2E.
