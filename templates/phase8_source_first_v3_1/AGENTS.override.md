# Independent Source-First Layer A Session

- This is an independent, context-isolated review session.
- Read only files inside the current workspace.
- Do not inspect parent directories, sibling directories, or other workspaces.
- Do not recover or resume an earlier Codex session.
- Do not use network access, skills, agent delegation, Codex CLI, or background tasks.
- Follow only `WORK_ORDER.md` and the local schemas and validators.
- Do not modify `sources/`, `input/`, `schemas/`, manifests, or instructions.
- Write only the required structured files under `output/`.
- Do not output hidden chain-of-thought, confidence percentages, or long rationale.

These are procedural context-isolation constraints. They are not an operating-system security sandbox and do not imply statistical independence between model weights.
