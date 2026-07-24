# Product Leader Current Handoff

## Product North Star

Deliver a chemically readable, sentence-traceable mini-review that demonstrates how a frozen evidence ledger can support useful cross-study synthesis without hiding conflicts or overstating mechanistic evidence.

## Verified Current State

- Repository: `kenqia/review-writer`
- Active branch: `feat/phase8b-grounded-review-integration`
- Baseline HEAD: `fbf1725`
- Pull request: PR #4, Draft
- Frozen evidence: 44 records, comprising 37 non-conflict candidates and 7 `SOURCE_CONFLICT_RETAINED` records
- Product status: `HUMAN_FULL_TEXT_REVIEW_REQUIRED`; never `READY_FOR_HUMAN_REVIEW` or `WORKING_DRAFT_ACCEPTED`

## Accepted Decisions

- Center the manuscript on palladium-centered asymmetric allene synthesis.
- Organize by chemical problem, not paper chronology.
- Treat all 37 non-conflict records as candidates; select only what the prose needs and account for every omission.
- Keep all 7 conflicts outside manuscript prose.
- Permit `reviewer_synthesis` only with at least two claims from at least two sources.
- Use one broad review for context and two palladium primary studies for selectivity, scope, and mechanism comparison.
- Keep a concise five-column design-principles table in DOCX and the complete claim detail in XLSX.
- Do not add a figure in this milestone.

## Current Milestone

Case 01 Product-Quality Closure on the existing PR #4 branch.

## Execution Contract

- Use only the frozen 44-record ledger at the evidence path below; do not read PDFs or SI and do not introduce claims beyond that ledger.
- Account for every record as `used`, `intentionally_omitted`, or `retained_conflict`; retained conflicts never enter factual prose.
- Deliver the approved six-section English manuscript at 2000-2400 words, its Markdown/DOCX/CSV/XLSX/provenance/conflict artifacts, a prose diff against `continuousZ`, and self-contained hash manifests.
- Do not call Qwen, Bailian, DashScope, MinerU, or image APIs; do not modify any frozen Phase 8A input, existing `finalZ`, `continuousZ`, or `reconstructedZ` package, QoderWork workspace, or system configuration.
- The closing state is `HUMAN_FULL_TEXT_REVIEW_REQUIRED`; it must never be promoted to `WORKING_DRAFT_ACCEPTED` by this run.

## Acceptance Criteria

- English manuscript is 2000-2400 words with the approved title and six thematic sections.
- Unsupported numbers, wrong-paper citations, and conflict leakage are all zero.
- Selected and omitted records partition all 37 non-conflict candidates.
- DOCX has Word Heading styles, an updateable TOC field, neutral core properties, readable chemistry typography, linked citations, and three clickable DOI links.
- XLSX has readable widths, wrapping, a frozen header row, filtering, and styled headers.
- The versioned delivery directory is self-contained and passes `sha256sum -c HASH_MANIFEST.sha256`.

## Deferred Work

- QoderWork CN replay of the product-quality package.
- Any new evidence extraction, PDF/SI reading, or Phase 8A rerun.
- Figure selection or redraw.
- Second case, generic manifest layer, new validator layer, or product UI expansion.

## Forbidden Regressions

- Do not modify the frozen `...finalZ` or `...continuousZ` outputs.
- Do not leak retained conflicts into prose or restore the unsupported 76%/DBA binding.
- Do not describe the local editorial revision as a current Qwen or QoderWork generation run.
- Curated provenance must record `current_run_model_requests=0`, `authoring_mode=codex_exec_curated_revision`, `authoring_agent_model=gpt-5.6-terra`, `final_text_origin=CURATED_FROM_FROZEN_FINAL_CLAIMS_NO_EXTERNAL_PROVIDER_CALL`, and `reused_upstream_generation_payload=false`.
- Do not mark the manuscript accepted before full human reading and one targeted revision round.

## Evidence Paths

- Frozen ledger: `<WORKSPACE_PARENT>/phase8a_closure_v3_1_1_20260714T120245Z/final/final_reconciled_claims.jsonl`
- Frozen closure manifest: `<WORKSPACE_PARENT>/phase8a_closure_v3_1_1_20260714T120245Z/HASH_MANIFEST.sha256`
- Prior grounded package: `review-projects/case-01-allene-mini-review-20260715T-finalZ/`
- Product-quality package: `review-projects/case-01-allene-mini-review-product-quality-v4/`

## Unresolved Risks

- Cross-study interpretation is contract-valid but still requires expert judgment for emphasis, tone, and mechanistic caution.
- The compact three-source scope supports a mini-review, not comprehensive coverage of asymmetric allene synthesis.
- Word TOC page numbers appear after the reader updates the field in Word.

## Next Human Decision

肯恰大人 should read the complete manuscript, identify any chemical emphasis or phrasing that needs revision, and authorize one targeted editorial pass. Only after that pass may acceptance status be reconsidered.
