# Exact Claim Verifier Isolation Rules

- This is an independent exact-claim verification session.
- Do not inspect skills or `SKILL_MEMORY`.
- Do not read outside this workspace, its parent, or sibling directories.
- Do not access the network or restore previous sessions.
- Do not seek Layer A confidence, rationale, human decisions, gold answers, or other claim verdicts.
- Reopen the listed original source for every claim.
- Do not modify inputs or sources; write only auditable structured results to `output/`.
- Do not expose hidden chain-of-thought.

These are procedural context-isolation constraints, not an operating-system sandbox or a claim of statistical independence.
