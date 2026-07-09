# Bailian SDK Environment Bridge

## Conclusion

Codex non-interactive shell commands may not see variables that are only exported by `~/.zshrc`. This is expected: `~/.zshrc` is primarily for interactive zsh sessions, while Codex command execution usually runs a non-interactive shell.

Do not move Alibaba Cloud AccessKey values into `~/.zshenv`. That file is read by a much broader set of zsh invocations and increases accidental exposure risk.

## Required For Official KB Management

Official Bailian KB management requires:

```text
ALIBABA_CLOUD_ACCESS_KEY_ID
ALIBABA_CLOUD_ACCESS_KEY_SECRET
WORKSPACE_ID
```

`DASHSCOPE_API_KEY` alone is not sufficient for knowledge-base management.

## Recommended Local Patterns

Use one of these patterns:

- isolated conda environment plus temporary environment variables
- temporary local secret file sourced only for the one manual run
- `zsh -ic` wrapper for a local/manual run when variables are already in `~/.zshrc`

Do not commit secrets. Do not print values. Only print `SET` / `MISSING`.

## Isolated Conda Env

Suggested commands, not run by default:

```bash
conda create -n review-writer-bailian python=3.11 -y
conda activate review-writer-bailian
python -m pip install -U pip
python -m pip install alibabacloud-bailian20231229 alibabacloud-tea-openapi alibabacloud-tea-util requests
```

## Manual Env Bridge

For a local one-off check, if values are already in `~/.zshrc`, run:

```bash
zsh -ic 'python3 -c "import os; keys=[\"ALIBABA_CLOUD_ACCESS_KEY_ID\",\"ALIBABA_CLOUD_ACCESS_KEY_SECRET\",\"WORKSPACE_ID\"]; [print(k + \":\" + (\"SET\" if os.environ.get(k) else \"MISSING\")) for k in keys]"'
```

Local result observed in Phase 6c-ter:

```text
interactive zsh env bridge works
ALIBABA_CLOUD_ACCESS_KEY_ID: SET
ALIBABA_CLOUD_ACCESS_KEY_SECRET: SET
WORKSPACE_ID: SET
```

The check printed only presence status, not values.

## Default Check

```bash
make bailian-sdk-env-check
```

This target is non-strict so ordinary contributors without Alibaba credentials can still run the default test suite.

Manual strict check:

```bash
make bailian-sdk-env-strict-check
```

Strict mode can return nonzero when SDK packages or environment variables are missing.

