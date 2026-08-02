# Review-Writer Next Phase Continuation Execution Spec

Status: `APPROVED_EXECUTION_CONTINUATION`

Approved: 2026-08-02

Spec ID: `review-writer-next-phase-continuation-2026-08-02`

> **2026-08-03 priority notice.** This addendum remains a hash-bound record of
> prior constraints and evidence, but its inherited stage order, sole-next
> action, finding inventory, and recursive Reviewer/Repair route are superseded
> for active work by
> [docs/product/DELIVERABLE_FIRST_CORE_CONTRACT.md](../../../product/DELIVERABLE_FIRST_CORE_CONTRACT.md).
> A legacy item is PARKED_REFERENCE_ONLY unless it passes that contract's
> GOLD_DELTA or TRACE_DELTA admission gate. The immutable Approved Spec's
> scientific and safety constraints remain non-amendable.

## 1. Purpose and non-amendment rule

This document restores bounded, file-governed execution after the first
next-phase preparation session became too long and expanded into a recursive
Reviewer/Repair tree. It is an execution addendum only.

The semantic authority remains:

`docs/superpowers/specs/2026-08-01-review-writer-next-phase-unique-requirements.md`

Its normalized SHA-256 remains:

`105205dd8f5b65dadda3d4ea4d964f510cde104907bab59d56510eddd847da7c`

This addendum must not edit or reinterpret that file, lower a gate, add product
scope, change a model assignment, request corpus early, or turn a script into a
Content Agent or an API into a Dashboard path. A conflict stops writes as
`AUTHORITY_DRIFT_BLOCKED`; a terminal report maps that condition to the nearest
Approved Spec category, normally `CODE_BLOCKED` or `ORCHESTRATION_BLOCKED`.

## 2. Normative and factual authority

Within the project, normative instructions are read in this order:

1. current system, developer, and explicit user safety instructions;
2. project `AGENTS.md`;
3. the immutable Approved Spec;
4. this continuation execution addendum;
5. `EXECUTION_AUTHORITY.md`;
6. `FINDING_INVENTORY.json`;
7. `SESSION_HANDOFF.md`.

Current Git, filesystem, test, and runtime evidence always determine factual
state. If a status document disagrees with current evidence, stop before writing,
record the exact mismatch, and do not silently choose the more convenient value.

## 3. Hash-bound core read pack

Every new Coordinator, Owner, Repair Owner, Reviewer, runtime session, and every
session recovering from one context compaction must verify
`MANIFEST.sha256` and read the role-appropriate core pack before acting.

| Order | File | Required reader |
| --- | --- | --- |
| 1 | `AGENTS.md` | everyone |
| 2 | immutable Approved Spec | every new session; Reviewer reads relevant full sections plus hash verification |
| 3 | `CONTINUATION_EXECUTION_SPEC.md` | everyone |
| 4 | `EXECUTION_AUTHORITY.md` | everyone |
| 5 | `FINDING_INVENTORY.json` | Coordinator, Owner, Repair Owner, code Reviewer |
| 6 | `SESSION_HANDOFF.md` | everyone |
| 7 | `docs/agent-memory.md` session-rotation entry | Coordinator only |

Startup verification is fail-closed:

```bash
sha256sum -c docs/ops/execution-authority/2026-08-01-review-writer-next-phase/MANIFEST.sha256
git status --short --branch
git show -s --format='%H %P %s' HEAD
```

Also verify there is no `CHERRY_PICK_HEAD`, `MERGE_HEAD`, rebase state, unknown
integration writer, or mutable project writer. A chat summary, branch name, test
count copied from an older HEAD, or Reviewer adjective is not authority.

## 4. Verified continuation starting point

The prior Coordinator stopped cleanly and reported at handoff:

```text
INTEGRATION_WORKTREE=/home/kenqia/my_folder/review-writer/.worktrees/review-writer-next-phase-integration
INTEGRATION_BRANCH=codex/review-writer-next-phase-integration
CONTINUATION_BASE_CODE_HEAD=24625585d066fd7e8a96c2e2701bd77d19c0077a
WORKTREE_CLEAN=true
GIT_OPERATION_IN_PROGRESS=false
AUTHORITY=PRE_T0_PENDING_INPUT
CODE_FREEZE_READY=NOT_READY
RUNTIME_READY=NOT_READY
INPUT_READY=NOT_READY
T0=NOT_RECORDED
USER_INPUT_REQUESTED=false
```

