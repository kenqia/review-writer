# Model Configuration

Role descriptors and launchers use `gpt-5.6-terra` with `medium` reasoning and explicit `model_provider=custom` for review-writer defaults. Live qualification requires exact `codex-cli 0.144.5` and bundled Terra catalog metadata. If the selected model cannot run, the launcher reports that transport condition; it never silently falls back or uses Output Schema.

Sandbox is separately explicit. Preview uses `read-only`; an executable writable Owner launch requires both `--execute` and `--allow-workspace-write`.
