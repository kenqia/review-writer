# Model Configuration

Role descriptors and launchers use `gpt-5.6-terra` with `medium` reasoning for review-writer defaults. Effective selection precedence is: project role configuration, explicit invocation override, then the Codex default. If the selected model cannot run, the launcher reports that condition; it never silently falls back.

Sandbox is separately explicit. Preview uses `read-only`; an executable writable Owner launch requires both `--execute` and `--allow-workspace-write`.
