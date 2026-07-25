# Unified Checkpoint Contract

Status: `ACCEPTED_DESIGN_NOT_YET_IMPLEMENTED`

Last updated: 2026-07-19

## Purpose

The existing eight-stage orchestrator remains the execution skeleton. This
contract adds a case-neutral review layer that binds human or automatic review
to exact artifact snapshots. Fifteen logical checkpoints do not mean fifteen
mandatory clicks: each checkpoint chooses an explicit review policy, and the UI
shows only the current or affected task.

## M0/PR A implementation applicability

This file defines target-product semantics. M0/PR A implements only the minimum
fields and pure validations exercised by the two formal acceptance paths in
[PRODUCT_ROADMAP.md](PRODUCT_ROADMAP.md). In particular, atomic evidence
registration, HTTP `409` and three-way diff, optimistic-concurrency servers,
the full dependency ledger, generic invalidation propagation, persistent
projections, event replay, CP00-CP14 orchestration, and checkpoint UI are not M0
implementation requirements.

Every M0 required field must be populated by a fixture, read by production code,
and asserted by an acceptance test. Target-only fields do not enter the M0
required schema. A newly discovered need requires a separate scope-change
decision rather than an implicit Implementation Owner expansion.

## Runtime objects

- **CheckpointContract**: versioned static rules committed with the product.
- **CheckpointSnapshot**: resolved input artifact IDs and hashes for one review.
- **CheckpointEvent**: immutable approval, revision-request, automatic
  validation, invalidation, or not-applicable event.
- **CheckpointProjection**: derived current state produced from selected
  immutable decision records. It is not the audit source of truth or a required
  persistent M0 service.

Related audit objects follow the same separation: a `Revision` is the current
projection while every `RevisionEvent` is immutable and append-only;
`UserIntentEvent` history is also append-only while the active intent set is a
rebuildable projection.

## Orthogonal state machines

Do not reuse evidence terms in revision, artifact, or checkpoint state.

| Domain | States |
| --- | --- |
| Revision lifecycle | `DRAFT`, `PROPOSED`, `VALIDATING`, `VALIDATED`, `ACCEPTED`, `REJECTED`, `SUPERSEDED` |
| Evidence support | `NOT_EVALUATED`, `SUPPORTED`, `PARTIALLY_SUPPORTED`, `UNSUPPORTED`, `CONTRADICTED` |
| Evidence governance | `CANDIDATE`, `UNDER_REVIEW`, `REGISTERED`, `REJECTED`, `WITHDRAWN`, `SUPERSEDED` |
| Artifact build | `NOT_BUILT`, `BUILDING`, `BUILT`, `BUILD_FAILED` |
| Artifact freshness | `CURRENT`, `OUTDATED`, `SUPERSEDED` |
| Artifact validation | `NOT_RUN`, `PASSED`, `WARNING`, `FAILED` |
| Checkpoint approval | `UNOPENED`, `NOT_READY`, `READY`, `AWAITING_HUMAN`, `SATISFIED`, `REVISION_REQUESTED`, `BLOCKED`, `INVALIDATED`, `NOT_APPLICABLE` |

Evidence insufficiency is represented by `Evidence support = UNSUPPORTED`; it
is not a revision state and does not automatically block the project. The
derived blocking issue `EVIDENCE_REQUIRED` exists only while an active
narrative, user revision, checkpoint-required output, or approved downstream
artifact still depends on that unsupported claim.

## User Intent contract

> **Target product semantics — not M0/PR A implementation.** M0 has only
> `initial_user_intent.goal` and `.scope` in editable ProjectManifest. It does
> not implement intent IDs, priority, supersession, withdrawal, event history,
> or an intent projection.

Every intent record carries `intent_id`, `scope`, `priority`, `supersedes`,
`status`, actor, timestamp, and content hash. Status is one of `ACTIVE`,
`WITHDRAWN`, or `SUPERSEDED`. History is never deleted or silently rewritten;
only `ACTIVE` intents participate in generation, artifact dependency hashes,
or checkpoint snapshots.

