# Source-First Layer A Isolation Rules

- This is an independent, source-first evidence inventory session.
- Do not inspect skills or `SKILL_MEMORY`.
- Do not read outside this workspace.
- Do not read parent or sibling directories.
- Do not access the network.
- Do not restore or consult previous sessions.
- Execute only `WORK_ORDER.md`.
- Do not modify `sources/`, `input/`, `schemas/`, or root manifest files.
- Write only to `output/`.
- Do not expose hidden chain-of-thought. Return only the required auditable structures.

These are procedural context-isolation constraints, not an operating-system sandbox or a claim of statistical independence.
