---
name: review-final-audit-release
description: Perform final content audit and format audit on a merged review draft, verify claims against available evidence, fix manuscript-level issues, and produce the final draft plus audit reports. Use after review-draft-merge-polish and human approval of the first draft.
---

# Review Final Audit Release

Use this skill after `review-draft-merge-polish` has produced `04_first_draft/first_draft.md` and the human has approved the draft structure.

This is the final quality gate. It should not create new arguments casually. Its job is to check, correct, and release a defensible final manuscript.

## Required Inputs

Read:

```text
review-projects/<project_id>/04_first_draft/first_draft.md
review-projects/<project_id>/04_first_draft/merge_report.md
review-projects/<project_id>/04_first_draft/remaining_issues.md
review-projects/<project_id>/01_matrix_outline/literature_matrix.json
review-projects/<project_id>/01_matrix_outline/selected_outline.md
review-projects/<project_id>/02_section_drafting/section_tasks.json
review-projects/<project_id>/02_section_drafting/section_drafts.json
review-projects/<project_id>/02_section_drafting/figure_candidates.json
```

If figures were redrawn, also read:

```text
review-projects/<project_id>/03_figure_redraw/redrawn_figure_manifest.json
review-projects/<project_id>/03_figure_redraw/figure_redraw_report.md
```

For high-risk claims, reopen the relevant local paper metadata and Markdown/PDF listed in the matrix or section outputs.

## Process

Follow this order:

```text
1. Run the deterministic format scan script.
2. Read the first draft and upstream evidence files.
3. Audit content: evidence support, citation fit, chemistry accuracy, overclaiming, missing caveats, outline fit.
4. Audit review quality: synthesis vs paper listing, comparison axes, scheme/table integration, organic-review style.
5. Audit format: headings, references, figure/table callouts, abbreviations, placeholders, unresolved notes.
6. Revise the manuscript into a final draft.
7. Write content and format audit reports.
8. Write a release report with remaining risks.
```

Do not hide unresolved problems. If a claim cannot be verified from local evidence, either weaken it, remove it, or list it in `final_remaining_issues.md`.

## Content Audit Rules

Check for:

```text
claim has support from the cited paper or matrix entry
citation number or paper_id matches the claim
reaction class, catalyst, substrate, product, regioselectivity, stereoselectivity, and mechanism are not distorted
non-comparable yields or conditions are not directly ranked
speculative mechanisms are described as tentative
paragraphs synthesize patterns rather than listing one paper after another
each major section follows the approved outline purpose
figures or schemes support the surrounding claims
```

For organic synthesis reviews, give special attention to:

```text
named reaction type and activation mode
substrate scope boundaries
leaving group and propargylic/allenyl regioselectivity
metal catalyst and ligand identity
enantioselectivity or stereospecificity claims
mechanistic evidence vs author proposal
```

## Format Audit Rules

Check for:

```text
heading hierarchy
duplicate or empty headings
reference callouts and reference list consistency
figure/table numbering and callouts
caption completeness
source figure placeholders that still need redraw or permission review
undefined abbreviations
placeholder text such as TODO, verification needed, citation needed
broken Markdown links or image paths
front matter style inappropriate for a chemistry review
```

## Script

Run:

```bash
python /home/ps/review-writer/skills/review-final-audit-release/scripts/final_audit_scan.py \
  --review-root /home/ps/review-writer \
  --project-id <project_id>
```

The script writes `format_scan.json` and `format_scan.md`. Codex must then perform the semantic content audit and final revision.

## Outputs

Write outputs under:

```text
review-projects/<project_id>/05_final_audit/
```

Create:

```text
format_scan.json
format_scan.md
content_audit_report.md
format_audit_report.md
final_draft.md
final_remaining_issues.md
release_report.md
```

## Output Requirements

`content_audit_report.md` must include:

```text
major content fixes made
claims weakened or removed
citation or paper_id mismatches found
sections still weak in evidence
chemistry-specific risks
```

`format_audit_report.md` must include:

```text
format scan summary
manual format fixes made
remaining formatting issues
```

`final_draft.md` must be the clean manuscript without inline TODOs, verification notes, or editor-only comments.

Do not treat source-paper image placeholders as final publication figures. If `figure_insertion_report.json` has `mode: source_candidates`, either replace them with redrawn figures or list this as a blocking remaining issue.

`final_remaining_issues.md` must be short and explicit. If there are no known remaining issues, say so.

`release_report.md` must state:

```text
source first draft
upstream evidence files used
final draft path
whether release is ready for human export
residual risks
```

## Human Check Point

Stop after this stage.

The human should check:

```text
whether the final manuscript is scientifically acceptable
whether any remaining risk requires returning to an earlier stage
whether figures and references are ready for export to the target format
```

Suggested completion message:

```text
终稿检查已完成，请人工最终确认 final_draft.md 和 release_report.md。
```
