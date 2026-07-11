# Phase 4b Controlled Hello Qwen PR

## PR Title

`feat: add controlled hello qwen check`

## Summary

This PR adds a guarded script for a single minimal hello Qwen request through Alibaba's OpenAI-compatible endpoint. By default it only supports dry-run/offline validation. Real network access requires `--allow-network` and a separate explicit user confirmation.

## Changed Files

- `scripts/hello_qwen_openai_compatible.py`: controlled hello Qwen script.
- `tests/test_hello_qwen_safety.py`: no-network safety tests.
- `Makefile`: adds `qwen-hello-dry-run`.
- `docs/providers/hello_qwen_runbook.md`: operator runbook.
- `docs/pr/phase4b_hello_qwen_pr.md`: PR notes.
- `docs/migration/05_incremental_pr_plan.md`: Phase 4b plan update.

## Safety Contract

- No real call without `--allow-network`.
- No real call until the user replies `allow hello qwen`.
- No key printing.
- No `.env` write.
- No shell rc write.
- No paper reading.
- No file upload.
- No Bailian knowledge base creation.
- No image generation.

## Offline Validation

```bash
make smoke
make quality-check
make qoderwork-check
make provider-check
make qwen-hello-dry-run
python tests/test_hello_qwen_safety.py
python scripts/hello_qwen_openai_compatible.py \
  --dry-run \
  --output-json /tmp/qwen_hello_dry.json \
  --output-md /tmp/qwen_hello_dry.md
```

## Real Call Prerequisites

The user must set temporary local environment variables:

```bash
export DASHSCOPE_API_KEY='paste your key locally, not into chat'
export BAILIAN_WORKSPACE_ID='your WorkspaceId'
export BAILIAN_REGION='cn-beijing'
export BAILIAN_MODEL='qwen-plus'
```

Then explicitly reply:

```text
allow hello qwen
```

## Known Limits

- The script depends on the `openai` Python package for the real call and does not install it automatically.
- It sends only a fixed hello prompt and is not a general provider integration.
- Failure is classified and reported; the script does not auto-retry or auto-fix config.
