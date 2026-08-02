# Review-Writer Next Phase Session Handoff

Status: `READY_FOR_PARALLEL_READ_ONLY_REVIEW_WAVE`

Session epoch: `3`

Role: `Repair Intake And Parallel Review Dispatch`

Context compactions in this Coordinator session: `0`

## Start and authority state

```text
STARTED_FROM_HEAD=17b06f4b54e8b64b0de519ed4562277f4ec7a02f
CODE_HEAD=24625585d066fd7e8a96c2e2701bd77d19c0077a
HANDOFF_HEAD_POLICY=use the current descendant docs-only review-wave HEAD after MANIFEST verification; integration code tree must still match CODE_HEAD
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

The review-wave dispatch commit changes Git HEAD but not the integration code
tree. A receiver must verify that current HEAD descends from `CODE_HEAD`, the
manifest passes, and no later integration code commit exists without a matching
handoff update.

## Integrated at the code head

```text
PDF_SYMLINK_INTEGRATION=7fa882d2600647f7613dd23a22e4698c373d6f8d
GENERIC_PROVENANCE_INTEGRATION_1=1c573a17b01aa4e43345b0f486cbdaa49f9ad621
GENERIC_PROVENANCE_INTEGRATION_2=acc550df8727665d94df496a0532ffc9089a6102
SCHEDULER_LINEAGE_INTEGRATION=fa5cef88b151a78bab266df5f9ee6422c1334d8b
CORPUS_COUNT_INTEGRATION=24625585d066fd7e8a96c2e2701bd77d19c0077a
```

## C1 Reviewer result and evidence boundary

```text
REVIEW_RESULT=HOLD
REVIEWED_BASE=acc550df8727665d94df496a0532ffc9089a6102
REVIEWED_TIP=8a7502eaec7a2e7ea881a5a7de8adeff6d784694
REVIEWER_MANIFEST_REPORTED=7/7 OK
REVIEWER_TIP_FOCUSED_TESTS_REPORTED=27 passed
COORDINATOR_MANIFEST_AT_START=7/7 OK
INTEGRATION_CODE_CHANGED=false
```

The Reviewer test count is reported evidence tied to the rejected candidate TIP,
not fresh evidence for a future repair. The Coordinator independently inspected
the cited code and confirmed both findings are technically present.

## Pending state

The immutable candidate chain is `HOLD` and must not be integrated unchanged:

```text
CANDIDATE_BASE=acc550df8727665d94df496a0532ffc9089a6102
CANDIDATE_COMMIT_1=f754f07065b7cf65dd7fcf75925105933fd23616
CANDIDATE_COMMIT_2=8a7502eaec7a2e7ea881a5a7de8adeff6d784694
CANDIDATE_TIP=8a7502eaec7a2e7ea881a5a7de8adeff6d784694
CANDIDATE_PATHS=review_writer/project/dual_parse_bootstrap.py,tests/test_dual_parse_bootstrap.py
REVIEW_STATUS=HOLD
CANDIDATE_DIRECT_INTEGRATION=FORBIDDEN
```

Completed attempt-1 repair chain awaiting independent review:

```text
SOLE_NEXT_ACTION_ID=NP-CAN-PUBLISH-001
P1_1_STATUS=PENDING_INDEPENDENT_REVIEW_ATTEMPT_1
P1_1_STOP_LINE=exclusive anchor reservation, ownership-aware rollback, paired target/anchor publication
REPAIR_BASE=17b06f4b54e8b64b0de519ed4562277f4ec7a02f
TRANSPLANT_1=88573cc5ffcc801cb566824d7391a30671186e02
TRANSPLANT_2=3a2165d26892e69b98d06deecbdcca99d359bb89
REPAIR_COMMIT=1baa9f9e21c70337d67bbaee3e6033bb7e11e2c6
REPAIR_PARENT=3a2165d26892e69b98d06deecbdcca99d359bb89
REPAIR_TIP=1baa9f9e21c70337d67bbaee3e6033bb7e11e2c6
REPAIR_PATHS=review_writer/project/dual_parse_bootstrap.py,tests/test_dual_parse_bootstrap.py
OWNER_RED_REPORTED=1 failed, 27 deselected
OWNER_GREEN_REPORTED=28 passed in 0.64s
COORDINATOR_FOCUSED_FRESH=28 passed in 0.52s
TRANSPLANT_PATCH_IDS_MATCH=true
P1_2_ID=NP-CAN-RECEIPT-001
P1_2_STATUS=SERIALIZED_AFTER_NP-CAN-PUBLISH-001
PARALLEL_READ_ONLY_ACTION=NP-ORCH-DISPOSITION-001
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

Launch one fresh, independent, read-only Luna 5.6 max Reviewer for
`17b06f4b54e8b64b0de519ed4562277f4ec7a02f..1baa9f9e21c70337d67bbaee3e6033bb7e11e2c6`.
The Reviewer verifies transplant identity, the final repair, tests, and rollback
behavior only within `NP-CAN-PUBLISH-001`. The already frozen
`NP-CAN-RECEIPT-001` is outside this review stop line and cannot be rediscovered
or used to HOLD P1-1.

Expected result is `ACCEPT` or numbered `HOLD` P0/P1 findings with current
evidence, affected paths, and an acceptance test. The Reviewer makes zero writes.

## Parallel read-only action

At the same time, one different fresh read-only Luna 5.6 max Reviewer may dispose
`NP-ORCH-DISPOSITION-001`. It compares commits `404650de`, `32d74ffe`, and
`e3a0ac82` to the current integrated scheduler lineage at code HEAD `24625585...`.
For each candidate it returns `SUPERSEDED` with evidence or one bounded
`CURRENT_P1` finding. It must not cherry-pick, repair, or broaden beyond persisted
source resolution and bounded corpus-count parsing.

These two sessions are disjoint and may run concurrently. The next Coordinator
collects both results in one session; on canonical ACCEPT it integrates the three
repair-branch commits in order, verifies the current tree, records disposition,
and immediately opens the serialized P1-2 lane.

## Required receiver startup

1. Read project `AGENTS.md` and the immutable Approved Spec.
2. Run `sha256sum -c` on `MANIFEST.sha256`.
3. Read `CONTINUATION_EXECUTION_SPEC.md`, `EXECUTION_AUTHORITY.md`,
   `FINDING_INVENTORY.json`, and this handoff.
4. Verify current HEAD, ancestry from `CODE_HEAD`, clean status, and no active Git
   operation or competing integration writer.
5. Accept exactly one assigned read-only lane and state its immutable base, tip or
   candidates, paths, and stop line before inspection.
6. Return the bounded result without modifying any worktree or Git state.

## Forbidden next actions

- no writes in the integration or repair worktree and no direct integration of
  the rejected candidate TIP or pending repair chain;
- no review expansion into `NP-CAN-RECEIPT-001` during P1-1 review;
- no second repair attempt or new finding without a fresh independent Reviewer
  result and Coordinator disposition;
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
