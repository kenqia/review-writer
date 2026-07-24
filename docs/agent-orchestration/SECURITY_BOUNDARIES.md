# Security Boundaries

Launchers use validated paths and Python `subprocess` argument arrays only. They do not use `eval` or `shell=True`. Prompts forbid nested `codex exec`, and the system performs no commits, pushes, PRs, installs, auth reads, remote writes, publication, or deployment.

Raw JSON events, model output, stderr, opaque session references, runtime locations, and cleanup commands are stored under ignored `.agent-orchestration-runs/`. Tracked summaries omit those values.
