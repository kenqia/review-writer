# Phase 8 Context-Isolated AI Adjudication Implementation Plan

> **For agentic workers:** This plan must be executed inline in one coordinator session. The task explicitly prohibits subagents, agent spawning, Codex CLI, and background Codex tasks.

**Goal:** Prepare two context-isolated, offline review workspaces and the deterministic coordination machinery for a later three-layer AI adjudication workflow, stopping at `PREPARED_FOR_INDEPENDENT_LAYER_1_AND_2`.

**Architecture:** A standard-library Python library owns immutable package creation, manifests, leakage validation, output validation, deterministic rule flags, anonymous Layer 3 preparation, human-decision precedence, and bounded spot-check sampling. A thin CLI exposes stage commands. Public JSON Schemas and Markdown templates define auditable contracts; real PDFs, human decisions, mappings, and AI outputs remain ignored external data.

**Tech Stack:** Python 3 standard library, JSON/JSONL, JSON Schema documents, `unittest`-style script tests, Make, Git.

---

### Task 1: Reconcile and save the sixth human decision

**Files:**
- Read: `local/phase8_evidence/review_queue/core_review_queue.json`
- Append through existing writer: `local/phase8_evidence/review_decisions/reviewer_1.jsonl`
- Update through existing writer: `local/phase8_evidence/reports/`

- [ ] Build one complete event from the immutable queue record and user-provided edit.
- [ ] Run `record_phase8_decision.py record --dry-run` and verify schema/package checks pass.
- [ ] Record atomically, verify the reread log, checkpoint, progress, resume, ignored backup, and SHA-256 manifest.
- [ ] Write a reconciliation report showing six unique effective human decisions and four remaining budget slots.

### Task 2: Specify package and adjudication behavior with failing tests

**Files:**
- Create: `tests/test_phase8_ai_adjudication.py`

- [ ] Test repo-external workspace enforcement and absence of `.git`/directory symlinks.
- [ ] Test A/B task parity, identical source hashes, opaque task IDs, read-only inputs, and manifest verification.
- [ ] Test filename/key/content leakage allowlists, chain-of-thought rejection, absolute-path rejection, and untracked PDFs.
- [ ] Test output validation and immutable-input detection.
- [ ] Test anonymous balanced X/Y mapping and private mapping separation.
- [ ] Test sentinel, reaction-stage, yield-kind, mechanism, negative-claim, and locator rule flags.
- [ ] Test human precedence, separate AI logs, six protected decisions, and budget `<= 10`.
- [ ] Run `python tests/test_phase8_ai_adjudication.py` and confirm it fails because the module/contracts do not exist.

### Task 3: Implement coordination library, CLI, schemas, and templates

**Files:**
- Create: `review_writer/phase8/ai_adjudication.py`
- Create: `scripts/phase8/coordinate_ai_adjudication.py`
- Create: `schemas/phase8_ai_adjudication/*.schema.json`
- Create: `templates/phase8_ai_adjudication/*.md`

- [ ] Implement stable hashing, atomic writes, copy-with-reflink fallback, permissions, relative manifests, and immutable snapshots.
- [ ] Implement blinded A/B task projection and strict package leakage scans.
- [ ] Implement structured output validation and output manifests.
- [ ] Implement deterministic rule flags without calling an LLM or network.
- [ ] Implement seeded balanced anonymous X/Y mapping stored only in coordinator private state.
- [ ] Implement final AI status mapping, human-decision precedence, and bounded spot-check selection.
- [ ] Run the focused test until green, then refactor while preserving green.

### Task 4: Document the methodology and add deterministic gates

**Files:**
- Modify: `Makefile`
- Modify: `docs/phase8/README.md`
- Modify: `docs/handoff/CURRENT.md`
- Create: `docs/phase8/context_isolated_ai_adjudication.md`

- [ ] Add an offline `phase8-ai-adjudication-check` Make target.
- [ ] Replace obsolete full single-human wording with `HUMAN_SPOT_CHECKED_AI_ADJUDICATION` and prohibited-claim warnings.
- [ ] Document procedural isolation limits, stage checkpoints, manual launch, ingest, and Phase 8B not started.
- [ ] Run focused tests and repository safety checks.

### Task 5: Prepare and validate the real A/B workspaces

**Files:**
- Create outside Git: `<WORKSPACE_PARENT>/<run_id>/coordinator/`
- Create outside Git: `<WORKSPACE_PARENT>/<run_id>/layer1_extractor/`
- Create outside Git: `<WORKSPACE_PARENT>/<run_id>/layer2_verifier/`

- [ ] Record run metadata and input hashes without leaking absolute source paths into layer packages.
- [ ] Copy source PDFs with reflink fallback, verify hashes, and mark all inputs read-only.
- [ ] Generate per-layer `AGENTS.md`, `WORK_ORDER.md`, schemas, tasks, manifests, and writable output directories.
- [ ] Run leakage, parity, hash, permissions, Git-tracking, and manifest checks.
- [ ] Write `COORDINATOR_RESUME.md` with stage, paths, hashes, budget, blockers, and manual launch instructions.
- [ ] Confirm no Layer 3 workspace exists and stop scientific work.

### Task 6: Run full verification, commit, push, and wait for CI

**Files:**
- Commit only public code, tests, schemas, templates, and docs.

- [ ] Run the new gate plus all nine user-required existing gates with fresh output.
- [ ] Audit `git diff`, tracked files, PDF/SI exclusions, absolute paths, and prohibited verification labels.
- [ ] Commit normally on `feat/human-verified-evidence-evaluation` and push without force.
- [ ] Update PR #3 description with the methodology change while retaining Draft status.
- [ ] Wait for CI and report exact check results.
- [ ] Stop at `PREPARED_FOR_INDEPENDENT_LAYER_1_AND_2` and provide the two manual-session paths and unified launch sentence.
