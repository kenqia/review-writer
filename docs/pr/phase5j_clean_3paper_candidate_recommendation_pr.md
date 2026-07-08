# Phase 5j-A Clean 3-Paper Candidate Recommendation PR Notes

## Summary

Phase 5j-A adds an AI-assisted, offline candidate recommender so the user does
not need to be an allene-domain expert to choose three seed papers manually.

The recommender reads filenames and committed real-lite metadata only. It does
not read PDF bodies, call APIs, upload files, create a knowledge base, or mark
anything as human verified.

## Added Files

```text
scripts/demo/recommend_clean_3paper_candidates.py
tests/test_clean_3paper_recommendation.py
demo_projects/clean_3paper_allene_review/README.md
demo_projects/clean_3paper_allene_review/inputs/selected_papers.candidates.json
demo_projects/clean_3paper_allene_review/inputs/human_selection_needed.md
demo_projects/clean_3paper_allene_review/expected/expected_claims.schema.json
demo_projects/clean_3paper_allene_review/expected/expected_citations.schema.json
demo_projects/clean_3paper_allene_review/expected/expected_figures.schema.json
demo_projects/clean_3paper_allene_review/outputs/.gitkeep
docs/demo/clean_3paper_candidate_recommendation.md
docs/pr/phase5j_clean_3paper_candidate_recommendation_pr.md
```

## Top 3

- `F3I`: review/background candidate.
- `F47A`: representative asymmetric/chiral allene method candidate.
- `P403`: recent-progress candidate from real-lite metadata.

## Alternatives

Alternatives include `P401`, `F4G`, `F4A`, `F14`, `F24A`, and other
high-scoring filename or real-lite metadata candidates.

## Safety Boundary

- no PDF body read
- no MinerU API
- no Qwen call
- no Bailian call
- no upload
- no knowledge-base creation
- no image generation
- all candidates remain `human_verified=false`

## Verification

```bash
make release-readiness-check
make reality-audit-check
make clean-3paper-recommend-check
python tests/test_clean_3paper_recommendation.py
```

## Next

- Phase 5j-B: user approves Top 3 or requests replacements.
- Phase 5j-C: read-only parsing of only the approved 3 PDFs.
- Phase 5k: clean 3-paper E2E.
