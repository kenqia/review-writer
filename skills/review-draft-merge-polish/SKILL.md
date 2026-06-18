---
name: review-draft-merge-polish
description: Merge section-level drafts into a unified first review draft, normalize terminology and flow, and write merge reports for human review. Use when Codex needs to combine section drafting outputs into a readable first manuscript before final checking.
---

# Review Draft Merge Polish

Use this skill after section drafting has produced section-level draft outputs.

This stage should produce a unified first draft for one review project and a merge report that explains what was normalized or still remains risky.

This skill uses a small script to create stable project files and then relies on Codex to do the actual merge and polishing work.

## When To Use

Use this skill for the workflow stage:

```text
8. Merge the drafted sections.
9. Unify terminology, tone, and transitions.
10. Produce the first full draft.
```

Do not use this skill for:

```text
topic discovery
metadata extraction
literature matrix creation
source figure redraw
final content audit
final format audit
```

## Required Inputs

Read:

```text
review-projects/<project_id>/01_matrix_outline/literature_matrix.json
review-projects/<project_id>/01_matrix_outline/selected_outline.md
review-projects/<project_id>/02_section_drafting/section_tasks.json
review-projects/<project_id>/02_section_drafting/section_drafts.json
review-projects/<project_id>/02_section_drafting/section_drafts.md
review-projects/<project_id>/02_section_drafting/section_drafting_report.md
```

If figure redraw has already happened, also inspect:

```text
review-projects/<project_id>/03_figure_redraw/redrawn_figure_manifest.json
review-projects/<project_id>/03_figure_redraw/figure_redraw_report.md
```

If redrawn figures exist, the first draft must insert them in the relevant sections with Markdown image links and captions. Do not leave them only in `merge_report.md`.

## Core Goal

This stage does not do final scientific checking yet. Its job is to produce a coherent first draft.

Codex must:

```text
merge the section texts into one manuscript
insert approved redrawn figures/schemes at the claim or section they support
remove obvious duplication across sections
unify terminology and naming
improve transitions and chapter flow
keep claims aligned with section-level evidence
preserve unresolved issues explicitly instead of hiding them
```

## Merge Rules

When merging sections:

```text
do not silently delete important caveats
do not merge conflicting claims into false certainty
do not flatten all sections into the same voice if that loses technical precision
do not invent citations or figures that are not in the prior stage outputs
do not omit successfully redrawn figures unless there is a clear content reason recorded in remaining_issues.md
```

The output should read like a real first draft, not a stitched note file.

## Script

Run:

```bash
python /home/ps/review-writer/skills/review-draft-merge-polish/scripts/init_first_draft.py \
  --review-root /home/ps/review-writer \
  --project-id <project_id>
```

The script creates the output directory and a small draft bundle JSON from prior stages.

Then Codex should read the generated bundle and produce the final files listed below.

If a draft already exists and available figures need to be inserted, use:

```bash
python /home/ps/review-writer/skills/review-draft-merge-polish/scripts/insert_figures_into_draft.py \
  --review-root /home/ps/review-writer \
  --project-id <project_id>
```

This script prefers redrawn figures. If redraw failed but source candidates exist, it inserts source figures as explicit placeholders that still require redraw and permission checking before final release.

## Outputs

Write outputs under:

```text
review-projects/<project_id>/04_first_draft/
```

Create:

```text
draft_bundle.json
first_draft.md
figure_insertion_report.json, when figures were inserted by script
merge_report.md
remaining_issues.md
```

## Output Requirements

### `draft_bundle.json`

This is a machine-readable merge input summary written by the script. Codex may update it if needed, but should not remove useful provenance fields.

### `first_draft.md`

This is the unified manuscript draft.

It should:

```text
follow the approved outline order
read as one document
contain clear section and subsection headings
include Markdown image links for approved redrawn figures/schemes when available
include concise captions explaining the source paper and review function of each figure
use consistent terminology
preserve topic focus
be suitable for human review in the dashboard
```

### `merge_report.md`

This report must include:

```text
which source section files were merged
which terminology or naming was normalized
which overlaps were removed
which sections still feel weak or repetitive
which redrawn figures were inserted and where
which redrawn figures were not inserted and why
```

### `remaining_issues.md`

This file must list unresolved issues, such as:

```text
claims that still need human fact check
sections that may need more comparison
places where figure placement is still uncertain
redrawn figures that still need source verification or permission decisions
phrasing that may still be too paper-by-paper
```

## Human Check Point

This stage has a mandatory human review.

The human should check:

```text
whether the full draft still matches the intended outline
whether transitions and terminology are now coherent
whether any important caveat was lost during merging
whether the draft reads like a review rather than a paper list
```

Suggested continuation text:

```text
已确认初稿结构和行文，进入内容检查与终稿整理阶段。
```
