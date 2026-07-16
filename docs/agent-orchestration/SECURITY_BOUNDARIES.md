# Security Boundaries

Launchers use validated paths and Python `subprocess` argument arrays only. They do not use `eval` or `shell=True`. Prompts forbid nested `codex exec`, and the system performs no commits, pushes, PRs, installs, auth reads, remote writes, publication, or deployment.

Raw JSON events, model output, stderr, and opaque session references are stored under ignored `.agent-orchestration-runs/`. Tracked summaries are sanitized to exclude those fields and raw logs.
