# Write Ownership Policy

- A task package records one `implementation_owner` and one worktree.
- Only that Owner may use workspace-write in that worktree.
- Reviewers and verifier always use `read-only` and fresh sessions.
- Owner replacement needs Leader approval and a documented reason; it never happens silently.
- Parallel work requires explicit worktree approval and an Integration Owner; no shared-worktree writers.
- Commits, pushes, PRs, installs, auth reads, deployments, and remote writes are outside this system.
