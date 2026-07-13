# Phase 8 V3.1 Layer A Contract Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline. Do not use subagents, start Layer A, or modify the frozen V3 run.

**Goal:** Replace the NO-GO V3 Layer A contract with a source-scoped, non-vacuous, semantically validated V3.1 preparation containing separate scientific and calibration workspaces.

**Architecture:** New V3.1 schemas and workspace-local validators keep V3 compatibility artifacts untouched. Eight scientific shards encode explicit review questions, inclusion/exclusion rules, required page ranges, and unit-specific completion contracts; a separate exact-page calibration workspace uses the same result schema and prompt core while private gold and scoring remain coordinator-only. Task `search_scope` and claim `evidence_locator` are separate contracts.

**Tech Stack:** Python 3, PyMuPDF, JSON Schema, JSON/JSONL, SHA-256, unittest, Make, Git.

---

### Task 1: Reproduce and freeze the NO-GO baseline

**Files:**
- Create: `tests/test_phase8_v3_1_contract.py`
- Create outside Git: `<V3_1_RUN>/coordinator/V3_NO_GO_AUDIT.json`

- [ ] Hash every regular file in the frozen V3 run and record its 22-file aggregate baseline.
- [ ] Write eight failing regression cases for empty completion, unreadable-with-claims, wrong source role, out-of-range page, visual-without-locator, unbound numeric outcome, invalid ee normalization, and wrong observed page label.
- [ ] Run the cases against the V3 validator and confirm all eight are incorrectly accepted before changing production contracts.
- [ ] Preserve the independent audit classification and old bypass outcomes as coordinator-local diagnostic evidence only.

### Task 2: Define executable source scope and completion contracts

**Files:**
- Create: `schemas/phase8_source_first_v3_1/source_unit.schema.json`
- Create: `schemas/phase8_source_first_v3_1/layerA_inventory_output.schema.json`
- Create: `review_writer/phase8/v3_1_source_first.py`

- [ ] Require `unit_kind`, `search_scope`, `review_question`, included claim classes, excluded material, required page ranges/sections, completion criteria, source page counts, and task hash.
- [ ] Bind paper/source IDs and source-role keys exactly; reject irrelevant locator fields for each search-scope mode.
- [ ] Build eight scientific shards: F3I pages 0-8, 9-16, and 17-32; F47A main+SI; P403 main; and P403 SI pages 0-9, 10 plus 12-17, and 18-41. Exclude F3I references at 33-38, the calibration page at P403 SI index 11, and routine spectra at 42-189.
- [ ] Require output coverage summary, pages examined, sections examined, status reason, and statuses `COMPLETED`, `PARTIAL`, `SOURCE_UNREADABLE`, `OUT_OF_SCOPE`, or `NO_QUALIFYING_EVIDENCE`.
- [ ] Reject global zero-claim completion while allowing well-formed partial/unreadable/conflict rows in a run that otherwise contains valid scientific evidence.

### Task 3: Enforce semantic claim binding

**Files:**
- Create: `templates/phase8_source_first_v3_1/validation_core.py`
- Create: `templates/phase8_source_first_v3_1/verify_input_package.py`
- Create: `templates/phase8_source_first_v3_1/validate_results.py`
- Create: `templates/phase8_source_first_v3_1/finalize_output.py`
- Test: `tests/test_phase8_v3_1_contract.py`

- [ ] Replace task/claim `locator_scope` equality with task `search_scope` containment and claim `evidence_locator` restricted to exact page or tight page window.
- [ ] Validate PDF page counts, observed printed page labels, source roles, visual component locators, numeric product/entry/stage/metric/value/unit/conditions, normalization provenance, and ee/er/dr/yield unit types.
- [ ] Add controlled reaction-stage ontology and reject substrate/target, intermediate/pathway, and proposed/experimental mechanism conflation.
- [ ] Add structured source conflicts with conflict type, both reported alternatives, and both locators; never auto-select one side.
- [ ] Make finalization delete stale success files first and create an output manifest only after input and full semantic validation pass.

### Task 4: Separate scientific inventory and calibration execution

**Files:**
- Create: `templates/phase8_source_first_v3_1/AGENTS.override.md`
- Create: `templates/phase8_source_first_v3_1/WORK_ORDER.md`
- Create: `scripts/phase8/prepare_v3_1_source_first.py`
- Create: `scripts/phase8/evaluate_v3_1_calibration.py`

- [ ] Create `layerA_inventory` with scientific shards only and `calibration_layerA` with one exact-page source unit only.
- [ ] Use identical core schema, semantic validator, finalizer, and prompt contract in both workspaces; vary only the source-unit input and workspace role.
- [ ] Extract page counts and printed labels from PDF text blocks at package time; correct the private calibration label from the source page without hardcoding private gold in public code.
- [ ] Keep private gold in coordinator, write only its hash to public run state, exclude calibration from scientific claims, and preserve the 6/10 human budget.
- [ ] Add a coordinator-side evaluator that requires one exact gold match across entity, claim type, stage, metric, value, unit, page index, printed label, epistemic class, and non-target-reaction classification.
- [ ] Record resolved global/repository/workspace instruction-source paths and hashes without copying secrets or auth material.

### Task 5: Verify, publish, and stop

**Files:**
- Modify: `Makefile`
- Modify: `docs/phase8/README.md`
- Modify: `docs/phase8/context_isolated_ai_adjudication.md`
- Modify: `docs/handoff/CURRENT.md`

- [ ] Run all eight negative cases and positive populated, partial, unreadable, and structured-conflict cases.
- [ ] Run V3.1, V3, V2, all Phase 8, quality, portability, smoke, and release-readiness gates.
- [ ] Commit implementation/tests separately from public methodology documentation; push normally and update Draft PR #3.
- [ ] Create a fresh `phase8_source_first_v3_1_<UTC>` run from committed code and validate both workspaces locally.
- [ ] Recompute the frozen V3 22-file aggregate hash and require exact equality with the pre-change baseline.
- [ ] Wait for CI, confirm Draft state, and stop at `PREPARED_FOR_SOURCE_FIRST_LAYER_A_V3_1` without starting either Layer A session.

## Self-Review

- The plan covers every NO-GO blocker and all eight supplied bypasses.
- Scientific and calibration sessions share contracts but no task context.
- Private gold is derived from ignored human state plus PDF-observed locator metadata and never appears in public tests/templates/PR text.
- `NO_QUALIFYING_EVIDENCE` is structurally valid but cannot make an all-empty run finalize successfully.
