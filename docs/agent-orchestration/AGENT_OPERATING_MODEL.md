# Agent Operating Model

One work package and worktree has one persistent writable Implementation Owner. The Leader scopes and accepts work but does not become the writer. Scientific Reviewer, Artifact Reviewer, and Final Verifier are fresh read-only sessions; Explorer is optional and fresh read-only. Repairs return to the recorded Owner through explicit resume.

Parallel writing is forbidden unless a human approves isolated worktrees and assigns an Integration Owner. Review output is merged into actionable findings and sent back to the same Owner. A paper is never auto-accepted.

All Worker launch prompts forbid nested `codex exec`; only the Leader may invoke outer orchestration. Final Verifier reports are limited to `PASS`, `BLOCKED`, or `ENVIRONMENT_UNDETERMINED`, while the Leader maps the overall run/release to `PASS`, `PARTIAL`, or `FAIL`. Default operations are previews or offline checks. Runtime events, full output, stderr, and session identifiers remain only in ignored runtime directories.