An intent change is evaluated like any other material dependency change. Scope
changes always invoke the mandatory scope-impact analysis. A superseding or
withdrawn intent remains visible in the UI history but cannot continue steering
new output.

## ProjectManifest and resolved configuration

`ProjectManifest` is editable validated configuration, not an event-sourced
aggregate. The binding M0 schema is
[project_manifest.schema.json](../../schemas/project/project_manifest.schema.json).
Its M0 fields are limited to:

```text
manifest_schema_version
project_id
project_title
initial_user_intent
discovery_policy
output_language
citation_style
paths.seed_source_root
paths.project_data_root
paths.export_root
initial_source_inputs[]
network_policy
adapter_ref            # optional
```

Chemistry domain, literature-review kind, and DOCX final delivery are product
constants rather than fake generic configuration. Relative-path enforcement,
path base resolution against the manifest directory, traversal rejection, and
Windows/POSIX separator normalization are program rules, not user options.
Credentials, provider profiles, and credential values never enter the manifest.

Both `project validate` and `project status` use the same resolved-config
resolver. For goal and scope it converts CRLF and lone CR to LF, applies Unicode
NFC, removes only whole-string leading/trailing Unicode whitespace, preserves
internal text and LF/TAB, and rejects NUL or other control characters. Length
is checked after normalization in Unicode code points: goal 1-4000 and scope
1-8000. The editable source file is never rewritten.

For M0, `discovery_policy` accepts only `CLOSED_CORPUS`. It declares the
scientific corpus boundary and is not a command to execute discovery; no source
outside `initial_source_inputs[]` or the selected read-only adapter may be added
silently. `network_policy` accepts only `OFFLINE_ONLY`. It is a project-level
capability ceiling, not authorization for a call. Future policy values would
still require explicit per-run human authorization.

`adapter_ref`, when present, is a closed product-maintained adapter ID from an
allowlist. Paths, Python import strings, shell commands, URLs, and third-party
plugin entrypoints are invalid. The field cannot become a plugin system.

All three root paths are relative to the directory containing the manifest.
Every `initial_source_inputs[]` path is relative to
`paths.seed_source_root`. Validators reject traversal, absolute POSIX paths,
Windows drive paths, UNC paths, WSL paths, and non-canonical separators at the
contract boundary.

The file may be edited directly. `project_id` becomes immutable once project
records or an immutable RunManifest exist. Each corpus, run, draft, checkpoint,
or release captures the resolved normalized configuration and its SHA-256 in
its own immutable snapshot. Historical results depend on that captured config,
not the current editable file.

`project status` compares the current normalized manifest hash with relevant
immutable snapshots. Equivalent NFC/NFD, line-ending, or outer-whitespace forms
produce the same resolved hash and do not trigger drift. A material goal/scope
difference reports `CONFIG_CHANGED` with the static affected-stage list
`CORPUS`, `CLAIMS`, `CHECKPOINT`, `DRAFT`, `RUN`, and `RELEASE`; it does not
create a manifest adoption event or ProjectProjection.
If real multi-version switching, rollback, or parallel configuration branches
are later demonstrated, they require a separately authorized design.

Provider identity is execution evidence, not project scientific configuration.
If an authorized M1 run uses a model, its immutable RunManifest records only
non-sensitive actual provider/model/profile identifiers and the authorization
fact. It never copies credentials or provider configuration values into the
ProjectManifest.

## SourceRecord and ParseArtifact contract

Search-only entries remain `CandidatePaperRecord` objects. A `SourceRecord`
requires a resolved `document_role` of `MAIN` or `SI`; an unresolved role emits
the blocking issue `DOCUMENT_ROLE_UNRESOLVED` rather than adding an `UNKNOWN`
enum value.

The minimum `SourceRecord` dimensions are independent:

