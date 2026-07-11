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

## Timeout Triage

The first controlled real Qwen judge call reached the provider path but returned `timeout`. A separate hello Qwen call had already returned `QWEN_HELLO_OK`, so the provider/key/endpoint path is broadly usable. The initial timeout is therefore treated as a judge request-layer issue until proven otherwise.

Hardening added after that timeout:

- `--timeout-seconds`, default `90`
- `--max-output-tokens`, default `128`
- `--compact`
- `--task-limit`, default `1`
- prompt size telemetry
- elapsed time telemetry
- network attempt count
- `client_timeout` classification
- `server_overloaded_503` classification

Dry-run hardened command:

```bash
python scripts/llm_judges/qwen_review_quality_judge.py \
  --dry-run \
  --compact \
  --task-limit 1 \
  --timeout-seconds 90 \
  --max-output-tokens 128 \
  --output-json /tmp/qwen_judge_dry_hardened.json \
  --output-md /tmp/qwen_judge_dry_hardened.md
```

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

For the next real retry, the user must explicitly reply:

```text
allow qwen judge retry once
```

## Retry Validation Result

The controlled retry succeeded after hardening. The run used a synthetic fixture, compact prompt, `--timeout-seconds 90`, `--max-output-tokens 128`, and `--task-limit 1`.

Safe summary:

- status: `pass`
- judge_mode: `qwen`
- task_id: `dry_run_title_alignment`
- rule_id: `CRQ007_REVIEW_TITLE_FIT`
- result_status: `ok`
- verdict: `fail`
- model: `qwen3.7-plus`
- region: `cn-beijing`
- prompt_chars: `676`
- input_excerpt_chars: `413`
- rubric_chars: `75`
- elapsed_seconds: `27.937`
- network_attempts: `1`

The `verdict=fail` result matches the expected direction for `tests/fixtures/judge/bad_title_alignment.md`.

Safety boundaries held:

- No key was printed or recorded.
- No paper正文 or PDF was read.
- No file was uploaded.
- No Bailian knowledge base was created.
- No image API was called.
- No automatic retry was performed.

Phase 4 conclusion: Alibaba OpenAI-compatible hello provider is usable, and Qwen-backed judge is usable for small quality-gate excerpts. Real calls must remain explicitly user-authorized.

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
- `client_timeout`
- `server_overloaded_503`
- `server_error_5xx`
- `network_error`
- `unexpected_error`

## Next Stage

After the judge is proven on fixtures, the next phase can consider a small real review-project smoke using user-approved excerpts only. Full paper RAG and image generation remain separate later phases.
