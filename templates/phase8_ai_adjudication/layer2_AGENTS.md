# Independent Review Session Rules

- This is an independent, blinded candidate verification session.
- Read no path outside this workspace.
- Do not read parent or sibling directories.
- Do not search for peer-session outputs.
- Do not restore an earlier Codex session.
- Do not ask for results from another session.
- Do not use network access.
- Execute only `WORK_ORDER.md`.
- Do not modify `sources/` or `input/`.
- Do not output hidden reasoning traces.
- Emit only the auditable structured fields required by the schema.

These are procedural context-isolation constraints. They are not an operating-system security sandbox and do not imply statistical independence between model weights.
