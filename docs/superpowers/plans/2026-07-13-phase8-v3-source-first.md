# Phase 8 V3 Source-First Preparation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan inline. Do not use subagents, start scientific review, or create Layer B/C.

**Goal:** Freeze the semantically invalid V2 queue, preserve its 41 tasks as an adversarial regression corpus, and prepare one immutable external V3 source-first Layer A workspace.

**Architecture:** A focused `v3_source_first` module builds three scientific source units plus one opaque calibration unit from the already identity-validated local sources. A strict package validator verifies every manifest-listed file, while workspace-local verification, result validation, and finalization scripts enforce source-unit coverage, claim uniqueness, JSON Schema, task hashes, unchanged inputs, and a closed output-file set. V2 artifacts and all scientific data stay outside Git.

**Tech Stack:** Python 3, JSON/JSONL, JSON Schema, SHA-256 manifests, unittest, Make, Git.

---

### Task 1: Freeze V2 and define the adversarial corpus

**Files:**
- Create outside Git: `<V2_RUN>/coordinator/V2_DIAGNOSTIC_REPORT.json`
- Create outside Git: `<V2_RUN>/coordinator/V2_DIAGNOSTIC_REPORT.md`
- Create outside Git: `<V2_RUN>/DO_NOT_CREATE_V2_LAYER3`
- Create: `review_writer/phase8/v3_source_first.py`
- Test: `tests/test_phase8_v3_source_first.py`

- [ ] Write a failing test that combines the 41 V2 Layer 1/2 tasks and outputs without changing the source run.
- [ ] Require exact blind-ID coverage and preserve input/output hashes in every regression row.
- [ ] Record the six-category external-audit aggregate while marking unavailable per-item labels `NOT_PROVIDED`.
- [ ] Write diagnostic-only markers that prohibit final AI decisions, human-log writes, and Phase 8B evidence use.
- [ ] Run `python3 tests/test_phase8_v3_source_first.py` and confirm the adversarial corpus tests pass.

### Task 2: Define source-first Layer A contracts

**Files:**
- Create: `schemas/phase8_source_first_v3/source_unit.schema.json`
- Create: `schemas/phase8_source_first_v3/layerA_inventory_output.schema.json`
- Create: `schemas/phase8_source_first_v3/layerB_verifier_output.schema.json`
- Create: `templates/phase8_source_first_v3/AGENTS.override.md`
- Create: `templates/phase8_source_first_v3/WORK_ORDER.md`
- Create: `templates/phase8_source_first_v3/layerB_AGENTS.override.md`
- Create: `templates/phase8_source_first_v3/layerB_WORK_ORDER.md`
- Test: `tests/test_phase8_v3_source_first.py`

- [ ] Write failing schema tests for all required claim fields and epistemic-class enums.
- [ ] Add conditional validation so yield/ee/er/dr claims require a reaction entry and product.
- [ ] Add one result row per source unit with `source_unit_id`, `input_manifest_hash`, `task_hash`, and an open-length `claims` array.
- [ ] Encode the shared `EXACT_PAGE`, `PAGE_WINDOW`, `SECTION`, and `FULL_SOURCE` locator policy in each input task and the work order.
- [ ] Add procedural isolation instructions in `AGENTS.override.md`, including no skills, parent/sibling reads, network, or restored sessions.
- [ ] Define the future exact-claim verifier verdict/correction schema and matching isolation template without creating a Layer B workspace.

### Task 3: Implement deterministic package and result validation

**Files:**
- Create: `templates/phase8_source_first_v3/validation_core.py`
- Create: `templates/phase8_source_first_v3/verify_input_package.py`
- Create: `templates/phase8_source_first_v3/validate_results.py`
- Create: `templates/phase8_source_first_v3/finalize_output.py`
- Test: `tests/test_phase8_v3_source_first.py`

- [ ] Write failing tests for a changed source, changed task, duplicate/missing source-unit ID, duplicate claim ID, wrong manifest/task hash, schema violation, and unexpected output file.
- [ ] Make `verify_input_package.py` verify the manifest checksum plus every manifest-listed file hash and reject unlisted input files.
- [ ] Make `validate_results.py` enforce exact source-unit coverage, unique claims, task hashes, input hash, locator scope, claim binding, and JSON Schema.
- [ ] Make `finalize_output.py` call both validators and write `OUTPUT_MANIFEST.json` plus its checksum only after both pass.
- [ ] Verify that a failed finalization leaves no success manifest.

### Task 4: Build and validate the external V3 Layer A workspace

**Files:**
- Create: `scripts/phase8/prepare_v3_source_first.py`
- Modify: `Makefile`
- Create outside Git: `<WORKSPACE_PARENT>/phase8_source_first_v3_<UTC>/coordinator/`
- Create outside Git: `<WORKSPACE_PARENT>/phase8_source_first_v3_<UTC>/layerA_inventory/`

- [ ] Write a failing workspace test for repo-external placement, no symlinks/Git, read-only input files, writable output, and no Layer B/C.
- [ ] Build three full-source scientific units: F3I, F47A main+SI, and P403 main+SI.
- [ ] Derive one opaque P403 SI exact-page calibration unit from the ignored human event; keep its gold answer and private mapping only in coordinator.
- [ ] Generate `INPUT_MANIFEST.json` and `INPUT_MANIFEST.sha256` where the checksum file covers the manifest and every listed input.
- [ ] Validate source hashes, source-unit hashes, isolation text, no absolute paths, no gold/calibration markers, and no unexpected files before atomic rename.
- [ ] Add `phase8-v3-source-first-check` and run it with the existing V2/adjudication gates.

### Task 5: Publish public method state without scientific artifacts

**Files:**
- Modify: `docs/phase8/README.md`
- Modify: `docs/phase8/context_isolated_ai_adjudication.md`
- Modify: `docs/handoff/CURRENT.md`

- [ ] Document V2 as `V2_DIAGNOSTIC_COMPLETE` and not a scientific adjudication queue.
- [ ] Document V3 source-first inventory, exact-claim verification, conflict-only Layer C, shared locator policy, and active calibration execution.
- [ ] Set the public checkpoint to `PREPARED_FOR_SOURCE_FIRST_LAYER_A_V3`; state that Layer A has not started and Layer B/C do not exist.
- [ ] Run `make release-readiness-check`, all Phase 8 gates, `make quality-check`, `make portability-check`, and `make smoke`.
- [ ] Commit implementation/schema/tests separately from method documentation; push normally and keep PR #3 Draft.
- [ ] Wait for CI and confirm all checks complete successfully.

## Self-Review

- The plan covers every V3 requirement through a deterministic artifact or an explicit future-stage boundary.
- The only calibration value is read from the ignored human log and stored outside Git; public code contains no gold answer.
- Open inventory cardinality is compatible with deterministic coverage because coverage applies to source-unit result rows, not to a fixed number of claims.
- Layer B/C schemas may be published now, but neither workspace is created in this turn.
