# Leader protocol: no-Output-Schema workflow

The current highest-capability main session is the Leader. It scopes, interprets Worker prose, and performs human checkpoints. It is never launched by a Worker launcher.

## States

`GRILLING → EXECUTION_BRIEF → EXECUTING → HUMAN_CHECKPOINT_REQUIRED`

No state transition is inferred from a Worker word such as “PASS” or “FAIL”. The Leader uses the diff, files, deterministic checks, and fresh Reviewer evidence.

## Roles and boundaries

One persistent writable Implementation Owner works in one worktree. Repairs resume that same Owner. Scientific, artifact, and final reviews are fresh read-only sessions. Native subagent dispatch and nested dispatch are disabled/unqualified. The runner is a transport/evidence layer: it records lifecycle facts and stores prose privately; it does not validate or grade Worker prose.

Every external Worker uses `gpt-5.6-terra`, `model_provider=custom`, `medium` reasoning, an explicit sandbox, `--json`, and `--output-last-message`. No Worker command uses `--output-schema`. There is no automatic retry, provider/model fallback, or automatic second Writer.

## Qualification and rollback

Live execution is allowed only after exact CLI `0.144.5` and bundled Terra metadata preflight. Any upgrade is unqualified until the same preflight and the Q0–Q7 protocol are reviewed. Roll back by selecting the known-good `0.144.5` binary/configuration outside this repository; do not alter the workflow to introduce a fallback.

Legacy JSON Schemas remain historical artifacts for deterministic offline package checks. They are non-enforcing and absent from live runtime calls.
