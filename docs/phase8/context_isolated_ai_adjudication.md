# Context-Isolated AI Adjudication

## Scope

`HUMAN_SPOT_CHECKED_AI_ADJUDICATION` is an engineering validation method for
internal demonstration. V3 combines source-first evidence inventory, independent
exact-claim verification, deterministic controls, conflict-only adjudication,
and at most 10 unique core-item human spot checks. It does not establish a
publication-grade accuracy estimate.

AI stages never write human decision events. Their outputs live under ignored
local evidence and external workspace trees. Effective human decisions take
precedence over new claim verification, which takes precedence over old
extraction.

## Isolation Contract

Layer A receives identity-validated source files, opaque source-unit IDs, the
shared locator policy, preferred evidence categories, and the output schema. It
receives no old candidate matrix, human decision, gold answer, or V2 result.

Layer B is created only after strict Layer A ingest. It receives each concrete
claim, its claim hash and locator scope, the original source, and a verification
rubric. It receives no Layer A confidence/rationale, human decision, gold
answer, other claim verdict, or later-stage output.

Layer C is created only when Layer A and Layer B materially disagree about the
same claim. It is not used to compare different valid facts, repair invalid
tasks, or adjudicate unavailable sources.

These controls provide procedural context isolation. They are not an
operating-system security sandbox and do not imply statistical independence
between model weights.

## Deterministic Controls

The offline rules block workflow sentinels as scientific values, missing
locators, source-role mismatches, ungrounded numerical/unit values, compound or
entry mismatches, substrate/product and preparation/target-reaction confusion,
yield-type conflation, untraceable stereometric conversion, unclassified
mechanistic claims, unsupported negative claims, incomplete figure locators,
and bibliography substituted for scientific body evidence.

Rule output is an intermediate control artifact, not a final adjudication.

## V2 Diagnostic Boundary

The first three-layer run is retained as diagnostic evidence only because
source identity, sentinel, availability, locator, and task-type defects were
identified. It is not eligible to produce scientific adjudication decisions.

V2 completed 41/41 outputs in both layers with valid manifests and no known
cross-layer leakage. A later independent PDF audit found semantic task defects:
locator checks did not establish entity/fact/stage/value binding, the fixed
field matrix created nonexistent tasks, and several claims bound metrics to the
wrong entity, reaction stage, or page. V2 is therefore
`SCIENTIFIC_ADJUDICATION_NOT_APPLICABLE`.

Its 41 tasks are an adversarial regression corpus only. Evaluation is limited
to safe rejection, error categorization, and avoiding incorrect value binding.

## V3 Source-First Method

Layer A receives three source units and inventories only atomic evidence that
the sources actually report. Categories are priorities, not required slots. A
missing category creates no claim. Numeric outcomes bind substrate/partner,
product, reaction entry, reaction stage, metric, value, and locator explicitly.

Layer A and future Layer B use one shared locator policy: `EXACT_PAGE` cannot
search elsewhere, `PAGE_WINDOW` stays inside its inclusive window, `SECTION`
stays inside the named section, and only `FULL_SOURCE` permits a full-document
search. Printed page labels are observed from pages rather than derived from PDF
indices.

Layer B independently verifies each exact Layer A claim against its original
source. Layer C is eligible only for a material conflict about the same claim's
value, entity, product, reaction stage, fact type, locator, or epistemic class.
Different but independently valid open-inventory facts are not conflicts.

The existing human-reviewed calibration is now executed as an opaque,
page-scoped source unit using the same Layer A schema and prompt. Its gold stays
coordinator-private, it is excluded from the scientific queue, and it consumes
no additional human-review budget.

## Human Budget

The total budget is 10 unique core items. Sampling prioritizes at most two
highest-risk cases, includes the highest-risk mechanism/figure/negative-claim
case when available, and includes at least one fixed-seed low-risk consensus
sample when capacity remains. Cases above the budget remain unresolved rather
than being presented as human-confirmed.

Any human comparison metrics are described as a small human spot-check sample,
an engineering signal only, and not a publication-grade validation estimate.

## Checkpoints

The current checkpoint is `PREPARED_FOR_SOURCE_FIRST_LAYER_A_V3`. Layer A has
not started. Layer B and Layer C have not been created. Phase 8B has not started.
