# Product Positioning

Status: `CURRENT_POSITIONING_SUMMARY`

Last updated: 2026-07-19

The authoritative product definition is
[Product North Star](../product/PRODUCT_NORTH_STAR.md). This document preserves
the concise positioning and competition boundary.

## User-facing position

> An offline-first literature-review workbench for chemistry researchers. A
> user supplies a research question and a bounded set of papers with supporting
> information; the system preserves traceable evidence and scientific
> disagreement, pauses for repeated user review, and produces a revisable DOCX
> whose material scientific claims can be traced to their sources.

The final expert-facing deliverable is one clean DOCX. Internal evidence,
claim, conflict, revision, checkpoint, and hash artifacts provide the audit
trail but are not the primary user deliverable.

## Honest current stage

The repository has a credible technical kernel and one deep chemistry case. It
is crossing from a research-workflow codebase into a reusable product. It does
not yet demonstrate a general product, publication-grade scientific
acceptance, autonomous scientific discovery, an experimental feedback loop, or
cross-domain generality.

Its strongest differentiators are:

- source and SI identity plus exact locators;
- evidence-governed claims rather than free-form RAG prose;
- explicit retention of missing evidence and scientific conflict;
- repeated, hash-bound human checkpoints with revision propagation;
- a practical final DOCX and visual-review boundary.

## Architecture position

The internal statement is:

> Chemistry-first, case-neutral, evidence-governed review workflow with
> auditable single-user checkpoints.

`Case-neutral` does not mean domain-neutral. `Single-user checkpoints` means
one user may complete all review moments; it does not mean multiple people are
required or that one person's different review perspectives are independent
expert reviews.

`Offline-first` separates offline preparation and validation, optional
authorized provider execution, and local review/export. It must not be
marketed as fully offline when the selected Qwen, Bailian, search, or retrieval
path requires network access.

## Case 01 role

Case 01 is a reference implementation, regression fixture, and audit record.
It demonstrates depth but must remain behind the public project and artifact
contracts. Its paper IDs, allene rules, fixed claim counts, and frozen hashes
cannot define the public schema.

Case 01 v5 is the approved golden calibration. The first strong reuse proof is
a later new 20-40-paper chemistry review through the same public contract,
without topic-specific production-code changes.

## Productization priorities

1. Stabilize the generic project, artifact, corpus, checkpoint, and release
   contracts.
2. Exercise them through Case 01 v5 and the minimal bilingual checkpoint UI.
3. Run a new large chemistry review in Windows-native QoderWork CN.
4. Harden the one-entry user experience and reproducible evaluation.

The binding sequence is [PRODUCT_ROADMAP.md](../product/PRODUCT_ROADMAP.md).
Historical competition audits remain evidence of how the gaps were found, but
they no longer define current sequencing.
