# Review-Writer Product North Star

Status: `ACCEPTED_TARGET_PRODUCT_CONTRACT`

Last updated: 2026-07-19

## User-facing North Star

> An offline-first literature-review workbench for chemistry researchers. A
> user supplies a research question and a bounded set of papers with supporting
> information; the system preserves traceable evidence and scientific
> disagreement, pauses for repeated user review, and produces a revisable DOCX
> in which every important scientific claim can be traced to its source.

The final expert-facing deliverable is one clean DOCX. Source inventories,
claims, retrieval bundles, conflicts, revision events, figures, audit reports,
and hash manifests are internal product artifacts.

## Internal architecture statement

> Chemistry-first, case-neutral, evidence-governed review workflow with
> auditable single-user checkpoints.

`Single-user checkpoints` means one user may complete the whole workflow, but
the product stops repeatedly for review at the stages where human intent or
scientific judgment matters. It does not imply independent experts or multiple
accounts.

## Honest current status

The repository has a credible technical kernel and one deep chemistry case. It
is moving from a research-workflow codebase toward a reusable product. It is
not yet a generic product, an AI Scientist, a fully autonomous writer, or a
publication-ready manuscript generator.

Demonstrated foundations include source/SI identity work, claim extraction,
locators, conflict retention, bounded human review, grounded synthesis,
provider adapters, RAG experiments, a local dashboard, deterministic quality
checks, and DOCX export. The missing product layer is a stable project and
artifact contract, unified checkpoint semantics, one simple QoderWork entry,
and a clean end-to-end run that does not depend on Case 01 constants.

M0/PR A is not the final product or a workflow-engine build. It only proves that
one minimum local contract can validate a synthetic non-allene fixture and
frozen Case 01 without allowing editable configuration to contaminate immutable
evidence, human decisions, snapshots, or releases. Target-product semantics in
the Checkpoint Contract do not automatically become M0 implementation work.

## Intended user journey

The target QoderWork CN experience is deliberately small:

1. Clone or download the repository and open it as the current Windows-native
   QoderWork workspace.
2. Put main papers and SI in a local input directory.
3. Provide only a topic and the paper directory to the
   `chem-review-orchestrator` entry.
4. Review the current task in a localhost dashboard when QoderWork pauses.
5. Approve, revise, request evidence, or exclude material; then resume the same
   project.
6. Download one clean DOCX after the current DOCX snapshot passes the final
   checks.

Users must not need to understand Phase 6, Phase 7, Phase 8A, fixed paper IDs,
internal run directories, RAG implementation details, or model payload files.

## Product boundaries

The product is:

- chemistry-first, not cross-domain by default;
- case-neutral, while retaining chemistry-specific validation profiles;
- designed for bounded corpora and explicit discovery choices;
- evidence-governed, not a free-form citation generator;
- single-user with repeated human review, not a mandatory multi-person system;
- local-first and offline-first, not necessarily fully offline;
- capable of optional, explicitly authorized provider execution;
- optimized for an expert-reviewable DOCX, not automatic publication acceptance.

The product is not currently intended to provide:

- autonomous hypothesis generation or experimental closed loops;
- a general scientific ontology or universal knowledge graph;
- account, payment, multi-tenant, or cloud collaboration features;
- silent use of model-suggested citations as scientific evidence;
- automatic conversion of a self-reviewed draft into an expert-reviewed release.

## Offline-first execution boundary

The product must distinguish three execution classes:

1. **Offline preparation and validation**: source hashing, identity checks,
   parsing, deterministic validation, local indexing, checkpoint state, and
   export checks.
2. **Optional authorized provider execution**: Qwen generation, model-assisted
   discovery, or remote retrieval only when the project policy and user allow
   it.
3. **Local review and export**: localhost checkpoint UI, revision history,
   visual review, and final DOCX handoff.

Default CI remains offline. `Offline-first` must never be advertised as
`fully offline` when a selected model, search provider, or remote RAG service
requires network access.

Project `network_policy` is a capability ceiling, not permission to make a
call. M0 accepts only `OFFLINE_ONLY`. Any future provider execution still
requires explicit per-run human authorization, and its non-sensitive actual
provider/model identity belongs in RunManifest rather than ProjectManifest.

## Source and corpus model

The user-provided papers are the seed corpus. Discovery mode is selected per
project:

- `CLOSED_CORPUS`;
- `MODEL_ASSISTED`;
- `SCHOLARLY_SEARCH`;
- `HYBRID`.

M0 accepts only `CLOSED_CORPUS`. The field declares the scientific corpus
boundary; it does not execute discovery or silently add sources beyond the
manifest and its closed product-maintained adapter.

Pure search results and model-suggested references are `CandidatePaperRecord`
objects. They are not `SourceRecord` objects and cannot support a scientific
claim. A candidate becomes a source only after the expected document role can
be resolved as `MAIN` or `SI`; otherwise the workflow raises the blocking issue
`DOCUMENT_ROLE_UNRESOLVED`.

A `SourceRecord` keeps independent dimensions instead of one mixed role:

| Dimension | Values | Meaning |
| --- | --- | --- |
| `document_role` | `MAIN`, `SI` | Expected document relationship to the paper |
| `usage_role` | `EVIDENCE`, `BACKGROUND`, `DISCOVERY_ONLY` | Permitted product use |
| `governance_status` | `CANDIDATE`, `INCLUDED`, `EXCLUDED` | Corpus decision |
| `availability_status` | `METADATA_ONLY`, `FULL_TEXT_AVAILABLE`, `PARSED` | Highest available level for the current hash-pinned version |
| `integrity_status` | `UNVERIFIED`, `VALIDATED`, `QUARANTINED` | Whether that source version is trusted for workflow use |

`UNVERIFIED` has not completed the checks required for its current available
level. `VALIDATED` means source identity and hash binding passed and, when an
active parse exists, its parse QA passed. `QUARANTINED` marks a known wrong
binding, wrong document, damaged source, or otherwise untrusted source version;
it does not claim that any scientific conclusion is correct or incorrect.

`availability_status` does not report parse failure or trust. Parse execution
and QA belong to a separate `ParseArtifact`. A bad derived parse can be
quarantined without contaminating a correct source document. Conversely, a
wrong document version already parsed under the wrong identity is accurately
represented as `PARSED` plus `QUARANTINED`.

Evidence Discovery RAG eligibility is derived, not a new lifecycle state. It
requires `INCLUDED`, `EVIDENCE` or `BACKGROUND`, `PARSED`, and `VALIDATED` for
the same source version. Approved scientific-claim eligibility additionally
requires `usage_role=EVIDENCE`, a precise locator, and the source content hash.

`EXCLUDED` or `QUARANTINED` sources cannot enter either RAG, candidate claims,
the Approved Claim Registry, or manuscript prose. `DISCOVERY_ONLY` can support
candidate discovery only. `BACKGROUND` may provide context, but it must be
promoted to `EVIDENCE` and pass evidence checks before supporting a concrete
fact. `CANDIDATE`, `METADATA_ONLY`, and `FULL_TEXT_AVAILABLE` cannot support an
approved claim.

Every source version retains its content hash, active parse artifact, reason
code, validation report, and supersession link. Status values alone are not an
adequate audit record.

## Evidence retrieval authority

### Evidence Discovery RAG

Indexes only project-local, hash-pinned MAIN/SI that passed source identity,
parse QA, and the applicable corpus checkpoint. Retrieval can populate a
visible retrieval bundle or candidate-claim workflow. It cannot write facts
directly into the clean manuscript.

### Approved Claim Registry and optional derived retrieval

The Approved Claim Registry, not a vector index, is the authority. For bounded
MVP corpora, writing may query the registry deterministically by section, claim
type, paper ID, or other structured fields. An Approved Claim RAG/index is an
optional rebuildable optimization when scale justifies it; it is not required
for M0/PR A.

Immutable `ClaimVersionRecord` content and `ClaimDecisionEvent` decisions build
a rebuildable `ApprovedClaimRegistryProjection`. A claim is writing-eligible
only when its current version is registered and supported, all evidence and
supporting-claim dependencies remain eligible, conflict treatment permits the
requested language, and the claim remains in active scope. Unsupported unused
candidates do not block the project; an evidence-required issue is raised only
while a current intent or downstream artifact still depends on the gap. The
workflow never fills that gap from free retrieval or model memory.

Every chunk and claim retains project ID, paper ID, `document_role`, source
content SHA-256, page and section/table/figure locator, excerpt hash,
governance status, and version. Projects have isolated indexes, caches, and
retrieval histories.

