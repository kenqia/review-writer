# Review-Writer Next Phase Execution Authority

Status: `PRE_T0_PENDING_INPUT`
Authority anchor: the local docs-only commit containing this record and the approved Spec copy.

## Frozen Spec and revision facts

```text
SPEC_ID=review-writer-next-phase-2026-08-01
SPEC_STATUS=APPROVED
SPEC_SOURCE_PATH=docs/superpowers/specs/2026-08-01-review-writer-next-phase-unique-requirements.md
SPEC_SOURCE_SHA256=1836fa445bca134788bad3946a1ea030cb3c860c5bdc699ef39ff2609fc346fa
SPEC_RECORDED_PATH=docs/superpowers/specs/2026-08-01-review-writer-next-phase-unique-requirements.md
SPEC_NORMALIZED_SHA256=105205dd8f5b65dadda3d4ea4d964f510cde104907bab59d56510eddd847da7c
SPEC_NORMALIZATION=trailing-space-removal-and-single-final-LF-only
BASE_WORKTREE=/home/kenqia/my_folder/review-writer/.worktrees/e2r-mvp-integration
BASE_BRANCH=codex/e2r-mvp-integration
BASE_HEAD=2536db45c85ffb7c52248e349df9b645b8407a61
BASE_PARENT=6914bd068ec951ceeda69fe46af36ba7752ce307
INTEGRATION_WORKTREE=/home/kenqia/my_folder/review-writer/.worktrees/review-writer-next-phase-integration
INTEGRATION_BRANCH=codex/review-writer-next-phase-integration
INTEGRATION_BASE_HEAD=2536db45c85ffb7c52248e349df9b645b8407a61
AUTHORITATIVE_PROJECT_ID=PRE_T0_PENDING_INPUT
AUTHORITATIVE_PROJECT_ROOT=PRE_T0_PENDING_INPUT
INPUT_BUNDLE_ROOT=PRE_T0_PENDING_INPUT
CORPUS_STUDY_COUNT=PRE_T0_PENDING_INPUT
CORE_STUDY_IDS=PRE_T0_PENDING_INPUT
STANDARD_CORPUS_MANIFEST_SHA256=PRE_T0_PENDING_INPUT
FROZEN_CODE_HEAD=PRE_CODE_FREEZE
```

The recorded Spec was produced by the exact mechanical transformation named above. A
byte comparison against that transformation passed before this record was written.
No project input, corpus count, core-study selection, or manifest hash is invented
before the one-time user input request.

## Gate state

```text
INPUT_READY=NOT_READY
CODE_FREEZE_READY=NOT_READY
RUNTIME_READY=NOT_READY
T0=NOT_RECORDED
USER_INPUT_REQUESTED=false
USER_ACTIONS_AFTER_T0=0
```

The input request is not permitted until both `CODE_FREEZE_READY=OK` and
`RUNTIME_READY=OK` have fresh evidence. After that point exactly one complete corpus
request is allowed, followed by formal preflight and either T0 or a fixed blocker.

## Owner and Reviewer contract

```text
OWNER_1=Input & Provenance Owner
OWNER_1_BOUNDARY=variable-N manifest, input lifecycle, source binding/hash/currentness, fresh isolation, zero-write failure
OWNER_1_FORBIDDEN=downstream scientific content

OWNER_2=Scientific State & Evidence Owner
OWNER_2_BOUNDARY=Honest Progressive states, gap registry, claim dependency rule, Paper Evidence contract
OWNER_2_FORBIDDEN=Dashboard, scheduler, export

OWNER_3=Orchestration & Dashboard Owner
OWNER_3_BOUNDARY=single entry, visible Dashboard/Playwright path, resumable state, takeover, concurrency/retry/budget
OWNER_3_FORBIDDEN=scientific decisions, manuscript writing

OWNER_4=Synthesis, Manuscript & Export Owner
OWNER_4_BOUNDARY=5-question synthesis, single-writer manuscript, ACS citations, comparison table, benchmark, DOCX/PDF, artifact audit
OWNER_4_FORBIDDEN=input contract changes

OWNER_5=Integration Coordinator
OWNER_5_BOUNDARY=integrate four independently reviewed minimal commits, unified regression, freeze code, start one authoritative run
OWNER_5_FORBIDDEN=new feature development, self-approval

INDEPENDENT_REVIEWER=REQUIRED_SEPARATE_AGENT_SESSION
INDEPENDENT_REVIEWER_MODEL=Sol 5.6 max
INDEPENDENT_REVIEWER_WRITE_PERMISSION=NONE
REPAIR_OWNER_POLICY=only a new owner for one P0/P1 finding, with disjoint scope
```

Each Owner must report its own bounded diff and fresh verification. The Reviewer is
read-only and cannot approve its own work. The Coordinator integrates only after the
Reviewer result is available.

## Baseline evidence and immutable safety flags

```text
BASELINE_MAKE_SMOKE=PASS
BASELINE_MAKE_QUALITY_CHECK=PASS
BASELINE_SPEC_CMP=PASS
OLD_WORKTREES_MODIFIED=false
MAIN_MODIFIED=false
REMOTE_WRITE=false
PUSHED=false
DEPLOYED=false
PLAN_CHECKBOX_CHANGED=false
SENSITIVE_DATA_EXPOSED=false
```

Authority order is: approved Spec -> this execution authority record -> frozen code
revision -> authoritative project state. Historical handoffs, old dual-parse plans,
old checkpoints, old checkboxes, and old project state cannot widen this authority.
