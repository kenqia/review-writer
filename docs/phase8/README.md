# Phase 8A Evidence Adjudication

Phase 8A is complete at:

```text
PHASE8A_COMPLETE_PR3_READY_FOR_REVIEW
```

Method label:

```text
HUMAN_SPOT_CHECKED_AI_ADJUDICATION
```

The workflow is an engineering-validation and internal-demonstration method.
It combines source-first Layer A inventory, exact-claim Layer B verification,
deterministic reconciliation, and a bounded human spot check. It does not
establish publication-level scientific validation or complete human review.
Context isolation is procedural rather than an operating-system sandbox or
statistical independence between model weights.

## Closure Results

- Calibration: `PASS`
- Scientific Layer A: `8 rows / 44 claims`
- Layer B: `44/44 completed`
- Layer B verdicts: `29 SUPPORTED`, `4 LOCATOR_ERROR`, `2 REACTION_STAGE_ERROR`, `1 ENTITY_BINDING_ERROR`, `7 SOURCE_CONFLICT`, `1 INSUFFICIENT_EVIDENCE`
- Human spot checks: `4 completed`
- Human budget: `10/10`, remaining `0`
- Final reconciliation coverage: `44/44`
- Usable or deterministically corrected non-conflict claims: `37`
- Retained source-internal conflicts: `7`
- Human-review-required claims: `0`
- Layer C: `SKIPPED_AS_UNNECESSARY`
- Phase 8B: not started

Final disposition counts:

```text
AI_SUPPORTED                              29
AI_CORRECTED_LOCATOR                       4
AI_CORRECTED_REACTION_STAGE                2
AI_CORRECTED_ENTITY                        1
HUMAN_SPOT_CHECKED_CORRECTED_ACCEPT        1
SOURCE_CONFLICT_RETAINED                    7
```

The corrected-accept record preserves the reported 76% stoichiometric yield
while removing the unsupported DBA-specific binding. The entity correction
and one retained Table S2 conflict were human-confirmed. One supported claim
was selected by the fixed SHA-256 sampling rule and passed the spot check.

## Frozen Inputs

```text
Scientific Layer A results:
94757ac4bf7517655633a5b14f23ccc80ed36f3a817e5d16e5889046a03c17da

Scientific Layer A input manifest:
013b4ef4af792afe824a74bc6d40e050ea3fd97b83ad3925fc1327f697219715

Layer B results:
45fc079357bb013d92d60bdcb38b7237a0a4713d166737c6cc6670e73618ec68

Layer B output manifest:
989f5dd1bdd6f167b757ffc24bc25ab05470c9fc69c0bdba673950ed021db73e

Layer B input manifest:
aeb3b5f012a66f821bff109b9108843f6d52b076d2c99eda468068d443c68508
```

Closure artifacts remain in ignored external storage. Public hashes are listed
in `phase8a_status_report.md`; no absolute local path is published.

## Historical Runs

The first three-layer run, V2, V3, and V3.1 remain frozen diagnostic or
acceptance-regression evidence. They are not sources of final scientific
claims. V3.1.1 is the corrected source-first run used for closure.

`F3I_SI` remains represented as `NO_SI_PUBLISHED_ON_OFFICIAL_PAGE`; it was not
treated as a missing-download blocker. Calibration remained physically and
procedurally separate from the scientific workspace.

## Local Safety Boundary

PDFs, SI, full page text, screenshots, private calibration data, individual
human decision records, and per-claim AI outputs remain outside Git. Public
files contain only aggregate status, method boundaries, and hashes.

The legacy Phase 8 dashboard remains a read-only viewer. The original guided
decision writer remains available for the six earlier core-item decisions;
the four final claim-level spot checks are stored in the ignored closure run
and are not appended to that older core-item log.

## Verification

Default checks are offline:

```bash
make phase8-preflight
make phase8-source-inventory-check
make phase8-extraction-check
make phase8-review-package-check
make phase8-dashboard-check
make phase8-decision-writer-check
make phase8-ai-adjudication-check
make phase8-v2-semantic-input-check
make phase8-v3-source-first-check
make phase8-v3-1-source-first-check
make phase8-v3-1-1-source-first-check
make phase8-v3-1-1-layer-b-check
make phase8-v3-1-1-reconciliation-check
make phase8-v3-1-1-closure-check
make release-readiness-check
```

Do not start Phase 8B without a new explicit instruction.
