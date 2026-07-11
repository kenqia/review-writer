# Clean 3-Paper Bibliography Verification

## Conclusion

Phase 5j-D adds bibliographic metadata verification for the approved Top 3 clean allene candidates. The output helps the user avoid acting as a domain expert by surfacing evidence, confidence, conflicts, and missing fields.

The result remains a metadata draft:

- `human_verified=false`
- `needs_human_review=true`
- `trusted_for_scientific_quality=false`

## Metadata Sources

The verifier can query public metadata sources only when explicitly requested:

- Crossref
- OpenAlex
- Semantic Scholar

Default mode is offline and does not use the network. Public metadata lookup sends only title or filename-derived query text. It does not upload PDFs or paper content.

## Current Top 3 Drafts

| candidate | status | confidence | human review note |
| --- | --- | --- | --- |
| `F3I` | `bibliographic_verified_draft` | medium | Title, authors, year, journal, DOI found from public metadata. |
| `F47A` | `bibliographic_verified_draft` | medium | Title, authors, year, journal, DOI found; conflict tracking remains enabled. |
| `P403` | `bibliographic_verified_draft` | medium | Title/year/journal are plausible, but authors and DOI still need human confirmation. |

## Conflict Handling

No source is treated as the single truth. If public metadata sources disagree, the script records a conflict instead of silently overwriting fields. DOI values that look like supporting-information DOIs are not accepted as article DOI drafts.

## Safety Boundary

- No full `chem_papers` scan.
- No non-Top-3 PDF access.
- No long PDF body extraction or storage.
- No Qwen, MinerU, Bailian, image API, or knowledge-base creation.
- No upload.

## Commands

Offline:

```bash
make clean-3paper-biblio-check
```

Manual public metadata check:

```bash
make clean-3paper-biblio-web-check
```

## Next

- Phase 5j-E: key claims / figure notes extraction from only the Top 3 PDFs.
- Phase 5k: Clean 3-paper E2E after the user accepts the remaining metadata caveats.
