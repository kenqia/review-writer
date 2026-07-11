# Phase 6c-ter: Bailian SDK Environment Bridge

## Summary

This phase documents and checks the local environment needed for the official Bailian SDK path. It explains why Codex may not see values from `~/.zshrc`, adds a safe SET/MISSING checker, and keeps the default workflow offline.

## Added Files

```text
scripts/rag/check_bailian_sdk_env.py
tests/test_bailian_sdk_env_check.py
docs/rag/bailian_sdk_environment.md
docs/pr/phase6c_ter_bailian_sdk_environment_pr.md
```

## Updated Files

```text
Makefile
docs/migration/05_incremental_pr_plan.md
```

## Gates

```bash
make bailian-sdk-env-check
make bailian-sdk-env-strict-check
```

The default check is intentionally non-strict. The strict check is for local operator readiness only.

## Observed Local State

- Current Codex shell: official SDK modules missing; official KB env missing.
- Interactive `zsh -ic` bridge: official KB env shows SET.
- No key values were printed.
- No `.zshenv` change was made or recommended.

## Safety

- No Bailian API call.
- No upload.
- No knowledge-base creation.
- No PDF read.
- No Qwen/MinerU/image API call.

## Next

Install the official SDK in an isolated environment and run the strict check from that environment. Only then consider the explicitly authorized `allow official bailian sdk pilot` path.

