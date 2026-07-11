# Phase 5k: Clean 3-Paper Vertical Slice

## Summary

This phase converts the approved Top 3 allene papers into a complete offline vertical slice: clean input package, E2E output, quality gate, eval baseline, dashboard QA, export skeleton, and human review pack.

## Why

The previous real-lite run proved workflow wiring, but not a curated clean dataset. Phase 5k uses the Top 3 draft package from Phase 5j-A/B/C/D/E to exercise the same pipeline with a smaller, more inspectable dataset.

## Added Files

```text
scripts/demo/run_clean_3paper_e2e.py
tests/test_clean_3paper_e2e_workflow.py
scripts/eval/run_clean_3paper_eval.py
tests/test_clean_3paper_eval.py
tests/test_dashboard_clean_3paper_payload.py
evals/baselines/clean_3paper_v1.yaml
evals/fixtures/clean_3paper_expected_metrics.json
docs/demo/clean_3paper_e2e_runbook.md
docs/eval/clean_3paper_eval_baseline.md
```

## Updated Files

```text
Makefile
view/serve_review_dashboard.py
demo_projects/clean_3paper_allene_review/inputs/selected_papers.clean_draft.json
demo_projects/clean_3paper_allene_review/inputs/clean_registry.jsonl
demo_projects/clean_3paper_allene_review/inputs/claims/
docs/migration/05_incremental_pr_plan.md
```

## Gates

```bash
make clean-3paper-e2e-check
make clean-3paper-eval-check
make dashboard-clean-3paper-check
```

## Current Result

- Clean E2E: pass.
- Eval score: 100.
- Quality report: warn, with visible metadata warnings.
- Dashboard QA: pass.

## Safety

- No full PDF corpus read.
- No long PDF text extraction.
- No Qwen, MinerU, Bailian, image API, upload, or knowledge-base creation.
- All rows remain `human_verified=false`.
- Scientific trust remains false until user acceptance.