```text
document_role:      MAIN | SI
usage_role:         EVIDENCE | BACKGROUND | DISCOVERY_ONLY
governance_status:  CANDIDATE | INCLUDED | EXCLUDED
availability_status: METADATA_ONLY | FULL_TEXT_AVAILABLE | PARSED
integrity_status:   UNVERIFIED | VALIDATED | QUARANTINED
```

The record also binds `source_version`, `content_sha256`,
`active_parse_artifact_id`, `status_reason_code`, `validation_report_ref`, and
`supersedes_source_version`. Every governance or integrity decision produces a
reason-coded event. Enum values alone are not audit evidence.

`UNVERIFIED` means the checks required for the current availability level have
not completed. `VALIDATED` requires source identity and hash binding plus parse
QA when an active parse exists. `QUARANTINED` identifies a known wrong binding,
wrong document, damaged source, or untrusted source version and disables all
downstream use; it says nothing about scientific claim correctness.

`SourceRecord` and `ParseArtifact` are separate artifacts. Source availability
describes the highest available level for the current hash-pinned source
version. Parser failure is represented by `ParseArtifact` build/validation
state and a blocking issue, not by a `PARSE_FAILED` source state. A bad derived
parse is quarantined at the artifact level when the source document remains
correct: its artifact validation is `FAILED`, a reason-coded
`PARSE_ARTIFACT_QUARANTINED` blocking issue/event is retained, and it cannot be
selected as `active_parse_artifact_id`. A wrong document version parsed under
the wrong identity may itself be `PARSED` and `QUARANTINED`.

The generic product contract uses `document_role`. Frozen Phase 8 schemas keep
their legacy `source_role=MAIN|SI`; the Case 01 adapter maps that field without
modifying frozen schemas or artifacts.

The M0 derived eligibility predicates are:

```text
Evidence Discovery RAG:
  governance_status = INCLUDED
  usage_role in [EVIDENCE, BACKGROUND]
  availability_status = PARSED
  integrity_status = VALIDATED

Approved scientific claim:
  governance_status = INCLUDED
  usage_role = EVIDENCE
  availability_status = PARSED
  integrity_status = VALIDATED
  precise locator and source content hash are present
```

`EXCLUDED` or `QUARANTINED` blocks both RAG paths, candidate claims, the
Approved Claim Registry, and prose. `DISCOVERY_ONLY` is restricted to candidate
discovery. `BACKGROUND` must be promoted to `EVIDENCE` and rechecked before it
supports a concrete claim. No additional generic source state machine or
automatic migration engine belongs in M0/PR A.

## Approved Claim Registry authority

The registry is implemented as three separate objects:

- **ClaimVersionRecord**: immutable claim content and lineage;
- **ClaimDecisionEvent**: immutable evidence-support and governance decisions;
- **ApprovedClaimRegistryProjection**: rebuildable current state and writing
  eligibility.

`evidence_support_status` and `governance_status` are projection fields obtained
by replaying decision events. They are never directly editable authority fields
inside `ClaimVersionRecord`.

For M0, “projection” means a pure deterministic view over explicit immutable
fixture/snapshot inputs. It is not a persistent service or generic replay
engine.

The minimum immutable claim version binds:

```text
project_id
claim_id
claim_version
claim_version_id
claim_text
claim_text_sha256
epistemic_class
evidence_refs[]
supporting_claim_refs[]
conflict_refs[]
derived_from_claim_version
supersedes_claim_version
created_by_event_id
```

`claim_id` identifies one stable logical lineage. `claim_version_id` uniquely
identifies a concrete immutable version. `derived_from_claim_version` and
`supersedes_claim_version` reference complete version IDs, never ambiguous
integers.

The minimum epistemic classes are:

```text
SOURCE_OBSERVATION
AUTHOR_INTERPRETATION
PROPOSED_MECHANISM
REVIEWER_SYNTHESIS
```

