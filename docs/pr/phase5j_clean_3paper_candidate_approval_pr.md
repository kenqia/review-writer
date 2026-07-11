# Phase 5j-B Clean 3-Paper Candidate Approval PR Notes

## Summary

Phase 5j-B adds a candidate approval pack that converts the Phase 5j-A
recommendation into a small human decision: accept the Top 3, replace one
candidate, or regenerate with a different topic focus.

This phase still does not read PDFs, call APIs, upload files, create a knowledge
base, or mark any candidate as human verified.

## Added Files

```text
demo_projects/clean_3paper_allene_review/inputs/candidate_approval_pack.json
demo_projects/clean_3paper_allene_review/inputs/candidate_approval_pack.md
scripts/demo/check_clean_3paper_approval_pack.py
tests/test_clean_3paper_approval_pack.py
docs/demo/clean_3paper_candidate_approval.md
docs/pr/phase5j_clean_3paper_candidate_approval_pr.md
```

## Top 3

- `F3I`: background/review candidate.
- `F47A`: representative asymmetric/chiral allene method candidate.
- `P403`: recent-progress candidate.

## Alternatives

- `P401`
- `F4G`
- `F4A`
- `F14`
- `F24A`
- `C2024-angew-chem-int-ed-2024-wen-remote-enantios`

## User Options

```text
Option A: accept Top 3
Option B: replace candidate ___ with alternative ___
Option C: regenerate candidates with changed topic focus
```

## Next Authorization Text

```text
allow read-only verify top 3 PDFs
```

## Safety Boundary

- no PDF body read
- no MinerU API
- no Qwen or Bailian call
- no upload
- no knowledge-base creation
- no image generation
- all candidates remain `human_verified=false`

## Verification

```bash
make release-readiness-check
make reality-audit-check
make clean-3paper-recommend-check
make clean-3paper-approval-check
python tests/test_clean_3paper_approval_pack.py
```
