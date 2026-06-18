---
name: review-section-drafting-figure-picking
description: Draft review sections from section_blueprint.json and the approved literature matrix, applying the selected review-section-blueprint domain rule pack during first-pass paragraph writing, then pick source-grounded figure or scheme candidates from original papers. Use after review-section-blueprint and before figure redraw or manuscript merge.
---

# Review Section Drafting Figure Picking

Use this skill after the literature matrix and outline have been reviewed.

This is a prompt-driven writing stage. Do not create a deterministic drafting script unless explicitly requested.

## Inputs

Read:

```text
review-projects/<project_id>/00_discovery/selected_discovery_results.json
review-projects/<project_id>/01_matrix_outline/literature_matrix.json
review-projects/<project_id>/01_matrix_outline/outline_options.md
review-projects/<project_id>/01_matrix_outline/matrix_outline_report.md
review-projects/<project_id>/01_matrix_outline/section_blueprint.json
review-projects/<project_id>/01_matrix_outline/section_writing_plan.md
/home/ps/review-writer/skills/review-section-blueprint/references/rule_packs.json
/home/ps/review-writer/template/综述模板写作方式与风格总结.md
```

Prefer the approved outline:

```text
review-projects/<project_id>/01_matrix_outline/selected_outline.md
```

If `selected_outline.md` is missing, stop for confirmation unless `matrix_outline_report.md` clearly recommends one outline and the user asked to continue.

If `section_blueprint.json` is missing, run `review-section-blueprint` first unless the user explicitly asks to skip the blueprint stage. Use the blueprint as the primary source for section theses, review claims, paper roles, comparison axes, wording constraints, and figure/table needs.

Use the rule pack recorded in `section_blueprint.json` as paragraph-writing rules during first-pass drafting, not only as post-generation polish. If `section_blueprint.json` does not record a rule pack, use `references/rule_packs.json` and its `default_rule_pack`.

The current default pack is:

```text
/home/ps/review-writer/skills/review-section-blueprint/references/rule_packs/allenation/source-to-review-rules.md
/home/ps/review-writer/skills/review-section-blueprint/references/rule_packs/allenation/rewrite-rubric.md
/home/ps/review-writer/skills/review-section-blueprint/references/rule_packs/allenation/organic-review-style.md
```

Rule-pack references are editorial rules only; do not use them as evidence for chemistry facts, yields, catalyst identities, historical claims, or citation content.

For large rule files, prioritize these sections:

```text
<selected rule pack>/source-to-review-rules.md:
  Contamination Boundary
  Editorial Gates
  Source Selection Signals
  Source-To-Paragraph Mapping
  Logical Transition Selection

<selected rule pack>/rewrite-rubric.md:
  Extraction Checklist
  Evidence Strength
  Compression Rules
  Paragraph Template
  Quality Gate

<selected rule pack>/organic-review-style.md:
  Voice And Diction
  Organic Chemistry Information To Preserve
  Mechanistic Precision
  Scope Compression
  Comparison And Practicality
  Organic Logic Transitions
  Selectivity And Stereochemistry
  Topic-specific rules, such as Allene And Propargylic Rules when using the allenation pack
  Prohibited Patterns
  One-Paragraph Organic Review Pattern
```

For each section, re-open relevant papers through:

```text
review-library/metadata/papers/<paper_id>.metadata.json
linked Markdown path
linked PDF path when selecting figures or checking ambiguous chemistry
```

## Process

First build the figure/table inventory:

```bash
python /home/ps/review-writer/skills/review-section-drafting-figure-picking/scripts/build_paper_figure_inventory.py \
  --review-root /home/ps/review-writer \
  --project-id <project_id>
```

Optionally create an initial machine-ranked candidate set before manual/Codex refinement:

```bash
python /home/ps/review-writer/skills/review-section-drafting-figure-picking/scripts/select_initial_figure_candidates.py \
  --review-root /home/ps/review-writer \
  --project-id <project_id>
```

Then read:

```text
review-projects/<project_id>/02_section_drafting/paper_figure_inventory.json
review-projects/<project_id>/02_section_drafting/paper_figure_candidates.json, if already initialized
review-projects/<project_id>/02_section_drafting/figure_candidates.json, if already initialized
```

Follow this order:

```text
1. Convert section_blueprint.json into explicit section tasks, preserving section thesis, review claims, paper roles, comparison axis, wording constraints, and figure/scheme/table needs.
2. Assign a constrained paper set to each section.
3. Read the relevant rule sections and translate them into local drafting constraints for the current section.
4. Re-read relevant Markdown for each section.
5. Inspect the PDF for figures, schemes, tables, and key chemical details.
6. For every relevant paper, identify its best overview/mechanism/method figure or record why no useful figure exists.
7. Draft section-ready prose directly from blueprint claims and source evidence.
8. Apply a paragraph-level rule check and revise before writing outputs.
9. Pick manuscript figure/scheme/table candidates tied to section claims.
10. Write all structured outputs.
```