Each `evidence_refs[]` entry binds source ID and version, parse artifact ID,
source content SHA-256, precise locator, and excerpt SHA-256. Every reference
must continue to satisfy the SourceRecord approved-claim eligibility predicate.
Raw retrieval chunks are not authoritative evidence references.

`REVIEWER_SYNTHESIS` uses `supporting_claim_refs[]`. In M0 it may reference only
current `REGISTERED + SUPPORTED` non-synthesis claims, and the dependency graph
must be acyclic. Cross-study synthesis binds at least two material claims; a
cross-source comparison also requires at least two source records.

### Target lifecycle: decision replay and registration

The atomic workflow below is target-product semantics, not an M0 mutation
service. M0 only validates from explicit decision inputs that ordinary
checkpoint approval cannot produce a registered scientific fact.

Claim support projects to `NOT_EVALUATED`, `SUPPORTED`,
`PARTIALLY_SUPPORTED`, `UNSUPPORTED`, or `CONTRADICTED`. Claim governance
projects to `CANDIDATE`, `UNDER_REVIEW`, `REGISTERED`, `REJECTED`, `WITHDRAWN`,
or `SUPERSEDED`.

A newly proposed version starts as `NOT_EVALUATED + CANDIDATE`. The old current
`REGISTERED + SUPPORTED` version remains current while the proposal is checked.
Only a successful evidence-registration operation atomically registers the new
version and supersedes the old version. Failure, rejection, or withdrawal of
the proposal cannot displace the old registered version. One claim lineage has
at most one current registered version.

The evidence-registration operation binds base registry hash, claim version
ID, evidence decision, reason, actor, timestamp, validator-report references,
and an atomic transition set. Ordinary checkpoint `APPROVE` cannot produce
these transitions.

A `PARTIALLY_SUPPORTED` version cannot be registered. It may be narrowed into
a new version, split into new lineages, or have unsupported content removed and
then be re-evaluated. Every changed version restarts at
`NOT_EVALUATED + CANDIDATE`.

An ordinary unused `UNSUPPORTED` candidate may be rejected, withdrawn, or
retained as unused without blocking. It produces `EVIDENCE_REQUIRED` only when
an active intent or current downstream dependency still requires it.

A `CONTRADICTED` statement cannot be registered as settled fact. Supported
attributed positions may be registered separately. An attributed controversy
is a `REVIEWER_SYNTHESIS` version that references the current registered
position claims and the corresponding `ConflictRecord`, and follows that
record's non-definitive manuscript treatment.

### Writing eligibility and target invalidation semantics

M0 implements the writing-eligibility predicate as a pure function and reports
only directly affected stages/artifacts required by its fixtures. The general
dependency propagation described below is deferred.

Writing eligibility is deterministically derived from all of the following:

```text
the claim version is current
evidence_support_status = SUPPORTED
governance_status = REGISTERED
all source and parse evidence refs remain eligible and current
all supporting claim refs remain current and writing-eligible
all referenced ConflictRecords permit the requested manuscript treatment
the claim remains inside active project scope
```

Withdrawal, supersession, or evidence/source hash invalidation propagates over
explicit dependency edges to affected paragraphs, tables, citations,
checkpoint snapshots, and DOCX artifacts as `OUTDATED` or `INVALIDATED`.

The Case 01 adapter maps legacy epistemic classes without modifying frozen
schemas:

```text
DIRECT_REPORTED_RESULT
EXPERIMENTAL_MECHANISTIC_OBSERVATION
INTERMEDIATE_ISOLATION
  -> SOURCE_OBSERVATION

AUTHOR_PROPOSED_MECHANISM
  -> PROPOSED_MECHANISM

REVIEW_ARTICLE_SUMMARY
  -> AUTHOR_INTERPRETATION
```

