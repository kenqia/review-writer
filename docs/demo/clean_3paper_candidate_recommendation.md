# Clean 3-Paper Candidate Recommendation

## Goal

Phase 5j-A helps a non-specialist user select a small candidate set for a later
human-verified allene review fixture. The user should not have to read 205 PDFs
or make expert chemistry judgments upfront.

This phase recommends candidates only. It does not read PDF bodies, call Qwen,
call MinerU, upload files, create a knowledge base, or generate a review.

## How Candidates Are Recommended

The recommender uses weak but safe evidence:

- PDF filenames under `chem_papers/`
- committed real-lite `selected_papers.json`
- committed real-lite metadata
- topic terms for allene synthesis, asymmetric synthesis, chiral allenes, axial
  chirality, and catalytic methods
- role coverage for background, representative method, and recent progress

It intentionally avoids fabricating DOI, authors, claims, figures, or
citations.

## Ranking Criteria

Each candidate receives:

- `topic_match_score`
- `metadata_completeness_score`
- `recency_or_classic_score`
- `role`
- `risks`
- `why_selected`

Every candidate remains:

```text
needs_pdf_read_verification: true
human_verified: false
```

## Top 3 Recommendation

The current recommended trio is:

1. `F3I` — review/background candidate:
   `Angew Chem Int Ed 2012 Yu Allenes in Catalytic Asymmetric Synthesis and Natural Product Syntheses`
2. `F47A` — representative method candidate:
   `Palladium catalyzed asymmetric synthesis of axially chiral allenes...`
3. `P403` — recent-progress candidate:
   `Pd-Catalyzed Asymmetric Allenylation of Secondary Phosphine Oxides...`

This trio is balanced because it has one overview-style background paper, one
focused asymmetric/chiral allene method, and one 2025 recent-progress example
with committed real-lite metadata.

## User Confirmation

The user only needs to decide:

- accept the Top 3
- replace one paper with an alternative
- authorize read-only parsing of only the selected 3 PDFs
- decide whether later Qwen-assisted claim extraction is allowed
- keep uploads and knowledge-base creation forbidden unless separately approved

## Run

```bash
make clean-3paper-recommend-check
```

or:

```bash
python scripts/demo/recommend_clean_3paper_candidates.py \
  --paper-root chem_papers \
  --real-lite-root demo_projects/real_lite_allene_review \
  --output-json /tmp/clean_3paper_recommendations.json \
  --output-md /tmp/clean_3paper_recommendations.md \
  --strict
```

## Next

- Phase 5j-B: user approves Top 3 or requests replacements.
- Phase 5j-C: read-only parsing of only the approved 3 PDFs to generate a
  verified metadata draft.
- Phase 5k: clean 3-paper E2E.
