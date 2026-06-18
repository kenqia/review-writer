---
name: review-literature-matrix-outline
description: Read the selected papers from the discovery stage, extract topic-relevant evidence, build a structured literature matrix, and propose 2-3 detailed review outlines. Use after discovery results have been human-checked and before section drafting.
---

# Review Literature Matrix Outline

Use this skill after `review-topic-paper-discovery` has produced a selected paper set.

This is a prompt-driven reading and synthesis stage. Do not replace it with a deterministic extraction script unless explicitly requested.

## Inputs

Read first:

```text
review-projects/<project_id>/00_discovery/selected_discovery_results.json
review-projects/<project_id>/00_discovery/topic_input.md
```

For each selected local paper, inspect:

```text
review-library/metadata/papers/<paper_id>.metadata.json
the linked Markdown path
the linked PDF path when figures, schemes, tables, or ambiguous chemistry matter
```

Use metadata only for navigation. Use Markdown for reading and PDF as the truth source for layout and figures.

Before generating outlines, consult these local guides:

```text
/home/ps/review-writer/综述写作流程指导.md
/home/ps/review-writer/template/综述模板写作方式与风格总结.md
```

Use them as constraints for outline design and organic-review style. Do not copy long passages from them.

## Process

Follow this order:

```text
1. Identify selected papers that are actually relevant to the review topic.
2. Read each useful paper with the review topic in mind.
3. Extract concrete evidence: reaction/system, substrate class, catalyst/condition, mechanism, scope pattern, limitation, useful figure/table.
4. Downgrade or exclude papers that are not useful after reading.
5. Build the literature matrix.
6. Generate 2-3 genuinely different outline options.
7. Recommend one option and explain the reason briefly.
```

Do not summarize entire papers when only part of the paper is relevant.

## Outline Design Rules

Each outline option must choose one primary organizing logic, such as:

```text
development line
substrate or precursor class
reaction type
catalyst or activation mode
mechanistic pathway
synthetic application
```

Do not mix several organizing logics at the same hierarchy level unless the option explicitly explains why this is necessary.

Each option in `outline_options.md` must include:

```text
outline type and organizing logic
why this structure fits the topic and matrix
main risk or weakness
detailed section plan
recommended figure/scheme/table plan
```

For every major section, include:

```text
section title
section purpose or core question
core papers
main comparison axis
must-cover evidence
candidate scheme/figure/table need
known limitations or uncertainty
transition to the next section
```

Avoid title-list outlines. The outline must be a chapter task framework that can directly drive `review-section-drafting-figure-picking`.

For organic synthesis reviews, prefer scheme-driven organization. Avoid vague headings such as “privileged platform” or “synthetic potential” unless they are paired with concrete reaction classes, substrate families, or scheme plans.

## Outputs

Write all outputs under:

```text
review-projects/<project_id>/01_matrix_outline/
```

Create:

```text
paper_reading_notes.json
literature_matrix.json
literature_matrix.csv
outline_options.md
matrix_outline_report.md
```

Required content:

```text
paper_reading_notes.json: one evidence note per paper, including relevance, role, key evidence, limitations, useful sections, and figure/table candidates
literature_matrix.json: structured paper comparison for later agents
literature_matrix.csv: flat comparison table for human review
outline_options.md: 2-3 outline options grounded in the matrix
matrix_outline_report.md: short summary of read papers, core papers, downgraded papers, dominant evidence patterns, recommended outline, and unresolved checks
```

Use stable values where possible:

```text
review_topic_relevance: high|medium|low
role_after_reading: core|supporting|background|exclude
```

## Quality Rules

Prefer synthesis-ready findings over paper-by-paper storytelling.

Record limitations and non-comparable experimental conditions instead of smoothing them over.

Surface uncertain mechanisms as uncertainty, not as established fact.

## Human Check

Stop after this stage in an interactive workflow.

The human should check:

```text
whether any core paper was misread or wrongly downgraded
whether the matrix missed an important comparison axis
which outline option should be used
```

Preferred continuation artifact:

```text
review-projects/<project_id>/01_matrix_outline/selected_outline.md
```

Suggested continuation message:

```text
已确认文献矩阵和大纲方案，进入章节任务书与正文写作阶段。
```
