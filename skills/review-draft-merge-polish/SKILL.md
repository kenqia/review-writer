---
name: review-draft-merge-polish
description: Merge separately drafted section files into one coherent first review draft and polish transitions, terminology, and figure placement.
---

# Review Draft Merge Polish

Goal: merge section files into one complete review draft.

## Inputs

```text
review-projects/<project_id>/01_matrix_outline/selected_outline.md
review-projects/<project_id>/01_matrix_outline/literature_matrix.json
review-projects/<project_id>/02_section_drafting/sections/*.md
review-projects/<project_id>/02_section_drafting/figure_candidates.json
review-projects/<project_id>/02_section_drafting/section_drafting_report.md
```

If available, also use:

```text
review-projects/<project_id>/03_figure_redraw/redrawn_figure_manifest.json
```

## Merge Rules

```text
Keep the selected outline order.
Merge all section files.
Polish transitions and terminology.
Preserve paper-to-paragraph and figure-to-paragraph links.
Do not delete caveats or no_figure_reason notes silently.
Do not invent new papers, claims, or figures.
```

## Hard Output Requirements

`first_draft.md` must satisfy all of:

```text
at least one ![](...) figure or scheme image,
  resolved against 04_first_draft/ (use redrawn images when available,
  or source-figure placeholders during early development; never zero figures
  unless 03_figure_redraw/skip_reason.md exists);
inline citation callouts using the `[n]` style for every claim that
  references a paper;
a final References section. Heading must be one of
  References / Reference List / Bibliography / Cited Literature / 参考文献.
  Items numbered 1., 2., ... or [1], [2], ... and the numbering must align
  with the inline `[n]` callouts.
```

The orchestrator status script will mark this stage incomplete with
`draft_has_no_figures`, `draft_has_no_citation_callouts`, or
`missing_references_section` whenever any of these are violated.

## Outputs

Write under:

```text
review-projects/<project_id>/04_first_draft/
```

Required files:

```text
first_draft.md
merge_report.md
remaining_issues.md
citations.json
```

`citations.json` aggregates every paragraph's `cited_paper_ids` into a single
ordered list per `[n]` slot. It is consumed by the final audit to cross-check
inline `[n]` callouts and the References section against `literature_matrix.json`.

Figure insertion is paragraph-anchored: read `target_paragraph_id` from
`02_section_drafting/figure_candidates.json` and insert each figure right after
its anchor paragraph. Do not fall back to heading-only matching when
`target_paragraph_id` exists.

`first_draft.md` must be a continuous review manuscript, not a list of section notes.

Stop after this stage for human check.
