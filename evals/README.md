# Review Writer Evals

This directory stores offline, deterministic evaluation baselines for review-writer workflow outputs.

Current baseline:

- `baselines/real_lite_v1.yaml`: real-lite workflow artifact and quality baseline.
- `fixtures/real_lite_expected_metrics.json`: minimum passing thresholds.

Generated reports should be written outside the repository, for example:

```bash
/tmp/real_lite_eval_report.json
/tmp/real_lite_eval_report.md
```

Do not commit real paper bodies, PDFs, API keys, `.env` files, or `/tmp` reports.
