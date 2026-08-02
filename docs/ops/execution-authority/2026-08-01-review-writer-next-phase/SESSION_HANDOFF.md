# Review-Writer Next Phase Session Handoff

Status: `READY_FOR_FRESH_SESSION`

Session epoch: `1`

Role: `Continuation Authority Persistence`

Context compactions in this persistence session: `0`

## Start and authority state

```text
STARTED_FROM_HEAD=24625585d066fd7e8a96c2e2701bd77d19c0077a
CODE_HEAD=24625585d066fd7e8a96c2e2701bd77d19c0077a
HANDOFF_HEAD_POLICY=use the current descendant docs-only HEAD after MANIFEST verification; code tree must match CODE_HEAD
INTEGRATION_BRANCH=codex/review-writer-next-phase-integration
INTEGRATION_WORKTREE=/home/kenqia/my_folder/review-writer/.worktrees/review-writer-next-phase-integration
WORKTREE_CLEAN_AT_START=true
GIT_OPERATION_IN_PROGRESS_AT_START=false
AUTHORITY_STATUS=PRE_T0_PENDING_INPUT
INPUT_READY=NOT_READY
CODE_FREEZE_READY=NOT_READY
RUNTIME_READY=NOT_READY
T0=NOT_RECORDED
USER_INPUT_REQUESTED=false
USER_ACTIONS_AFTER_T0=0
```

The new docs-only continuation commit changes Git HEAD but not the code tree. A
receiver must verify that current HEAD descends from `CODE_HEAD`, the manifest
passes, and no later code commit exists without a matching handoff update.

## Integrated at the code head

```text
PDF_SYMLINK_INTEGRATION=7fa882d2600647f7613dd23a22e4698c373d6f8d
GENERIC_PROVENANCE_INTEGRATION_1=1c573a17b01aa4e43345b0f486cbdaa49f9ad621
GENERIC_PROVENANCE_INTEGRATION_2=acc550df8727665d94df496a0532ffc9089a6102
SCHEDULER_LINEAGE_INTEGRATION=fa5cef88b151a78bab266df5f9ee6422c1334d8b
CORPUS_COUNT_INTEGRATION=24625585d066fd7e8a96c2e2701bd77d19c0077a
```

## Reported checks tied to the stopped Coordinator

These results came from the stopped Coordinator report and must not be presented
as fresh for a later code HEAD without rerun:

```text
FOCUSED_TESTS_REPORTED=19 passed, 1 warning
SCHEDULER_TESTS_REPORTED=44 passed
AGENT_ORCHESTRATION_CHECK_REPORTED=PASS
SMOKE_REPORTED=PASS
QUALITY_CHECK_REPORTED=PASS
```

## Pending state

Immediate immutable candidate chain:

```text
CANDIDATE_BASE=acc550df8727665d94df496a0532ffc9089a6102
CANDIDATE_COMMIT_1=f754f07065b7cf65dd7fcf75925105933fd23616
CANDIDATE_COMMIT_2=8a7502eaec7a2e7ea881a5a7de8adeff6d784694
CANDIDATE_TIP=8a7502eaec7a2e7ea881a5a7de8adeff6d784694
CANDIDATE_PATHS=review_writer/project/dual_parse_bootstrap.py,tests/test_dual_parse_bootstrap.py
REVIEW_STATUS=PENDING_INDEPENDENT_READ_ONLY_REVIEW
```

Reference-only or pending-disposition commits, never direct cherry-pick targets:

```text
23813a2ebe7e4d9587c5ec34a2a1b69e6b89df86
7c4f3023155d92bb303b04320e44f88a3922270b
404650de5c77aa13ae05c638708c3b762716c45b
32d74ffee3d818f3b224023785fb714dcbf0a529
e3a0ac82324e52757aa960bd2e17b77981d0917f
```

Active finding IDs and their stop lines are authoritative only in
`FINDING_INVENTORY.json`.

## Sole next action

Launch exactly one fresh, independent, read-only Luna 5.6 max code Reviewer for
`acc550df8727665d94df496a0532ffc9089a6102..8a7502eaec7a2e7ea881a5a7de8adeff6d784694`.
The Reviewer evaluates only canonical external-anchor binding and transactional
publication in the two owned files. It must not compare current integration
`HEAD..TIP` as a replacement tree and must make zero writes.

Expected result: `ACCEPT` or numbered `HOLD` P0/P1 findings with evidence,
affected paths, and acceptance tests.

## Required receiver startup

1. Read project `AGENTS.md` and the immutable Approved Spec.
2. Run `sha256sum -c` on `MANIFEST.sha256`.
3. Read `CONTINUATION_EXECUTION_SPEC.md`, `EXECUTION_AUTHORITY.md`,
   `FINDING_INVENTORY.json`, and this handoff.
4. Verify current HEAD, ancestry from `CODE_HEAD`, clean status, and no active Git
   operation or competing integration writer.
5. State the sole next action and stop line before dispatch.

## Forbidden next actions

- no implementation, cherry-pick, code review expansion, or new repair branch
  before the canonical Reviewer result;
- no corpus request, T0, project bootstrap, Dashboard/runtime claim, or Playwright;
- no direct integration of any reference-only candidate;
- no push, deploy, remote write, issue filing, external sync, worktree cleanup,
  reset, checkout discard, old checkbox modification, or Approved Spec edit;
- no script as Content Agent and no API as Dashboard.

```text
PUSHED=false
DEPLOYED=false
REMOTE_WRITE=false
PLAN_CHECKBOX_CHANGED=false
SENSITIVE_DATA_EXPOSED=false
```
