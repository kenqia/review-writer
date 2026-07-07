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
