# Clean 3-Paper PDF Verification Draft

## Conclusion

Phase 5j-C performs a narrow read-only verification pass for the approved Top 3 clean allene candidates:

- `F3I`
- `F47A`
- `P403`

The result is a `verified_draft` dataset, not a final human-verified dataset.

## Scope

Allowed:

- Check only the approved Top 3 PDF paths.
- Confirm PDF existence and file size.
- Confirm title/role plausibility from filename and committed candidate metadata.
- Create short metadata, excerpt-note, and figure-note drafts.

Not allowed:

- Read the full `chem_papers` library.
- Extract or store long PDF body text.
- Call MinerU, Qwen, Bailian, or image APIs.
- Upload PDFs, images, markdown, or metadata.
- Create a knowledge base.
- Mark `human_verified=true`.

## Outputs

```text
demo_projects/clean_3paper_allene_review/inputs/selected_papers.verified_draft.json
demo_projects/clean_3paper_allene_review/inputs/verified_metadata/
demo_projects/clean_3paper_allene_review/inputs/verified_excerpts/
demo_projects/clean_3paper_allene_review/inputs/figure_notes/
```

## Verification

```bash
make clean-3paper-pdf-verify-check
```

This target runs the PDF verification report and the dataset audit in strict mode.

## Remaining Human Work

The user still needs to confirm:

- exact title
- authors
- DOI
- journal and year
- key claims
- figure candidates and captions
- whether the trio is suitable for a real clean 3-paper review demo

## Next

- Phase 5k: Clean 3-paper E2E.
- Or Phase 5j-D: manual metadata correction before E2E.
