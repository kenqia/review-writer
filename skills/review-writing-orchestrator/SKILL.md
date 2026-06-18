---
name: review-writing-orchestrator
description: Orchestrate the implemented review-writing workflow by inspecting a review project, deciding the next required skill, checking stage outputs, and pausing at human review nodes. Use when Codex needs to start, resume, or explain the current state of a review project under /home/ps/review-writer/review-projects.
---

# Review Writing Orchestrator

Use this as the main entry skill for the review-writing workflow after the paper library has already been prepared.

Writing-preparation skills are separate:

```text
mineru-precise-parse-review-writer
review-metadata-prep
```

Run those only when PDFs still need MinerU parsing or metadata still needs preparation.

## Main Workflow

Route the project through these stage skills:

```text
1. review-topic-paper-discovery
2. review-literature-matrix-outline
3. review-section-blueprint
4. review-section-drafting-figure-picking
5. review-figure-style-redraw
6. review-draft-merge-polish
7. review-final-audit-release
```

The workflow stops after final content/format audit and final draft release.

## Status First

For an existing project, always inspect status first:

```bash
python /home/ps/review-writer/skills/review-writing-orchestrator/scripts/project_status.py \
  --review-root /home/ps/review-writer \
  --project-id <project_id>
```

Use JSON output when another script or a concise machine-readable summary is useful:

```bash
python /home/ps/review-writer/skills/review-writing-orchestrator/scripts/project_status.py \
  --review-root /home/ps/review-writer \
  --project-id <project_id> \
  --json
```

Then report:

```text
completed stage
blocking human check, if any
next skill
missing files that explain why the next skill is needed
```

## New Project

For a new review task, require:

```text
review topic
seed keywords
optional project_id
```

Then invoke:

```text
review-topic-paper-discovery
```

That stage creates:

```text
review-projects/<project_id>/00_discovery/
```

## Human Check Rules

Pause after each major stage when the workflow is interactive:

```text
00_discovery: check keywords and selected papers at http://127.0.0.1:8765/discovery
01_matrix_outline: choose or edit the outline, preferably by creating selected_outline.md
01_matrix_outline/section_blueprint: check section theses, claims, paper roles, comparison logic, and wording constraints
02_section_drafting: check section drafts and figure_candidates.json
03_figure_redraw: compare redrawn figures with original sources
04_first_draft: check first_draft.md at http://127.0.0.1:8765/draft
05_final_audit: check final_draft.md and release_report.md before export
```

Do not silently move past these checks unless the user explicitly says to continue.

Accept short continuation messages such as:

```text
已确认 discovery，继续
已确认大纲，继续
已确认章节草稿和图表候选，继续
已确认重绘图片，继续
已确认初稿，继续
已确认终稿，完成
```

## Routing Rules

Use the next skill reported by `project_status.py` unless the user explicitly asks to rerun a stage.

If a required upstream file is missing, run the earlier missing stage instead of improvising.

After `selected_outline.md` exists, run `review-section-blueprint` before section drafting. Do not derive `section_tasks.json` directly from the outline when `section_blueprint.json` is missing, unless the user explicitly asks to skip the blueprint stage.

If figure redraw is intentionally skipped, say so clearly before moving to draft merge.

In the normal full workflow, do not skip figures. If `figure_candidates.json` is empty, source images cannot be resolved, or `redrawn_figure_manifest.json` contains no successful redrawn figures, return to `review-section-drafting-figure-picking` or `review-figure-style-redraw` instead of producing a text-only review.

Never claim a stage is complete unless its required output files exist.
