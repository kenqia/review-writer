# Owner-Review Orchestration

This layer makes one Implementation Owner the sole writer for a work package, then routes independent review to fresh read-only sessions. Start with `AGENT_OPERATING_MODEL.md` and `LEADER_PROTOCOL.md`; use the scripts only in preview mode unless explicit execution approval is present.

`make agent-orchestration-check` is offline-only and never invokes a model. `scripts/agent-orchestration/run_dry_run.sh` is preview-only by default. Historical 0.142.4 PARTIAL evidence is neither current failure nor current Grade-4 proof; see `PROVIDER_QUALIFICATION_REPORT.json` for current qualification evidence. Runtime paths, cleanup commands, raw events, stderr, outputs, and opaque session data remain ignored and are omitted from tracked summaries.