Repository inspection independently confirmed the HEAD, clean state, Spec hash,
and absence of an in-progress merge/cherry-pick/rebase. Test results in the stop
report are retained as reported evidence, not silently upgraded to fresh evidence
for a later HEAD:

```text
FOCUSED_REPORTED=19 passed, 1 warning
SCHEDULER_REPORTED=44 passed
AGENT_ORCHESTRATION_CHECK_REPORTED=PASS
SMOKE_REPORTED=PASS
QUALITY_CHECK_REPORTED=PASS
```

Integrated and reported ACCEPT at the continuation base:

- external PDF parent-component symlink rejection;
- Generic source-PDF provenance validation and mandatory key;
- scheduler source-lineage binding;
- fail-closed persisted variable-N corpus count handling.

The sole next action is still one fresh, independent, read-only code Reviewer for
candidate tip `8a7502eaec7a2e7ea881a5a7de8adeff6d784694` under section 9.

## 5. Session health contract

```text
COORDINATOR_ACTIVE_WORK_MINUTES=75
HANDOFF_RESERVE_MINUTES=15
COORDINATOR_HARD_LIMIT_MINUTES=90
OWNER_OR_REVIEWER_SCOPE=one immutable task
FIRST_CONTEXT_COMPACTION=HANDOFF_REQUIRED
NEW_WORK_AFTER_FIRST_COMPACTION=false
SECOND_CONTEXT_COMPACTION=PROHIBITED
CHAT_SUMMARY_IS_AUTHORITY=false
```

Rules:

1. Prefer a fresh session at every stage boundary and before any expected context
   compaction. The Coordinator remains light and does not become a Repair Owner.
2. At minute 75, stop starting work. Use the remaining 15 minutes for current-HEAD
   checks, manifest verification, inventory update, handoff, and a bounded commit.
3. If context is compacted once, immediately stop discovery, dispatch, review
   expansion, and new code. Re-read the core pack, finish only the current atomic
   operation if safe, persist handoff, and end the session.
4. No session may continue after a second compaction. Open a fresh session instead.
5. A session may not hand off a dirty integration worktree. If an atomic clean
   checkpoint cannot be reached without discarding state, return
   `DIRTY_HANDOFF_BLOCKED`; never reset, checkout, clean, or delete worktrees.
6. Every handoff records exact commit and parent hashes, checks tied to that HEAD,
   active finding IDs, one next action, and forbidden actions. Natural-language
   optimism never changes a gate.

## 6. Parallel execution contract

Total live concurrency remains `min(4, Codex available concurrency)` from the
Approved Spec. A normal wave is one light Coordinator plus up to three bounded
Owner/Reviewer sessions.

- Exactly one Coordinator may write the integration worktree.
- Exactly one named actor may write the authoritative mutable project.
- Parallel writers require separate approved worktrees and non-overlapping path
  ownership. Paths that overlap are serialized even when agents are available.
- The Coordinator alone creates top-level task sessions. Owners and Reviewers do
  not recursively launch replacement trees.
- A Reviewer is fresh, read-only, and receives one immutable commit or explicitly
  bounded commit chain, its actual parent, required files, and acceptance checks.
- A repair begins from the latest verified integration HEAD. Historical repair
  parents are reference evidence only.
- An ACCEPTed repair is integrated, verified, or explicitly parked with a reason
  in the same Coordinator session. It may not remain silently stranded.
- Input/canonical work touching `dual_parse_bootstrap.py` is serialized. Scheduler
  disposition on `scheduler_contract.py` may run in parallel only after the sole
  canonical review action has completed and the next wave is recorded.

## 7. Finding freeze and stop line

`FINDING_INVENTORY.json` is the only active P0/P1 list. A new finding may enter it
only when all fields below exist:

- exact Approved Spec P0/P1 class;
- unique finding ID and severity;
- current or bounded-parent evidence;
- affected paths and one stop line;
- failing test or deterministic reproduction when applicable;
- one Owner and one fresh Reviewer;
- at most two attempts for that immutable finding.

Anything else is `MVP_BACKLOG`. Reviewers must not add new threat-model dimensions
after their assigned stop line. If attempt two fails, return `CODE_BLOCKED` with
the required unique recovery action instead of creating another recursive branch.

## 8. Fixed continuation stages

