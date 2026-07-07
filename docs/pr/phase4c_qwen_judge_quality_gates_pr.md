# Phase 4c Qwen Judge Quality Gates PR

## PR Title

`feat: add qwen judge quality gate`

## Summary

This PR connects the Phase 2 LLM judge placeholders to an offline-first judge layer. The default judge is deterministic and local. Qwen-backed judging is available only when explicitly requested with `--judge-mode qwen --allow-network`.

## Changed Files

- `review_writer/judges/base.py`: judge task/result dataclasses.
- `review_writer/judges/offline_judge.py`: deterministic offline placeholder.
- `review_writer/judges/qwen_judge.py`: guarded Qwen OpenAI-compatible judge.
- `scripts/llm_judges/qwen_review_quality_judge.py`: standalone judge CLI.
- `scripts/validators/validate_review_quality.py`: judge-mode and judge-output integration.
- `tests/test_qwen_judge_safety.py`: offline safety tests.
- `tests/fixtures/judge/*.md`: small synthetic fixtures.
- `docs/providers/qwen_judge_runbook.md`: runbook.
- `Makefile`: `judge-check`.

## Validator Parameters

```bash
--judge-mode offline|qwen
--allow-network
--judge-output-json /tmp/judge_report.json
--judge-output-md /tmp/judge_report.md
```

Default:

```bash
--judge-mode offline
```

## Implemented Task Types

- `section_title_alignment`
- `review_title_alignment`
- `prompt_leakage_semantic`
- `chem_formula_review_assist`

## Safety Contract

- Default path does not call Qwen.
- Qwen path refuses network without `--allow-network`.
- No key output.
- No PDF read.
- No file upload.
- No Bailian knowledge base creation.
- No image API.
- No review正文 generation.

## Validation Commands

```bash
make smoke
make quality-check
make qoderwork-check
make provider-check
make qwen-hello-dry-run
make judge-check
python tests/test_qwen_judge_safety.py
```

## Known Limits

- Offline judge does not make semantic claims; it only records deterministic placeholder results.
- Qwen judge currently handles small markdown excerpts/fixtures, not full project-scale review artifacts.
- Real Qwen judge calls should be manually approved one run at a time.

## Timeout Hardening Addendum

The first controlled real Qwen judge call timed out, while the earlier hello Qwen smoke passed. This suggests the endpoint and key path are usable, and the immediate hardening target is the judge request shape.

Added:

- `--timeout-seconds 90`
- `--max-output-tokens 128`
- `--compact`
- `--task-limit 1`
- `prompt_chars`
- `input_excerpt_chars`
- `rubric_chars`
- `timeout_seconds`
- `max_output_tokens`
- `compact_mode`
- `elapsed_seconds`
- `error_category`
- `network_attempts`

The next real retry must wait for the exact user confirmation:

```text
allow qwen judge retry once
```

## Retry Validation Result

After timeout hardening, the single controlled retry succeeded:

- status: `pass`
- summary: `1 judge tasks, 0 errors, 0 disabled`
- judge_mode: `qwen`
- result_status: `ok`
- verdict: `fail`
- model: `qwen3.7-plus`
- region: `cn-beijing`
- prompt_chars: `676`
- timeout_seconds: `90.0`
- max_output_tokens: `128`
- compact_mode: `True`
- elapsed_seconds: `27.937`
- network_attempts: `1`

The `bad_title_alignment.md` fixture received `verdict=fail`, which is the expected direction.

No key was printed or committed, no paper正文/PDF was read, no file was uploaded, no Bailian knowledge base was created, no image API was called, and no automatic retry was performed.

Phase 4 is now validated at two levels:

- Alibaba OpenAI-compatible hello provider works.
- Qwen-backed judge works for controlled quality-gate excerpts.

All future real calls must continue to require explicit user authorization.
