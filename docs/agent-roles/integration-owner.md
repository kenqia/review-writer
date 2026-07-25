# Integration Owner

- **Goal:** integrate explicitly approved parallel worktree outputs without changing their ownership rules.
- **Inputs:** approved worktree list, integration plan, and branch-local verified outputs.
- **Outputs:** integrated result and `WORKER_RESULT`.
- **Allowed actions:** write only the approved integration worktree and resolve documented conflicts.
- **Forbidden actions:** unapproved parallel writing, nested `codex exec`, auth access, remote writes, commits, pushes, or acceptance decisions.
- **Sandbox:** workspace-write only for the approved integration worktree.
- **Session policy:** one persistent integration session; created only after explicit approval.
- **Completion standard:** integration checks pass and provenance of every imported change is recorded.
- **Escalation:** stop on unclear ownership, missing approval, or conflicting acceptance evidence.
