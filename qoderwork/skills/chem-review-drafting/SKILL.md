---
name: chem-review-drafting
description: Use when drafting chemistry review sections from an approved blueprint, selecting source-grounded figures, redrawing figures, and merging a first draft.
---

# Chem Review Drafting

## Scope

Run or guide:

```text
section drafting
retrieval-backed single-section generation
source figure inventory
figure candidate selection
figure redraw
first draft merge
```

## Rules

- Resolve `<REPO_ROOT>`, `<REVIEW_ROOT>`, `<PAPER_LIBRARY>`, and
  `<OUTPUT_ROOT>` from user input before running commands; never guess personal
  paths.
- If required paths are missing, ask for them or use a repo-relative demo.
- Every paragraph that cites papers should expose a stable paragraph ID.
- Figure candidates must point to real source figures, tables, schemes, or an explicit no-figure reason.
- Redrawn figures need human verification against source figures.
- Source-image placeholders are not final publication figures.
- Default to offline smoke; do not call real LLM or image generation APIs unless explicitly approved.
- Do not read, print, or persist real credentials.
- Preserve human checkpoints after section drafting, figure selection, figure redraw, and first draft merge.
- Do not skip the downstream quality gate; unresolved figure or citation risks must be carried into final audit.
- Retrieval-backed generation defaults to `retrieval_mode=offline_fixture` and `generation_provider=offline`.
- Retrieval-backed generation may produce only one short section, must cite only evidence-pack paper ids, and must stop at `Sections: ready_for_human_review`.
- Do not continue from retrieval-backed generation into Figures, Draft, Final, or Export without a separate human checkpoint.

## Deterministic Scripts

Prefer repo scripts for repeatable drafting and figure inventory work:

```text
make smoke
make quality-check
python skills/review-section-drafting-figure-picking/scripts/build_paper_figure_inventory.py
python skills/review-section-drafting-figure-picking/scripts/select_initial_figure_candidates.py
python skills/review-draft-merge-polish/scripts/init_first_draft.py
python scripts/demo/run_retrieval_generation_pilot.py --retrieval-mode offline_fixture --generation-provider offline
python scripts/validators/validate_grounded_section.py
```

## Outputs

```text
02_section_drafting/
03_figure_redraw/
04_first_draft/
```
