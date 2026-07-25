# Product Roadmap

Status: `CURRENT_PRODUCT_ROADMAP`

Last updated: 2026-07-19

This roadmap supersedes the sequencing recommendations in the historical
competition roadmap. It preserves the same core lesson: stabilize the public
contract before attempting broad product or UI work.

## M0 - Product and Checkpoint Contract

Goal: define one public project boundary before a new scientific run.

The only minimum implementation package for M0 is the local work-package alias
`PR A`, with stable ID `M0-PR-A`. This label does not assert a remote pull
request. Until explicitly changed, run records use:

```text
work_package_id = M0-PR-A
remote_pr_created = false
remote_pr_url = null
```

Contract and schema lock reaches `M0_CONTRACT_LOCKED`. M0 completes only at
`M0_IMPLEMENTED_AND_ACCEPTED`, after the whole work package passes its offline
acceptance evidence and human checkpoint. The package may contain multiple
commits and review/repair rounds under one Implementation Owner; it cannot be
split into independently bypassable acceptance packages.

### M0/PR A acceptance question

This work package answers exactly one question:

> Can the same minimum, case-neutral, local project contract validate both a
> synthetic non-allene project and frozen Case 01, while protecting existing
> evidence, human decisions, and historical outputs from editable configuration
> drift, so the project can safely prepare M1?

The retained list is the maximum allowed boundary, not an instruction to build
one module, service, repository, or state machine per noun. A required field or
production-code branch must be read by the two acceptance paths and asserted by
at least one acceptance test. Otherwise it is removed or deferred.

The M0 ProjectManifest field set is frozen to schema version, project ID/title,
initial goal/scope, discovery policy, output language, citation style, three
relative roots, initial source inputs, network policy, and optional closed
`adapter_ref`. `provider_profile_ref` and manifest/contract version-management
fields are excluded. M0 accepts only `CLOSED_CORPUS` and `OFFLINE_ONLY`.
Provider/model execution evidence, if separately authorized in M1, belongs to
the immutable RunManifest rather than project configuration.

Deliver:

- editable, case-neutral ProjectManifest validation and standard artifact/output
  layout;
- immutable resolved configuration in RunManifest, corpus/draft/checkpoint
  snapshots, and ReleaseRecord closures;
- ArtifactRef, orthogonal SourceRecord fields, separate ParseArtifact,
  CorpusVersion, and source eligibility validation;
- immutable ClaimVersionRecord and human ClaimDecisionEvent inputs plus a
  deterministic current/writing-eligibility registry view;
- minimum ConflictRecord/decision validation that prevents artifact errors or
  non-comparable results from becoming academic controversy;
- the minimum logical CheckpointContract/Snapshot/Event fields needed to bind a
  decision to one artifact hash;
- Case 01 frozen-artifact adapter and one synthetic non-allene manifest;
- case-neutral `project validate` and `project status`, including
  `CONFIG_CHANGED` and affected-stage reporting;
- offline schema, portability, hardcoding, path-safety, config-snapshot, and
  immutable snapshot/release hash-closure tests.

Deferred after M0/PR A unless real usage demonstrates the need:

- ProjectManifest versions, adoption events, rollback, or ProjectProjection;
- a project-wide event journal, canonical event envelope, OS locking, fsync
  protocol, crash recovery, idempotent operations, or generic replay engine;
- a general dependency/invalidation engine beyond reporting the directly
  affected stages and artifacts required by the minimum slice;
- all fifteen checkpoint implementations or UIs and any dashboard rewrite;
- a mandatory Approved Claim RAG/index;
- AI claim verification, full writing, or a generic claim ontology;
- automatic conflict discovery, comparability judgment, adjudication, or
  academic-language generation;
- new providers;
- a full new review;
- a universal scientific ontology;
- a database, accounts, deployment, concurrent writers, distributed
  transactions, or online migration.

### Allowed implementation form

Retained objects may be implemented only as:

- JSON Schema or equivalent structural validation;
- pure functions over explicit inputs;
- a deterministic derived view for one explicit snapshot;
- immutable-output creation with overwrite refusal;
- fixtures, the read-only Case 01 adapter, and offline tests.

M0/PR A explicitly excludes claim/conflict/checkpoint mutation services,
persistent projections, event replay or lifecycle engines, atomic registration
workflows, HTTP `409`/three-way-diff/optimistic-concurrency servers, dependency
ledgers, generic invalidation propagation, CP00-CP14 orchestration or UI,
network/model calls, writing generation, and provider changes. Descriptions of
those behaviors in the target Checkpoint Contract do not expand this work
package.

### Formal acceptance paths

**Synthetic non-allene**

- validates through the generic editable ProjectManifest;
- `project validate` passes;
- `project status` deterministically summarizes project, corpus, claims,
  checkpoint, run, and release closure;
- production code contains no Case 01 IDs/counts, allene taxonomy, or fixed run
  ID.

The synthetic path also changes the editable manifest and verifies
`CONFIG_CHANGED` with a static list of directly affected stages. It does not
perform DAG propagation. Existing RunManifest, snapshots, scientific decisions,
releases, and their hashes remain unchanged.

For goal/scope changes the static list is `CORPUS`, `CLAIMS`, `CHECKPOINT`,
`DRAFT`, `RUN`, and `RELEASE`. Equivalent NFC/NFD text, CRLF/CR/LF line endings,
or whole-string outer whitespace must resolve to the same config hash and must
not report `CONFIG_CHANGED`.