Historical `AI_INFERENCE` never auto-registers. It may become a candidate
synthesis requiring review or be excluded. M0/PR A implements the three object
schemas, lineage and state-combination validation, current-version and writing
eligibility filters, Case 01 mapping, deterministic per-snapshot registry
assembly, hash closure, and direct invalidation-report tests. It does not
implement AI claim verification, full writing, a second vector index, a generic
claim ontology, or a project-wide replay service.

## Static contract shape

This is the target contract shape. M0 schemas include only fields exercised and
asserted by the two formal PR A acceptance paths.

```json
{
  "schema_version": "checkpoint-contract-1.0",
  "contract_id": "cp05-evidence-selection",
  "contract_version": "1.0.0",
  "checkpoint_id": "CP05",
  "stage_bindings": ["matrix", "evidence_verification"],
  "policy": "HUMAN_REQUIRED",
  "applicability": {},
  "input_artifacts": [],
  "output_artifacts": [],
  "entry_rules": [],
  "check_rules": [],
  "blocking_issue_rules": [],
  "allowed_operations": [],
  "approval_event_contract": {},
  "invalidation_edges": [],
  "recovery_actions": [],
  "ui_summary": {},
  "chemical_validation_profiles": []
}
```

## Input artifact reference

Every input is a logical artifact reference, not only a path:

```json
{
  "artifact_id": "approved-source-inventory",
  "artifact_type": "source_inventory",
  "required": true,
  "selection": {
    "project_id": "${project_id}",
    "corpus_version": "${active_corpus_version}"
  },
  "snapshot_fields": [
    "content_sha256",
    "dependency_set_sha256",
    "revision_id",
    "schema_version"
  ],
  "required_states": {
    "build": "BUILT",
    "freshness": "CURRENT",
    "validation": ["PASSED", "WARNING"]
  }
}
```

The snapshot hash is computed from the canonical contract ID/version, resolved
artifact IDs and hashes, dependency hashes, validation-rule versions, active
User Intent IDs, and relevant ConflictRecord IDs.

## Review policies

- `HUMAN_REQUIRED`: a current human approval event is mandatory.
- `HUMAN_ON_EXCEPTION`: deterministic checks may satisfy the checkpoint when
  no exception exists; an exception opens the UI.
- `AUTOMATIC_VALIDATION`: no human action is requested unless the contract is
  changed to another policy.
- `NOT_APPLICABLE`: only a contract predicate can select this state; the event
  stores the predicate result and reason.

An automatic pass produces `AUTO_SATISFIED`, not a human `APPROVE` event.

## Blocking issues

Blocking issues are independent runtime records:

```json
{
  "issue_id": "issue-uuid",
  "issue_code": "EVIDENCE_REQUIRED",
  "severity": "BLOCKING",
  "artifact_id": "candidate-claim-42",
  "source_check_id": "claims-have-source-locators",
  "message_key": "checkpoint.evidence.missing_locator",
  "details": {},
  "permitted_recovery_actions": [
    "request_evidence",
    "narrow_claim",
    "reject_claim"
  ]
}
```

An issue blocks satisfaction but does not mutate Revision lifecycle or Evidence
support by itself.

## Allowed operations and concurrency

> **Target product semantics — not M0/PR A implementation.** M0 has no mutation
> service, HTTP API, optimistic-concurrency server, or three-way-diff workflow.

Every user mutation supplies:

```text
base_checkpoint_snapshot_hash
base_artifact_hash
base_revision_id
proposed_revision
```

The server uses optimistic concurrency. A base/current mismatch returns HTTP
`409`, writes no revision, and supplies a base/current/proposed three-way diff.
No last-write-wins behavior is allowed.

Each successful edit creates an immutable RevisionEvent containing base
revision, before/after content, span-level multi-label classification, diff,
actor, timestamp, active intent IDs, expected impact, and actual invalidation.
User edits cannot be silently deleted.

## Approval event

An approval event binds:

- event and checkpoint IDs;
- contract version;
- checkpoint snapshot hash;
- every input artifact hash;
- decision and checklist results;
- unresolved non-blocking issues;
- user comment and display name;
- timestamp.

Ordinary checkpoint approval cannot change the Approved Claim Registry. Claim
registration uses its own verified operation under the evidence checkpoint.

Old approval events remain immutable. A changed snapshot creates an
`INVALIDATED` projection for the old approval and requires a new event when the
policy calls for human review.

## Invalidation edges

> **Target product semantics — not a general M0 propagation engine.** M0 reports
> only a static, directly affected stage/artifact list for its configuration and
> eligibility fixtures.

Each edge declares source selector, target selector, materiality rule, effect,
reason code, propagation mode, and required global checks.

Effects include:

- `MARK_ARTIFACT_OUTDATED`;
- `INVALIDATE_CHECKPOINT_SNAPSHOT`;
- `REBUILD_DEPENDENCY_ONLY`;
- `MANDATORY_IMPACT_ANALYSIS`.

Scope changes always trigger impact analysis for corpus, outline, abstract,
conclusion, and DOCX. Only material dependency changes mark artifacts
`OUTDATED`. Local rebuilds are followed by global claim, citation,
cross-reference, figure-caption, and DOCX consistency validation.

The dependency ledger stores the whole-manuscript content hash plus paragraph,
claim, figure, table, citation, and cross-reference dependency hashes. Every
`OUTDATED` transition records the changed dependency and a concrete reason
code. The UI shows predicted impact before a revision is saved and actual
invalidation after the event is committed.

CP05-CP06 and CP07-CP09 have explicit backward and forward edges; they are not
implemented as a strict waterfall.

## Conflict authority

Known parse, OCR, locator, entity-binding, or wrong-document failures are
`ArtifactValidationIssue` records, not scientific conflicts. The conflict
authority uses three objects:

- **ConflictRecord**: immutable conflict identity and versioned position refs;
- **ConflictDecisionEvent**: immutable classification, comparability,
  resolution, dismissal, and manuscript-treatment decisions;
- **ConflictProjection**: rebuildable current classification, status,
  treatment, and manuscript eligibility.

The immutable record version binds:

```text
conflict_id
conflict_version
conflict_version_id
project_id
position_claim_version_ids[]
detected_by_event_id
derived_from_conflict_version
content_sha256
```

`conflict_id` identifies a stable lineage. Positions are immutable within one
version and contain only `claim_version_id` references, never copied claim
text. Adding, removing, or replacing a position creates a new conflict version.

Classification is a projected event decision, not a mutable ConflictRecord
field:

```text
SOURCE_INTERNAL_CONFLICT
CROSS_SOURCE_DISAGREEMENT
ACADEMIC_CONTROVERSY
```

A potential conflict may be recorded before its positions complete review, but
it has no manuscript eligibility. Attributed positions must all be current
`REGISTERED + SUPPORTED` claim versions.

### Comparability and classification

Source-internal differences do not become conflicts merely because MAIN and SI
contain different numbers. Classification checks entity/substrate, reaction
stage, conditions, metric/unit, table/entry identity, applicable scope, and
amendment/correction relationships. Differences explained by those dimensions
are non-comparable relationships or validation findings, not invented
scientific conflict.

Escalation from cross-source disagreement to academic controversy requires a
structured assessment:

```text
comparability_status:
  COMPARABLE | PARTIALLY_COMPARABLE | NONCOMPARABLE

dimensions_checked:
  conditions
  substrate/entity
  reaction_stage
  metric/unit
  applicable_scope
  epistemic_strength
```

Only at least two material, current `REGISTERED + SUPPORTED` positions that are
`COMPARABLE` and remain substantively incompatible may be classified as
`ACADEMIC_CONTROVERSY`. Non-comparable potential conflicts resolve as excluded
relationships with an auditable basis; they do not become controversy.

