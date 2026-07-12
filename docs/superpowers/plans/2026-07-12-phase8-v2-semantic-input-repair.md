# Phase 8 V2 Semantic Input Repair Implementation Plan

> **For agentic workers:** Execute inline in one coordinator session. Do not run any scientific review session while implementing this plan.

**Goal:** Replace the diagnostic first run with a source-identity-gated, atomic, dual-mode V2 A/B input package containing exactly 41 active tasks.

**Architecture:** A focused V2 semantic-input module audits source identity from weighted local PDF evidence, reconciles exclusions and hidden calibration, classifies task mode and locator quality, enforces atomicity, and prepares immutable external A/B workspaces only after all hard gates pass. Real sources, audit results, task packages, calibration answers, and model outputs remain ignored local data.

**Tech Stack:** Python 3, existing PyMuPDF Phase 8 environment, JSON/JSONL, JSON Schema, unittest-style offline tests, Make, Git.

---

### Task 1: Preserve common ingest infrastructure

**Files:**
- Commit: `review_writer/phase8/ai_adjudication.py`
- Commit: `scripts/phase8/coordinate_ai_adjudication.py`
- Commit: `tests/test_phase8_ai_adjudication.py`
- Commit: `templates/phase8_ai_adjudication/layer3_*.md`

- [x] Save the uncommitted diff to `/tmp/phase8_ingest_ab_uncommitted.patch`.
- [x] Run the adjudication, quality, portability, and smoke gates.
- [x] Commit and push only public infrastructure.

### Task 2: Downgrade the first run

**Files:**
- Create outside Git: `<OLD_RUN>/coordinator/SEMANTIC_INPUT_DEFECT_REPORT.json`
- Create outside Git: `<OLD_RUN>/coordinator/SEMANTIC_INPUT_DEFECT_REPORT.md`
- Create outside Git: `<OLD_RUN>/DO_NOT_EXECUTE_LAYER3`

- [x] Back up coordinator state before changing it.
- [x] Mark the run diagnostic-only and prohibit scientific adjudication/final decision writes.
- [x] Preserve all old artifacts as regression data.

### Task 3: Audit and quarantine source identity

**Files:**
- Create: `review_writer/phase8/v2_semantic_inputs.py`
- Create: `scripts/phase8/prepare_v2_semantic_review.py`
- Test: `tests/test_phase8_v2_semantic_inputs.py`
- Create outside Git: `local/phase8_evidence/quarantine/source_identity_conflicts/`

- [x] Test weighted DOI/title/author/role evidence and explicit conflicting DOI behavior.
- [x] Copy the old conflicting P403 main article to ignored read-only quarantine with provenance.
- [x] Audit all five active source identities and reject every conflict from package creation.

### Task 4: Build the 41-task semantic set

**Files:**
- Create: `schemas/phase8_ai_adjudication/layer1_v2_output.schema.json`
- Create: `schemas/phase8_ai_adjudication/layer2_v2_output.schema.json`
- Create: `templates/phase8_ai_adjudication/layer1_v2_*.md`
- Create: `templates/phase8_ai_adjudication/layer2_v2_*.md`

- [x] Test exact exclusions: 6 effective human decisions, 5 unavailable Phase 7 claims, and 1 no-SI status item.
- [x] Test placeholder/sentinel suppression and the expected 2 candidate-verification plus 39 dual-extraction modes.
- [x] Test locator-quality projection so precise labels appear only for verified exact locators.
- [x] Test one entity, one reaction stage, one fact type, and one evidence target per task.
- [x] Store the human calibration answer only in coordinator-private hidden calibration state.

### Task 5: Enforce preflight and prepare V2 A/B

**Files:**
- Create outside Git: `<WORKSPACE_PARENT>/phase8_three_layer_v2_<UTC>/layer1_extractor/`
- Create outside Git: `<WORKSPACE_PARENT>/phase8_three_layer_v2_<UTC>/layer2_verifier/`

- [x] Fail before workspace creation unless all semantic hard gates pass.
- [x] Build relative immutable manifests and read-only source/input/schema files.
- [x] Scan both packages for human decisions, sentinels, cross-layer data, absolute paths, and calibration leakage.
- [x] Write a coordinator resume at `PREPARED_FOR_INDEPENDENT_LAYER_1_AND_2_V2` and do not create Layer 3.

### Task 6: Verify and publish public changes

**Files:**
- Modify: `Makefile`
- Modify: `docs/phase8/README.md`
- Modify: `docs/phase8/context_isolated_ai_adjudication.md`
- Modify: `docs/handoff/CURRENT.md`

- [x] Run the new V2 gate, Phase 8 gates, quality, portability, smoke, and release readiness.
- [ ] Commit implementation/schema/tests separately from public method documentation.
- [ ] Push normally, update PR #3 methodology text, wait for CI, and confirm Draft remains true.
