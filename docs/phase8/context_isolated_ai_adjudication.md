# Context-Isolated AI Adjudication

## Scope

`HUMAN_SPOT_CHECKED_AI_ADJUDICATION` is an engineering validation method for
internal demonstration. It combines two independently started source-review
sessions, deterministic rule checks, a fresh anonymous adjudication session,
and at most 10 unique core-item human spot checks. It does not establish a
publication-grade accuracy estimate.

The three AI stages never write human decision events. Their outputs live under
the ignored `local/phase8_evidence/ai_adjudication/` tree. Effective human
decisions take precedence over new AI adjudication, which takes precedence over
the old extraction.

## Isolation Contract

Layer 1 receives source files, opaque task IDs, fact categories, required output
fields, and minimal locator hints. It receives no old candidate values,
rationales, confidence, support status, human decisions, or peer output.

Layer 2 receives source files, opaque task IDs, the old candidate and locator,
fact type, and a verification rubric. It receives no Layer 1 output, human
decision, old rationale/confidence, or later-stage result.

Layer 3 is created only after both earlier outputs and their immutable-input
checks pass. It receives anonymous Candidate X/Y structures, deterministic rule
flags, sources, and the adjudication rubric. The fixed-seed X/Y mapping remains
private to the coordinator.

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

## Human Budget

The total budget is 10 unique core items. Sampling prioritizes at most two
highest-risk cases, includes the highest-risk mechanism/figure/negative-claim
case when available, and includes at least one fixed-seed low-risk consensus
sample when capacity remains. Cases above the budget remain unresolved rather
than being presented as human-confirmed.

Any human comparison metrics are described as a small human spot-check sample,
an engineering signal only, and not a publication-grade validation estimate.

## Checkpoints

The current checkpoint is `PREPARED_FOR_INDEPENDENT_LAYER_1_AND_2`. Phase 8B
has not started. A coordinator must validate both output manifests and unchanged
inputs before preparing Layer 3.
