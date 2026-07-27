# Review Writer Product Rescue Implementation Plan

Goal: repair the existing path so reusable sources, hard human checkpoints, bounded batch processing, figures, and one authoritative manuscript work at real scale.

Architecture: extend review_writer.project.vertical_review, acquisition helpers, scripts/run_vertical_review.py, the existing Expert Kit, and the existing dashboard. Add no second state store or runtime. All behavior changes use failing tests first.

## Task 1: Checkpoint integrity

- Add failing projection and dashboard tests proving a new Risk Packet invalidates old decisions, Writer Packet rejects unresolved or stale decisions, and only complete UI decisions advance to ready_for_writing.
- Add canonical states and digest-bound transitions shared by CLI and dashboard.
- Verify bounded timeout and resume behavior at every human checkpoint.

## Task 2: Reusable intake and robust matching

- Add failing tests for DOI/hash reuse, parser-contract mismatch, MAIN/SI roles, and prohibition on reusing downstream scientific artifacts.
- Implement a read-only reusable-library audit without a registry or database.
- Add failing importer tests for alias, DOI filename, first-page DOI, normalized title, Unicode, duplicate, and ambiguous inputs.
- Extend the current matcher and expose unresolved rows.

## Task 3: SI policy and supplementation

- Test and implement MAIN_REQUIRED plus SI REQUIRED, RECOMMENDED, or NOT_REQUIRED.
- Add project API and Sources UI support for DOI/title additions, system recommendation, researcher disposition, reuse status, and unresolved mapping.

## Task 4: Canonical batch runner and Expert Kit constraints

- Test persisted per-study stages, idempotent deterministic resume, exact Reviewer coverage, immutable provider output, and pause when semantic or Reviewer output is absent.
- Implement one maintained bounded runner using existing preparation, assembly, R0, validation, and registration.
- Tighten Expert Kit allowlists and stage reload behavior; forbid one-off scripts and context-memory authorization.
- Report measured credits and forecasts without calling estimates measured.

## Task 5: Progress, Risk, and figure UX

- Test and render per-study processing, reuse, MAIN/SI gaps, credits, unresolved matches, and mandatory Risk status.
- Keep one researcher-language next action and hide internal terms.
- Make all Risk targets operable and block unresolved submission.
- Render LICENSED_SOURCE, ORIGINAL_GENERATED, and FIGURE_BRIEF_PLACEHOLDER states.

## Task 6: Authoritative manuscript and release

- Test draft revision drift, pending scientific edits, figure license and placeholder gates, lineage, and DOCX binding.
- Bind workbench and export to one manuscript revision and release snapshot.
- Preserve normal edits, flag scientific edits, allow restore, and block verified export while pending.

## Task 7: Verification and Windows acceptance package

- Run scaled-review-check, smoke, quality-check, qoderwork-check, diff checks, and browser engineering smoke in WSL.
- Build the Expert Kit from the verified WSL commit.
- Create one clean Windows-native acceptance copy without overwriting dirty data and without remote writes.
- Report paths, checksum, tests, real versus synthetic data, limitations, and leave human E2E pending.