The matrix is a guide, not a substitute for section-level rereading.

## Writing Rules

Use `section_blueprint.json` as the writing contract. Each section draft should cover its `section_thesis`, `review_problem`, `review_claims`, `major_papers`, `logic_relationship`, `comparison_axes`, and `wording_constraints` unless the reread source evidence forces a correction. If the source evidence conflicts with the blueprint, correct the draft and report the mismatch in `section_drafting_report.md`.

Prefer:

```text
one paragraph = one review claim, pattern, contrast, or argument
```

Do not default to:

```text
one paragraph = one paper summary
```

A paragraph may focus on one paper only when that paper contains a distinctive method, mechanism, or synthetic strategy.

For each paragraph, apply the rule references as follows:

```text
1. Open with the review claim, method identity, comparison problem, or transition logic.
2. Compress source evidence: reaction class, substrate/product class, catalyst or activation mode, selectivity, mechanism evidence, and limitation.
3. Use multiple papers when the claim is comparative or synthetic; use one paper only when its role is explicit.
4. Qualify mechanism according to the evidence level in the paper.
5. Qualify scope by naming substrate/product classes instead of using unbounded generality.
6. End with the paragraph's review function: advance, boundary, contrast, mechanism anchor, or application value.
```

Avoid:

```text
paper-by-paper abstract style
promotional wording copied from source papers
mechanism inflation
generic "broad scope" or "mild conditions" claims without boundaries
unsupported ranking between non-comparable conditions
old facts or examples imported from the rule references
```

When writing allene/propargylic sections, preserve distinctions among:

```text
propargylic alcohol, carbonate, acetate, ester, phosphate, bromide, sulfide, gem-dichloride
allene versus propargyl selectivity
SN2' substitution, allenylidene capture, radical addition/elimination, reductive coupling, carbonylation, protodenickelation
chirality transfer, catalyst-controlled enantioselectivity, stereospecificity, and selectivity erosion
```

## Figure Rules

Every figure candidate must be checked against the source paper.

Do not invent figures. Do not select decorative figures. Prefer method schemes, mechanism diagrams, catalytic cycles, reaction-scope summaries, mechanism proposals, and comparison tables.

Use the template review style as the target: schemes are part of the argument, not decoration. The drafted section should make clear why each selected scheme/figure is needed.

For every paper assigned to a section, inspect:

```text
Markdown image/table captions
content_list.json image/table blocks
PDF pages around candidate schemes/figures
```

Record the best paper-level candidate in `paper_figure_candidates.json`, even if it is not selected for the manuscript. If no useful figure exists, record `no_useful_figure_reason`.

Each major synthetic or mechanistic section should normally have at least one manuscript-ready figure/scheme candidate. If a section has none, explain the reason in `section_drafting_report.md`.

For each candidate, capture:

```text
section_id
paper_id
source_label
source_type
source_pdf
source_content_list when available
source_image_path
source_page_hint
source_caption_text
why_selected
what_it_shows
fits_paragraph_or_claim
recommended_action: reference|redraw|retable
manuscript_selected: true|false
resolution_status: ready|needs_source_resolution|no_useful_figure
needs_human_check
```

For `recommended_action: redraw` or `reference`, `source_image_path` should be a real local image path whenever MinerU extracted the source image. If it cannot be resolved, set `resolution_status: needs_source_resolution` and explain what Codex checked.

## Outputs

Write all outputs under:

```text
review-projects/<project_id>/02_section_drafting/
```

Create:

```text
section_tasks.json
section_drafts.json
section_drafts.md
paper_figure_inventory.json
paper_figure_candidates.json
figure_candidates.json
section_drafting_report.md
```

Required content:

```text
section_tasks.json: section goals, core question, core argument, blueprint claims, comparison axis, allowed papers, must-cover points, avoid points, transition role, wording constraints, figure/scheme/table need
section_drafts.json: section-ready prose, used papers, used blueprint claims, paragraph rule checks, open questions
section_drafts.md: human-readable draft
paper_figure_inventory.json: MinerU image/table inventory generated by the script
paper_figure_candidates.json: best overview/mechanism/method figure found for each relevant paper, or no-useful-figure reason
figure_candidates.json: source-grounded figures/schemes/tables for redraw or reuse
section_drafting_report.md: outline and blueprint basis, drafted sections, reused papers, rule-reference sections used, weak evidence, blueprint mismatches, overlap risks, figure candidates
```

## Human Check

Stop after this stage in an interactive workflow.

The human should check:

```text
whether sections follow the approved outline
whether paragraphs synthesize rather than list papers
whether figure candidates really support the drafted claims
which figures should be redrawn, retabled, reused, or removed
```

Suggested continuation message:

```text
已确认章节草稿和图表候选，进入图片统一风格重绘阶段。
```
