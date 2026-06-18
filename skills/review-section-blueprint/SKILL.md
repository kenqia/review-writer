---
name: review-section-blueprint
description: Convert an approved chemistry review outline into a concrete section_blueprint.json before section drafting, using a selectable domain rule pack. Use after literature_matrix.json and selected_outline.md exist, and before review-section-drafting-figure-picking, when Codex needs section theses, review claims, major citation papers, paper roles, logic relationships, figure needs, and wording constraints for organic chemistry review prose. The current default rule pack is allenation, but future topic-specific rule packs can be added under references/rule_packs.
---

# Review Section Blueprint

Use this skill between `review-literature-matrix-outline` and `review-section-drafting-figure-picking`.

Its job is to turn an approved outline into a concrete writing blueprint. It should not draft final prose. It should make the argument plan specific enough that the next stage can generate paragraphs without falling back to one-paper-one-paragraph summaries.

## Inputs

Read:

```text
review-projects/<project_id>/01_matrix_outline/selected_outline.md
review-projects/<project_id>/01_matrix_outline/literature_matrix.json
review-projects/<project_id>/01_matrix_outline/paper_reading_notes.json
review-projects/<project_id>/01_matrix_outline/matrix_outline_report.md
```

Select and consult a domain rule pack before writing the blueprint. Start from:

```text
references/rule_packs.json
```

Use `default_rule_pack` unless the project topic clearly matches another installed pack or the user names a pack. The current default is:

```text
references/rule_packs/allenation/source-to-review-rules.md
references/rule_packs/allenation/rewrite-rubric.md
references/rule_packs/allenation/organic-review-style.md
```

Use rule-pack references as editorial rules only. Do not import their historical facts, catalyst examples, yields, citation numbers, or old review wording into the current review.

For large references, first inspect headings and read the sections relevant to:

```text
Contamination Boundary
Editorial Gates
Source Selection Signals
Source-To-Paragraph Mapping
Evidence Strength
Compression Rules
Quality Gate
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

## Process

Follow this order:

```text
1. Select the applicable rule pack from references/rule_packs.json.
2. Run the initializer script to create a draft section_blueprint.json from the approved outline and matrix.
3. Read the generated draft blueprint.
4. Use the matrix, reading notes, and selected rule-pack references to improve each section semantically.
5. Ensure each section contains review claims, not only section titles.
6. Assign major citation papers and roles for every claim.
7. Add logic relationships between papers: foundation, extension, contrast, limitation, mechanism_anchor, application, or boundary.
8. Add wording constraints that prevent overclaiming, mechanism inflation, vague scope claims, and paper-by-paper narration.
9. Write the final section_blueprint.json and section_writing_plan.md.
```

Initializer:

```bash
python /home/ps/review-writer/skills/review-section-blueprint/scripts/init_section_blueprint.py \
  --review-root /home/ps/review-writer \
  --project-id <project_id>
```

On Windows local paths, use the same script under `E:\review-writer\skills\review-section-blueprint\scripts\init_section_blueprint.py` with `--review-root E:\review-writer`.

## Blueprint Schema

Write outputs under:

```text
review-projects/<project_id>/01_matrix_outline/
```

Create:

```text
section_blueprint.json
section_writing_plan.md
```

`section_blueprint.json` must contain:

```json
{
  "project_id": "...",
  "review_topic": "...",
  "outline_source": "selected_outline.md",
  "rule_pack": "allenation",
  "rule_pack_path": "references/rule_packs/allenation",
  "sections": [
    {
      "section_id": "sec3",
      "title": "...",
      "section_thesis": "...",
      "review_problem": "...",
      "dominant_logic": "precursor_class|activation_mode|mechanistic_pathway|stereochemical_control|application|outlook",
      "major_papers": ["P002", "P004"],
      "review_claims": [
        {
          "claim_id": "sec3_c1",
          "claim": "...",
          "claim_type": "foundation|extension|contrast|limitation|mechanism|scope|outlook",
          "supporting_papers": [
            {
              "paper_id": "P002",
              "role": "foundational method|strategic extension|mechanistic anchor|boundary source|comparison source|application source",
              "use_for": ["activation mode", "scope boundary"],
              "caveat": "..."
            }
          ],
          "logic_relationship": "foundation_to_extension|contrast|limitation_repair|mechanistic_partition|scope_boundary|application_validation",
          "comparison_axes": ["substrate class", "activation mode"],
          "evidence_strength": "strong|moderate|weak|needs verification",
          "wording_constraints": ["..."]
        }
      ],
      "figure_or_table_needs": [
        {
          "type": "scheme|comparison table|mechanistic figure|scope map",
          "purpose": "...",
          "candidate_papers": ["P002"]
        }
      ],
      "section_transition": {
        "from_previous": "...",
        "to_next": "..."
      },
      "avoid_patterns": ["..."]
    }
  ]
}
```

## Quality Rules

Each section must have a thesis, not only a topic label.

Each non-introduction section should normally contain 2-5 review claims. A claim should be broad enough to synthesize multiple papers when the matrix supports it.

Do not require every claim to cite multiple papers. A one-paper claim is acceptable when the paper is a distinctive method, mechanism anchor, or boundary case. Mark that role explicitly.

Use `major_papers` for the section-level citation set, and `supporting_papers` inside each claim for the papers that actually support that claim.

Mechanism wording must distinguish:

```text
reported mechanism
proposed mechanism
control-supported mechanism
computationally supported mechanism
speculative rationale
```

Scope wording must name substrate/product classes. Avoid unbounded phrases such as "broad scope", "general method", or "highly efficient" unless the matrix supports the exact boundary.

`section_writing_plan.md` should be human-readable and compact. Use it for review before paragraph drafting.

## Adding Rule Packs

Add future domain wording libraries as sibling folders:

```text
references/rule_packs/<pack_name>/
  source-to-review-rules.md
  rewrite-rubric.md
  organic-review-style.md
```

Then register them in `references/rule_packs.json` with a short description and topic signals.

Keep cross-domain rules in the same three-file shape where possible:

```text
source-to-review-rules.md: source evidence to review argument logic
rewrite-rubric.md: paragraph quality and compression gates
organic-review-style.md: domain-specific terminology, mechanisms, scope, and prohibited wording
```

Do not mix topic facts into shared process rules. Domain rule packs define wording discipline and evidence handling, not factual content for a new review.

## Handoff

After this skill completes, `review-section-drafting-figure-picking` should read:

```text
review-projects/<project_id>/01_matrix_outline/section_blueprint.json
review-projects/<project_id>/01_matrix_outline/section_writing_plan.md
```

Then it should generate `section_tasks.json` from the blueprint instead of deriving tasks directly from the selected outline.
