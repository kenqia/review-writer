# Clean 3-Paper Candidate Approval

## Goal

Phase 5j-B turns the Top 3 recommendation into a lightweight approval pack so
the user does not need to act as an allene-domain expert.

The pack is a decision aid only. It does not read PDF bodies, call Qwen, call
MinerU, call Bailian, upload files, create a knowledge base, or mark any paper
as human verified.

## Current Top 3

- `F3I`: background/review candidate.
- `F47A`: representative asymmetric/chiral allene method candidate.
- `P403`: recent-progress candidate.

All three remain:

```text
human_verified: false
needs_pdf_read_verification: true
```

## Alternatives

The approval pack includes alternatives for each role:

- `P401` can replace `P403` if the user wants Ni catalysis in the recent slot.
- `F4G` can replace `F3I` for a broader critical assessment background.
- `F4A` can replace `F3I` or `F47A` for an older enantioselective synthesis anchor.
- `F14` can replace `F47A` for copper catalysis.
- `F24A` can replace `F47A` for gold catalysis.
- `C2024-angew-chem-int-ed-2024-wen-remote-enantios` can replace `P403` for a
  2024 Angewandte filename-only recent-progress option.

## User Decision

Choose one:

```text
Option A: accept Top 3
Option B: replace candidate ___ with alternative ___
Option C: regenerate candidates with changed topic focus
```

## Next Authorization

Only after the user accepts a final trio may the next phase request:

```text
allow read-only verify top 3 PDFs
```

That authorization means:

- read only the selected 3 PDFs
- do not read full `chem_papers`
- do not upload files
- do not call external APIs
- do not create a knowledge base
- extract title/authors/year/DOI/abstract/key claims/figure notes only
- output a verified metadata draft that still requires human review

## Verification

```bash
make clean-3paper-approval-check
```

## Next

- Phase 5j-C: read-only verification of the approved 3 PDFs.
- Phase 5k: clean 3-paper E2E.
