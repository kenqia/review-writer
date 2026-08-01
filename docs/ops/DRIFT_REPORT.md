# Drift Report

审计范围：workspace canonicalization only。所有结论保留 `[Verified]`、`[Reported]`、`[Inferred]` 或 `[Unknown]`，没有把 raw candidate 或历史摘要升级为科学事实。

## Handoff drift

- [Verified] `.ai/handoffs/20260801-122233/MANIFEST.json` SHA-256 matches the `LATEST.md` record: `7c91ce68c6c0d036bcf34fe472bf778b19041f96bdf31ba6fc3d9f0711904ab9`.
- [Verified] Handoff main root identity still points to `main@baa9d1616ed7fac44aad4330261c27f22f2006ee`.
- [Verified] Handoff's old integration worktree path and base revision still exist, but its clean-state claim is stale: current `requirements-ci.txt` is modified.
- [Verified] The handoff reported 63822 unavailable; current read-only probe finds PID 135420 listening. This is runtime drift, not permission to restart it.
- [Verified] The four governing documents have the same SHA-256 values recorded in `CURRENT_WORKSPACE_MAP.md` and are read from `31d9dab`.

## Fresh v3 project

Target: `/home/kenqia/my_folder/review-projects/vis-light-olefin-difunctionalization-complete-loop-regression-v3-honest-progressive-fresh`

### Stage and artifacts

- [Verified] `00_brief/review_state.json`: `current_stage=source_parse`, `status=in_progress`, `counts={sources:3,evidence:0,claims:0}`.
- [Verified] `01_evidence/` exists and contains Generic parse, Chemical Paper, dual-source bindings, source truth, and candidate-only material. This does not mean downstream authoritative Evidence is complete; the review-state evidence count remains zero.
- [Verified] `02_synthesis/`, `03_content/`, `04_manuscript/`, `05_release/`, `06_evaluation/`, and `07_credits/` are absent.
- [Verified] No DOCX exists under the project. No downstream Evaluation, Release, Manuscript, Synthesis, or Credits artifact was found.

### Three main PDFs

PDF contents were not opened. The current project has exactly three main PDFs:

| File | SHA-256 |
|---|---|
| `00_sources/papers/source-anie-202101775.pdf` | `e46e223ce57082f251ac5e4f4c531bffd2ca67c60ceb3d560eb3bd7d9ccbc0de` |
| `00_sources/papers/source-acscatal-2c03805.pdf` | `4f6f251a1007f5c634fa41344fdc711809770f3b3b4f19281b8a11c98c54d0ab` |
| `00_sources/papers/source-jacs-3c06936.pdf` | `e230d8cd40af56115fa710bfa3775da7c85634ce2253f55eb4a4a4b8cc13bb97` |

Three imported SI PDFs also exist under `00_sources/supplements/imported/`; they were only counted/hashed, not opened.

### Three Chemical ZIPs

ZIP contents were not opened or unpacked. The current project has exactly three Chemical exports:

| File | SHA-256 |
|---|---|
| `00_sources/chemical_mineru_exports/01_ANIE_chemical-paper.zip` | `dcb4a84f96f05462b8c5557b71d265b2da89fe00e08fe1151bb1ef9748e550e5` |
| `00_sources/chemical_mineru_exports/02_ACS_Catalysis_chemical-paper.zip` | `917f67a78d51ca3be7b0fdf70fd14a2fbb35df614064cff10ed9af047c6e6eb9` |
| `00_sources/chemical_mineru_exports/03_JACS_chemical-paper.zip` | `3af8cb6db39f3abdb1559f89e2ef6a4b1ba4eefe1a81c01b5cc97f43f6404403` |

### SI registry and source-coverage conflict

- [Verified] `00_sources/si_resource_registry.json` SHA-256: `10f1ad346ca6b2fa3a16c57463f160b2ba3f216bf6dc0827f62298fdbc218f6e`.
- [Verified] The registry has three core studies, `core_si_required=true`, `raw_scientific_authority=CANDIDATE_ONLY`, `human_chemical_review_required_for_scientific_use=true`, and `integration_status=RAW_INPUT_REGISTERED_NOT_SOURCE_TRUTH_PARSED`.
- [Verified] `00_sources/source_coverage.json` SHA-256: `3802bbd3ae7dc4270ebf86c1c323ee17e90359281f07c88f4c9de9f35533f426`.
- [Verified] All three rows still say `si_policy=NOT_REQUIRED` and `study_status=READY`, despite the registered SI input. That is the concrete external-project drift this code patch addresses for future bootstrap; this task does not edit the external JSON.
- [Verified] `00_sources/manual_import_receipt.json` reports three imported archive results, but this is an import receipt, not a researcher-approved scientific projection.

