# Qwen Judge Quality Gate Runbook

## Conclusion

Qwen judge is a review-quality gate only. It judges title alignment, semantic prompt leakage, and formula-review assistance tasks. It does not generate review正文, read PDFs, upload files, create Bailian knowledge bases, or call image APIs.

## Default Mode

The default mode is offline:

```bash
python scripts/validators/validate_review_quality.py \
  --draft tests/fixtures/judge/bad_title_alignment.md \
  --judge-mode offline \
  --judge-output-json /tmp/judge_report.json \
  --judge-output-md /tmp/judge_report.md
```

Offline mode returns deterministic placeholder results and never calls network.

## Dry-Run Gate

Run:

```bash
make judge-check
```

This runs the safety tests, the judge CLI dry-run, and validator integration with offline judge output.

## Qwen Judge Scope

Only these placeholder task types may be sent to Qwen:

- `section_title_alignment`
- `review_title_alignment`
- `prompt_leakage_semantic`
- `chem_formula_review_assist`

## Real Call Requirements

Real Qwen judge calls require:

- explicit user confirmation
- `--judge-mode qwen`
- `--allow-network`
- temporary local env variables

Do not send API keys in chat. Do not write keys to repo files, `.env`, shell rc files, or reports.

Example command after explicit approval:

```bash
python scripts/validators/validate_review_quality.py \
  --draft tests/fixtures/judge/bad_title_alignment.md \
  --judge-mode qwen \
  --allow-network \
  --output-json /tmp/quality_with_qwen_judge.json \
  --judge-output-json /tmp/qwen_judge_report.json \
  --judge-output-md /tmp/qwen_judge_report.md
```

## Not Allowed

- No PDF reading.
- No paper body upload.
- No markdown upload beyond the small fixture/draft excerpt provided to the judge.
- No Bailian knowledge base creation.
- No image generation.
- No automatic retry loop.
- No key printing.

## Failure Categories

Qwen judge reports structured failures, including:

- `missing_dependency`
- `missing_env`
- `auth_error_401`
- `rate_limit_or_quota_429`
- `timeout`
- `server_error_5xx`
- `network_error`
- `unexpected_error`

## Next Stage

After the judge is proven on fixtures, the next phase can consider a small real review-project smoke using user-approved excerpts only. Full paper RAG and image generation remain separate later phases.