**Frozen Case 01 adapter**

- resolves frozen artifacts read-only without changing source files or hashes;
- accepts correct source/parse bindings and rejects quarantined or excluded
  evidence from writing eligibility;
- deterministically interprets the minimum legacy claim, conflict, checkpoint,
  run, and release fields;
- introduces no Case 01-only public field.

### Minimum scientific and integrity assertions

- one eligible claim is writing-eligible;
- one claim bound to quarantined or excluded evidence is not writing-eligible;
- ordinary checkpoint approval cannot register a scientific fact;
- incompatible conflict classification/status/treatment is rejected;
- tampering with an immutable snapshot or release breaks hash-closure
  verification.

Only these two paths constitute formal PR A acceptance. New needs discovered by
them require an explicit scope-change decision; they cannot enter the work
package implicitly.

Exit evidence:

- a synthetic non-allene manifest validates without production-code edits;
- generic entrypoints contain no required F3I/F47A/P403 IDs, 44/37/7 counts,
  allene taxonomy, or fixed run ID;
- Case 01 frozen artifacts resolve through an adapter without mutation;
- modifying editable configuration produces `CONFIG_CHANGED` while prior
  RunManifest, snapshots, releases, scientific decisions, and their hashes stay
  unchanged;
- the retained minimum slice passes one unified human acceptance checkpoint.

## M1 - Case 01 v5 Golden Calibration and Minimal UI Slice

Goal: prove that the intended product contract produces a chemically stronger,
user-aligned DOCX through the real QoderWork path.

Deliver:

- preserve Case 01 v4 unchanged;
- create a new v5 project through the generic contract;
- bind the correct P403 ACS Catalysis main/SI source hashes and refuse the
  quarantined wrong JACS extraction;
- perform only the targeted source parsing and evidence repair needed for the
  approved two-study perspective;
- add the accepted three original redraws and compact comparison table;
- provide a minimal bilingual localhost checkpoint UI using the existing
  Python/HTML/CSS/JS dashboard stack;
- run one Windows-native QoderWork CN flow with `qwen3.7-max` after evidence,
  outline, and figure-plan approval;
- produce one `SELF_REVIEWED_DRAFT` DOCX and a closed internal evidence package.

This is a calibration run, not proof of generality or publication readiness.
M0 acceptance authorizes preparation of an M1 work package only. M1 execution
requires a separate human approval, scope, Implementation Owner, and acceptance
criteria. It must not rerun or rewrite frozen Phase 8, add Case 01-only
validators or providers, expand scientific claims beyond the approved v5
scope, or build the complete checkpoint UI/workflow engine.

## M2 - New 20-40 Paper Chemistry Review

Goal: run the first large, valuable review without expanding Case 01 or adding
case-specific production code.

Inputs:

- a user-selected chemistry topic;
- main papers and SI supplied as a seed corpus;
- project-selected `CLOSED_CORPUS`, `MODEL_ASSISTED`, `SCHOLARLY_SEARCH`, or
  `HYBRID` discovery mode.

Requirements:

- execute through QoderWork CN in a Windows-native clone;
- use source identity, corpus versioning, Evidence Discovery RAG, the Approved
  Claim Registry, approved claims, conflict records, rolling paragraph review,
  figure review, and DOCX visual review; add a derived Approved Claim index only
  if claim scale and measured retrieval needs justify it;
- apply risk-tiered human attention so a large claim set does not require a
  routine click for every low-risk item;
- produce comparable Direct LLM, ordinary RAG, and full-system metrics only
  when a bounded evaluation is explicitly authorized.

Exit evidence:

- no production code contains new topic-specific IDs or rules;
- the final expert-facing artifact is one traceable DOCX;
- every material claim resolves to the Approved Claim Registry;
- user edits survive regeneration and affected artifacts rebuild locally;
- release status honestly distinguishes self review from external expert review.

## M3 - Product Hardening

Goal: make the validated workflow easy to install, understand, and repeat.

Deliver:

- one simple README quick start and one QoderWork prompt;
- stable localhost checkpoint navigation and bilingual terminology;
- recovery guidance for missing full text, parse errors, provider failure,
  outdated approvals, and DOCX visual defects;
- product metrics and reproducible demo/eval harnesses;
- Windows-native portability and offline CI evidence.

Still out of scope:

- SaaS deployment, accounts, payments, multi-tenancy;
- a large frontend framework migration;
- fully autonomous scientific acceptance;
- broad cross-domain expansion.

## Ordering rule

M0 is first. After `M0_IMPLEMENTED_AND_ACCEPTED`, do not continue horizontal
infrastructure work. Prepare M1 immediately as the next separately approved work
package. M0 acceptance does not itself authorize network/model execution.

Once the user separately approves M1 provider, transmitted content, request
budget, scope, Owner, and acceptance criteria, its first runtime gate is:

```text
hash-bound evidence
-> human-approved claims
-> one real model API section draft
-> citation/evidence validation
-> human review
```

Passing that gate continues to the complete Case 01 v5 DOCX within the same M1;
it does not start another infrastructure project. Model output is always a
draft and cannot approve its own scientific facts. M1 may add only the minimum
UI needed to exercise approved checkpoint contracts.

M2 starts only after M1 exposes a stable, user-aligned vertical slice. M3
hardens proven behavior; it does not precede it.