```text
C0  Persist this addendum, inventory, handoff, manifest, and docs-only anchor
C1  Fresh read-only review of canonical candidate chain ending at 8a7502ea
C2  ACCEPT: integrate the two canonical commits in order; HOLD: one bounded repair
C3  From latest integration HEAD, close Input & Provenance findings in inventory
    while a disjoint read-only session dispositions stale scheduler candidates
C4  Close canonical receipt/fresh-isolation residuals; freeze finding inventory
C5  One final current-tree code/contract review and prescribed regression
C6  Record CODE_FREEZE_READY only with fresh evidence
R1  Create one fresh non-overwriting project and start the real Dashboard path
R2  Complete visible Playwright path and two fresh scheduler takeovers
R3  Record RUNTIME_READY only with fresh evidence
U1  Make exactly one complete corpus request
U2  Formal preflight; return exact INPUT_BLOCKED/PARSE_BLOCKED or record T0
U3  Continue unattended to DOCX/PDF or the fixed terminal blocker report
```

No session may jump forward to manuscript, benchmark, export, visual polish, or
runtime claims while an earlier gate is open. Long regressions run once after the
intended code tree is stable, not on every repair branch.

## 9. Immediate canonical review protocol

The immutable candidate is a two-commit chain:

```text
BASE=acc550df8727665d94df496a0532ffc9089a6102
COMMIT_1=f754f07065b7cf65dd7fcf75925105933fd23616
COMMIT_2=8a7502eaec7a2e7ea881a5a7de8adeff6d784694
TIP=8a7502eaec7a2e7ea881a5a7de8adeff6d784694
OWNED_PATHS=review_writer/project/dual_parse_bootstrap.py,tests/test_dual_parse_bootstrap.py
REVIEWER=Luna 5.6 max, fresh and read-only
```

The Reviewer evaluates `BASE..TIP` and the two commits' internal ordering. It must
not treat `current integration HEAD..TIP` as a replacement tree: the candidate was
created before scheduler commits, so that comparison would falsely show unrelated
scheduler deletions. The Reviewer may inspect current integration for transplant
compatibility but cannot demand unrelated sibling repairs inside this delta.

The Reviewer returns exactly one of:

- `ACCEPT`: no P0/P1 within the assigned canonical-anchor/transactional-publication
  stop line, with exact checks and zero writes;
- `HOLD`: one or more numbered P0/P1 findings, each with evidence, affected paths,
  acceptance test, and no implementation.

On ACCEPT, a fresh Coordinator integrates `COMMIT_1` then `COMMIT_2` onto the
latest integration HEAD, records resulting hashes, runs focused canonical tests,
and updates the inventory. On HOLD, one new Repair Owner handles one finding from
the latest integration HEAD. No other implementation starts before this result.

## 10. Handoff and evidence rules

`SESSION_HANDOFF.md` is replaced at every Coordinator boundary and committed with
the corresponding inventory/authority state. Git history preserves prior versions.
Required fields are:

```text
SESSION_EPOCH
ROLE
STARTED_FROM_HEAD
CODE_HEAD
HANDOFF_HEAD_POLICY
WORKTREE_CLEAN
GIT_OPERATION_IN_PROGRESS
CONTEXT_COMPACTIONS
AUTHORITY_STATUS
GATE_STATUS
INTEGRATED_COMMITS
PENDING_REVIEW
ACTIVE_FINDING_IDS
CHECKS_TIED_TO_HEAD
SOLE_NEXT_ACTION
FORBIDDEN_NEXT_ACTIONS
REMOTE_WRITE
```

Test evidence names the exact tested HEAD. A new commit makes earlier full-suite
evidence historical until rerun. HTTP reachability or a generic Playwright MCP
process is not project-scoped `RUNTIME_READY` evidence.

## 11. Acceptance criteria for this addendum

1. The Approved Spec bytes and recorded normalized hash remain unchanged.
2. The core manifest verifies all listed files from a clean integration worktree.
3. `FINDING_INVENTORY.json` parses and identifies exactly one immediate review
   action, candidate base, ordered commits, tip, paths, and Reviewer class.
4. `SESSION_HANDOFF.md` identifies code HEAD `24625585...`, all gates as not ready,
   no corpus request, no T0, and the same sole next action.
5. `AGENTS.md` makes first-compaction handoff and second-compaction prohibition
   durable for future repository sessions.
6. No code, test fixture, project data, checkbox, old worktree, remote state, or
   Approved Spec content changes in the addendum commit.
7. The addendum commit is local only; `PUSHED=false` and `DEPLOYED=false`.

## 12. Rollback and forbidden actions

Rollback, if later explicitly authorized, is a new local revert commit limited to
the addendum/control files. Do not use reset, checkout, clean, recursive deletion,
or old-worktree cleanup. This addendum does not authorize push, deploy, issue
filing, external sync, agent impersonation, corpus acquisition, Dashboard claims,
or code implementation during its own persistence session.