### Chemical state and candidate staging

- [Verified] Chemical state files contain molecule arrays of `125`, `109`, and `75`, totaling the declared denominator `309`, and one raw import record per study. Their molecule objects do not contain a formal `CONFIRMED` / `AI_PROVISIONAL` / `BLOCKED` projection field.
- [Inferred] The current Chemical lane is raw candidate/unresolved material, consistent with the registry's `CANDIDATE_ONLY` policy; it is not a scientific decision ledger.
- [Verified] Candidate-only JSON files exist under `01_evidence/chemical_completion_candidates/`; no project-scoped authority receipt or formal three-state projection artifact was found.
- [Verified] `.dual-parse-staging/chemical-paper/` contains three consumed receipts; those receipts prove staging consumption only and do not prove researcher approval.
- [Reported] The requested snapshot label is `210 raw candidate / 99 unresolved`. Those numbers are intentionally recorded as raw candidate/unresolved counts, not as formal state counts; this audit did not open the Chemical ZIPs to recompute them.

The distinction is therefore:

```text
raw candidate (210) + unresolved gap (99)
        != authoritative projection (CONFIRMED / AI_PROVISIONAL / BLOCKED)
        != researcher decision
        != downstream Evidence or release
```

No candidate was upgraded, and no external project state was written.

## Runtime drift

### Port 63822

- [Verified at audit and final probe] PID `135420`, cwd `/home/kenqia/my_folder/review-writer/.worktrees/e2r-chemical-integration`.
- [Verified] command lane uses `--review-root /home/kenqia/my_folder/review-projects`.
- [Verified] `GET /api/projects` returned `[]`.
- [Verified] No project-scoped authority receipt was exposed or found for the fresh v3 project.

### Port 8765

- [Verified at initial audit] PID `42007`, cwd `/home/kenqia/my_folder/review-writer/.worktrees/e2r-dual-integration`.
- [Verified at initial audit] command lane used `--review-root /home/kenqia/my_folder`, which was broader than the target project and therefore not a project-scoped authority boundary.
- [Verified at initial audit] `GET /api/projects` advertised 4 projects; the payload had no authority-receipt field.
- [Verified at final probe] Port 8765 returned `connection refused`; the process/listener was no longer present. The lifecycle cause is `Unknown`; no stop or restart command was issued by this task.
- [Verified] No project-scoped authority receipt was exposed or found for the fresh v3 project.

No runtime was stopped or restarted. At the final probe 63822 remained alive and 8765 was unavailable. No protocol Restart 1/2, Playwright, Content Agent, or Researcher action was performed.

## Verification ledger

- [Verified] focused tests: `29 passed in 3.68s`.
- [Verified] `make smoke`: exit 0; project manifest tests, Python compilation, and helper `--help` checks passed.
- [Verified] `make quality-check`: exit 0; repository safety check, quality validator tests, and fixture validation passed.
- [Verified] `git diff --check` exited 0; final `git status --short --branch` is clean on `codex/e2r-canonicalization`. The final canonical commit identity and parent are recorded from `git rev-parse` in the handoff report.

## Residual blockers and non-claims

- The external fresh project remains inconsistent (`SI registry registered` versus `source_coverage NOT_REQUIRED/READY`) and was intentionally not repaired here.
- Neither runtime has a project-scoped authority receipt; 63822 is empty and 8765 is over-broad.
- No formal three-state projection, researcher decision, downstream Evidence, Synthesis, Manuscript, DOCX, Release, Evaluation, or Credits artifact is claimed.
- `FRESH_DUAL_PROJECT_READY=NOT_CLAIMED`.
- `PLAYWRIGHT_NOT_STARTED`.
- `PROTOCOL_RESTARTS_NOT_STARTED`.