An issue known from the outset to be an artifact error does not create a
ConflictRecord. `DISMISSED_AS_ARTIFACT` is reserved for a plausible scientific
conflict later shown by investigation to be an artifact error; the dismissal
event links the exact `ArtifactValidationIssue` and retains the investigation
history.

### Status and treatment matrix

Conflict status projects to `OPEN`, `RESOLVED`, `ACCEPTED_UNRESOLVED`, or
`DISMISSED_AS_ARTIFACT`. Manuscript treatment projects to `BLOCKED`, `EXCLUDED`,
`ATTRIBUTED_POSITIONS`, `UNRESOLVED_CONTROVERSY`, or `RESOLVED_SYNTHESIS`.

The deterministic compatibility matrix is:

| Classification/status | Allowed manuscript treatment |
| --- | --- |
| `DISMISSED_AS_ARTIFACT` | `EXCLUDED` only |
| `SOURCE_INTERNAL_CONFLICT` | `BLOCKED`, `EXCLUDED`, `ATTRIBUTED_POSITIONS` |
| `CROSS_SOURCE_DISAGREEMENT` | `BLOCKED`, `EXCLUDED`, `ATTRIBUTED_POSITIONS` |
| `ACADEMIC_CONTROVERSY + ACCEPTED_UNRESOLVED` | `UNRESOLVED_CONTROVERSY`, `ATTRIBUTED_POSITIONS` |
| `RESOLVED` | `EXCLUDED`, `RESOLVED_SYNTHESIS` |

`SOURCE_INTERNAL_CONFLICT` and un-escalated `CROSS_SOURCE_DISAGREEMENT` cannot
use `UNRESOLVED_CONTROVERSY`. `BLOCKED` affects only dependent claims,
paragraphs, tables, or release candidates; unrelated work may continue.

ConflictRecord never generates prose. `RESOLVED_SYNTHESIS` requires an
independently evidence-registered `resolution_claim_version_id` whose
epistemic class is `REVIEWER_SYNTHESIS`, support is `SUPPORTED`, and governance
is `REGISTERED`. That claim binds all material positions, resolution basis, and
appropriate attribution. Resolution by choosing one position records the
accepted position version, rejected or scoped position refs, resolution basis,
and validator refs.

### Decision event and invalidation

Each `ConflictDecisionEvent` binds event ID, conflict lineage/version IDs, base
conflict snapshot hash, classification, comparability assessment, decision,
manuscript treatment, optional linked artifact issue, optional resolution claim
version, reason, actor, timestamp, and validator refs. Ordinary checkpoint
approval cannot classify, resolve, dismiss, or change conflict treatment.

Withdrawal, supersession, evidence ineligibility, or scope removal of a
position automatically removes current manuscript eligibility and marks
dependent controversy claims, paragraphs, checkpoint snapshots, and DOCX
artifacts `OUTDATED` or `INVALIDATED`.

The Case 01 adapter retains all seven frozen legacy source conflicts with their
provenance and maps them by default to `SOURCE_INTERNAL_CONFLICT + EXCLUDED`.
It never upgrades them to academic controversy. Turning legacy alternatives
into positions requires separate ClaimVersionRecords; legacy conflict JSON is
not silently treated as registered fact.

M0/PR A implements conflict versions, decision records, a derived-view schema,
the classification/treatment matrix, position eligibility, Case 01 mapping,
deterministic per-snapshot assembly, hash closure, artifact-dismissal linkage,
and direct dependency-impact tests. It does not implement automatic conflict
discovery, comparability judgment, adjudication, academic-language generation,
or a project-wide replay service.

## Recovery action

Each recovery action names triggering issue codes, required inputs, expected
outputs, return checkpoint, and whether a retry is automatic. Scientific or
provider work is never retried merely because a prior attempt failed; the
contract must explicitly authorize the next attempt.

## UI summary

> **Target product semantics — checkpoint UI is deferred from M0/PR A.**

The contract provides locale-neutral UI semantics:

