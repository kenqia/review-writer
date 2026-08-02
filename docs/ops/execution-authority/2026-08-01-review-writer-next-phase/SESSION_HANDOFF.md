# Review-Writer Next Phase Session Handoff

Status: `READY_FOR_FRESH_REPAIR_OWNER`

Session epoch: `2`

Role: `C1 Canonical Review HOLD Disposition`

Context compactions in this Coordinator session: `0`

## Start and authority state

```text
STARTED_FROM_HEAD=54dbef846aaf7a621e72572cc7f21ffda0c6d223
CODE_HEAD=24625585d066fd7e8a96c2e2701bd77d19c0077a
HANDOFF_HEAD_POLICY=use the current descendant docs-only HOLD-disposition HEAD after MANIFEST verification; code tree must still match CODE_HEAD
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

The HOLD-disposition commit changes Git HEAD but not the code tree. A receiver
must verify that current HEAD descends from `CODE_HEAD`, the manifest passes, and
no later code commit exists without a matching handoff update.

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

Frozen repair order:

```text
SOLE_NEXT_ACTION_ID=NP-CAN-PUBLISH-001
P1_1_STATUS=READY_FOR_REPAIR_OWNER_ATTEMPT_1
P1_1_STOP_LINE=exclusive anchor reservation, ownership-aware rollback, paired target/anchor publication
P1_2_ID=NP-CAN-RECEIPT-001
P1_2_STATUS=SERIALIZED_AFTER_NP-CAN-PUBLISH-001
WRITE_GROUP=dual_parse_bootstrap
OWNED_PATHS=review_writer/project/dual_parse_bootstrap.py,tests/test_dual_parse_bootstrap.py
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

Launch exactly one fresh Repair Owner for `NP-CAN-PUBLISH-001`. The Owner creates
an isolated worktree and branch from the latest verified integration HEAD; the
integration worktree remains untouched. The rejected candidate chain may be
transplanted only inside that repair branch as implementation context and must be
followed by a RED test and the minimal P1-1 repair.

The Owner must not fix, suppress, or claim closure of `NP-CAN-RECEIPT-001`. It
returns one local commit chain, exact parent, focused RED/GREEN evidence, clean
status, and a bounded handoff for one later fresh read-only Luna Reviewer.

## Required receiver startup

1. Read project `AGENTS.md` and the immutable Approved Spec.
2. Run `sha256sum -c` on `MANIFEST.sha256`.
3. Read `CONTINUATION_EXECUTION_SPEC.md`, `EXECUTION_AUTHORITY.md`,
   `FINDING_INVENTORY.json`, and this handoff.
4. Verify current HEAD, ancestry from `CODE_HEAD`, clean status, and no active Git
   operation or competing integration writer.
5. Create a new repair worktree from that exact integration HEAD; do not edit the
   integration worktree.
6. State `NP-CAN-PUBLISH-001` and its stop line, reproduce RED, then repair only
   that finding.

## Forbidden next actions

- no writes in the integration worktree and no direct integration of the rejected
  candidate TIP;
- no repair of `NP-CAN-RECEIPT-001` in the P1-1 Owner session;
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
