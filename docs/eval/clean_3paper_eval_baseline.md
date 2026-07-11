# Clean 3-Paper Eval Baseline

## Purpose

The clean 3-paper eval checks whether the vertical slice is complete and safe enough for human review. It does not certify scientific truth.

## Metrics

- `workflow_completeness`
- `artifact_completeness`
- `bibliographic_completeness`
- `claim_traceability`
- `figure_note_integrity`
- `warning_visibility`
- `prompt_leakage_absence`
- `safety_boundary`
- `human_review_flags`

## Current Baseline

```text
evals/baselines/clean_3paper_v1.yaml
evals/fixtures/clean_3paper_expected_metrics.json
```

The expected minimum score is 90. The current offline run scores 100 while keeping:

- `trusted_for_scientific_quality=false`
- `needs_human_review=true`

## Command

```bash
make clean-3paper-eval-check
```

## Safety

The eval does not read PDFs, call Qwen, call MinerU, call Bailian, upload files, or create a knowledge base.