## Human review model

The product uses 15 logical checkpoints described in
[CHECKPOINT_CONTRACT.md](CHECKPOINT_CONTRACT.md). They do not imply 15 mandatory
clicks. Each checkpoint declares one policy:

- `HUMAN_REQUIRED`;
- `HUMAN_ON_EXCEPTION`;
- `AUTOMATIC_VALIDATION`;
- `NOT_APPLICABLE`.

The UI presents only the current or affected work. Section drafting uses
rolling paragraph/section review. The same user may perform every review
perspective. A self-review must never be presented as independent expert review.

## Revisions, conflicts, and release

User edits are immutable revision events with optimistic concurrency. Each edit
binds a base revision and base artifact hash, stores the before/after text and
diff, and records expected and actual impact. A conflicting concurrent edit is
not overwritten; the UI presents a three-way diff.

User Intent history is append-only. Each intent records its scope, priority,
supersession relationship, and withdrawal state. Only the current `ACTIVE`
intent projection participates in generation or checkpoint snapshots.

Scientific disagreement uses immutable ConflictRecord versions, immutable
decision events, and a rebuildable projection. Engineering errors remain
ArtifactValidationIssues. Different numbers or interpretations do not become
academic controversy until entity, conditions, stage, metric, scope, and
epistemic strength are checked for comparability. Only current, registered,
supported, comparable, and substantively conflicting positions may become an
attributed unresolved controversy; the ConflictRecord itself never writes
prose or turns a dispute into settled fact.

A proposed claim revision never replaces the current registered version before
the new version passes its evidence-registration operation. Claim text and
lineage are immutable by version; support and governance are event-replayed
projections. Ordinary checkpoint approval cannot register scientific facts.

`ProjectManifest` is editable validated configuration for the current local
project. Historical work never depends on whatever the file contains later:
each corpus, run, draft, checkpoint snapshot, and release captures the resolved
normalized configuration and its SHA-256. A configuration change appears as
`CONFIG_CHANGED` with affected stages in project status. M0/PR A does not add
manifest adoption events, a manifest projection, a general event journal, or a
configuration rollback system.

Source versions, claim versions, human scientific decisions, checkpoint
snapshots, and release records remain immutable. Closed
`HASH_MANIFEST.sha256` files belong to immutable snapshots, export packages,
and releases rather than the mutable project root.

Release records are immutable:

- `SELF_REVIEWED_DRAFT`: repeated review by the project user;
- `EXPERT_REVIEWED_RELEASE`: an external expert event binds the same DOCX hash,
  review scope, and conclusion.

A changed DOCX creates a new release candidate. It does not mutate or downgrade
an older expert-reviewed release.

## Case strategy

Case 01 is a reference implementation, regression fixture, and audit record. It
must remain behind generic contracts; its paper IDs, counts, allene rules, and
frozen Phase 8 artifacts cannot define the public schema.

The approved calibration sequence is:

1. preserve Case 01 v4;
2. build a structurally rewritten Case 01 v5 as the golden calibration case;
3. use the minimal checkpoint UI and a Windows-native QoderWork CN run with
   `qwen3.7-max` after the relevant evidence and outline checkpoints;
4. retain the final Case 01 output as a self-reviewed expert-facing DOCX, not a
   publication-ready claim;
5. run a new 20-40 paper chemistry review through the same public contract
   without adding case-specific production code.

## Product metrics

At minimum, track:

- source identity and locator coverage;
- unsupported factual claim rate;
- citation mismatch and numeric inconsistency rates;
- conflict leakage rate;
- user revision retention;
- approval workload by scientific risk;
- time to current expert-reviewable DOCX;
- stale/rebuild scope after revisions;
- Direct LLM, ordinary RAG, and full-system comparison where a bounded
  evaluation is authorized.

## Near-term stop rules

Do not prioritize:

- new Case 01-only validators;
- more provider integrations;
- a broad ontology or knowledge graph;
- accounts, deployment, payments, or multi-tenancy;
- a large frontend rewrite;
- claims of fully offline, publication-ready, cross-domain, or AI Scientist
  capability.

The next implementation work must follow [PRODUCT_ROADMAP.md](PRODUCT_ROADMAP.md).
