# Isolated Dynamic Dry-Run Report

Status: `PARTIAL`.

## Attempt 1 - Initial ORCH-001 Validation

- Date: `2026-07-16`.
- CLI version: `codex-cli 0.142.4`.
- Requested model: `gpt-5.6-terra` with medium reasoning and a read-only sandbox.
- Provider: `not-reported-by-codex-cli`.
- First exec: `MODEL_UNAVAILABLE` after an upstream `502` before a `WORKER_RESULT` was produced.
- Thread captured: yes.
- Resume: not attempted under the then-active no-retry policy.
- First and resumed contracts: not validated.
- Fallback model: false.
- Metadata fallback warning: yes; it did not indicate a model switch.
- Agent file write observed: no.
- The legacy fixed fixture was later recreated offline after its original raw runtime was removed by the environment. Missing raw events were not fabricated.

## Attempt 2 - Dynamic Closure Supplement

- Date: `2026-07-16`.
- CLI capability checks: PASS for `codex --version`, `codex exec --help`, and `codex exec resume --help`.
- Formal runner gap `ORCH-001-DYN-01`: repaired by resuming the recorded Implementation Owner session; focused tests and both static gates passed.
- Model, reasoning, sandbox: `gpt-5.6-terra`, medium, read-only.
- Task ID: `DRYRUN-002`.
- Health check 1: `PARTIAL`; thread captured; no result; explicit transient `upstream_error / request_failed / retry later`.
- Retry decision: allowed transient-upstream retry; waited 60 seconds and used a different fresh fixture.
- Health check 2: `PARTIAL`; thread captured; no result; the same transient upstream error class.
- Full exec-resume flow: not run because both permitted health requests failed.
- First/second contract validation and same-session verification: not run.
- Fallback model used: false.
- Metadata fallback observed: true on both health checks.
- Unauthorized Agent writes: none observed; both fixture content inventories remained under the formal read-only runner.
- Static regression: PASS.

## Final Decision

- ORCH-001 overall status: `PARTIAL`.
- Dynamic environment: `ENVIRONMENT_UNDETERMINED` / `UPSTREAM_UNAVAILABLE`.
- Dynamic infrastructure: statically validated; the full exec-resume path was not exercised because the health gate did not pass.

This tracked report is sanitized. It contains no session/thread value, full prompt, model output, endpoint URL, raw event, raw stderr, auth material, token, or private payload.

Retained fixtures:

```text
/tmp/kenqia-agent-orchestration-dry-run/
/tmp/kenqia-agent-orchestration-dry-run-20260716T172836-health-1/
/tmp/kenqia-agent-orchestration-dry-run-20260716T173524-health-2/
```

Manual cleanup only:

```bash
rm -rf /tmp/kenqia-agent-orchestration-dry-run/
rm -rf /tmp/kenqia-agent-orchestration-dry-run-20260716T172836-health-1/
rm -rf /tmp/kenqia-agent-orchestration-dry-run-20260716T173524-health-2/
```