- title, purpose, and why-now translation keys;
- current snapshot and diff;
- checklist and validation results;
- blocking and unresolved issues;
- allowed operations;
- expected and actual invalidation scope;
- recovery choices.

The interface supports `zh-CN` and `en`, but visual style and exact checkpoint
timing remain a later UX review decision.

## Chemical validation profiles

- **CP05 evidence**: compound identity, reaction stage, conditions,
  stoichiometry, yield/ee, MAIN/SI locator, and evidence-strength wording.
- **CP10 figures/tables**: atom connectivity, bond order, charge,
  stereochemistry, compound labels, reaction arrows, captions, and source
  provenance.
- **CP12 manuscript**: nomenclature, numeric consistency, mechanism-language
  strength, positive/negative scope balance, citations, conflicts, figures,
  and tables.

## Logical checkpoint sequence

The sequence is the stable target-product map. M0 does not instantiate or
orchestrate CP00-CP14; it validates only the minimum hash-bound checkpoint
snapshot and approval separation required by PR A acceptance.

The contract preserves the accepted CP00-CP14 sequence:

```text
CP00 Goal and Scope
CP01 Search Strategy
CP02 Candidate Papers
CP03 Inclusion/Exclusion and Corpus Version
CP04 Source Identity, Parse QA, and Discovery Index
CP05 Evidence Selection and Approved Claim Registry
CP06 Literature Matrix and Coverage
CP07 Scientific Narrative and Outline
CP08 Section Blueprint and Figure Plan
CP09 Rolling Section/Paragraph Review
CP10 Figure and Table Review
CP11 Integrated Draft Review
CP12 Scientific Audit
CP13 DOCX Visual Review
CP14 Final Handoff and Release Record
```

The existing orchestrator mapping remains:

```text
Discovery   -> CP01-CP03
Matrix      -> CP04-CP07
Blueprint   -> CP08
Sections    -> CP09
Figures     -> CP10
Draft       -> CP11
Final Audit -> CP12
Export      -> CP13-CP14
```

CP09 is rolling. Checkpoints with `HUMAN_ON_EXCEPTION` or
`AUTOMATIC_VALIDATION` do not require a routine click.

## M0 lightweight persistence boundary

M0/PR A preserves the records that protect scientific and human work without
building a general event-sourcing platform:

- hash-pinned SourceRecord versions and separate ParseArtifacts;
- immutable ClaimVersionRecords and append-only human ClaimDecisionEvents;
- immutable ConflictRecord versions and append-only ConflictDecisionEvents;
- immutable RunManifest, corpus/draft/checkpoint snapshots, and ReleaseRecords;
- closed hash manifests for immutable snapshots, exports, and releases.

The current ProjectManifest remains editable. Every immutable downstream
snapshot embeds or references the normalized resolved configuration and its
SHA-256. A later manifest edit cannot rewrite historical results; project status
reports `CONFIG_CHANGED` and the directly affected stages.

For M0, registry and conflict views are deterministic pure builds from the
explicit immutable inputs selected for one snapshot. They are not cached
project-wide projections backed by a generic journal. Decision files use unique
IDs and fail if the target path already exists; no last-write-wins overwrite is
allowed.

Deferred durability work includes a project journal, event envelope and hash
chain, operation idempotency, OS-level locks, fsync protocol, crash-tail
recovery, generic replay/projection infrastructure, configuration adoption and
rollback, and multi-writer concurrency. Those capabilities require observed
product need and a separately approved work package.

## Storage boundary

The accepted target is:

- versioned static contracts in Git;
- editable ProjectManifest plus immutable resolved RunManifest and artifact
  snapshots in ignored project data;
- immutable source, claim, conflict, human-decision, checkpoint, and release
  records with overwrite refusal;
- deterministic per-snapshot registry/conflict views, with no database or
  generic project projection required for the first product slice;
- closed hash manifests only inside immutable snapshots, exports, and releases.
