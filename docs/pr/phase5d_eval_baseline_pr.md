# Phase 5d Eval Baseline PR

## PR Title

`feat: add real-lite eval baseline`

## Summary

This PR adds an offline custom eval baseline for the real-lite workflow output. The eval runner scores required artifacts and quality gates without installing promptfoo, calling APIs, reading PDFs, or uploading files.

## Added Files

- `evals/README.md`
- `evals/baselines/real_lite_v1.yaml`
- `evals/fixtures/real_lite_expected_metrics.json`
- `evals/reports/.gitkeep`
- `evals/promptfoo/real_lite_v1.promptfooconfig.yaml`
- `scripts/eval/run_eval_baseline.py`
- `tests/test_eval_baseline.py`
- `docs/eval/real_lite_eval_baseline.md`
- `docs/pr/phase5d_eval_baseline_pr.md`

## Updated Files

- `Makefile`: adds `eval-baseline-check`
- `docs/migration/05_incremental_pr_plan.md`

## Metrics

- `workflow_completeness`
- `artifact_completeness`
- `quality_gate_health`
- `figure_integrity`
- `citation_and_reference_integrity`
- `prompt_leakage_absence`
- `evidence_coverage`
- `safety_boundary`

## Current Result

The real-lite v1 baseline currently reports:

```text
status: pass
score_total: 100.0
```

## Validation

```bash
make eval-baseline-check
python tests/test_eval_baseline.py
```

Full local QA:

```bash
make smoke
make quality-check
make qoderwork-check
make provider-check
make qwen-hello-dry-run
make judge-check
make tiny-e2e-check
make real-lite-preflight
make real-lite-e2e-check
make dashboard-real-lite-check
make eval-baseline-check
```

## Not Included

- No promptfoo install.
- No promptfoo execution.
- No API calls.
- No real Qwen call.
- No PDF body read.
- No upload.
- No Bailian knowledge base.
- No image generation.

## Risks

- Static eval cannot judge scientific novelty or deep chemistry correctness.
- The current score reflects workflow and safety completeness, not publication-ready review quality.

## Next Stage

- Phase 5e: QoderWork CN manual real-lite flow.
- Phase 5f: optional promptfoo integration.
- Phase 6: Bailian RAG preflight.
