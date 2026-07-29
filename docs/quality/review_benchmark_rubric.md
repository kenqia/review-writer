# Review benchmark rubric

This rubric is an internal regression and gap-analysis contract. It does not certify scientific correctness, expert acceptance, journal suitability, or publication readiness. Every score requires a human or Agent rationale, remains subject to researcher review, and cannot override a Hard Fail.

## 100-point rubric

| Dimension | Points | Required judgment |
| --- | ---: | --- |
| Scope and question value | 10 | The scope is explicit, bounded, timely, and organized around a consequential review question rather than a paper list. |
| Source Set coverage | 15 | Inclusion, exclusion, source types, important counterexamples, and known coverage gaps are explicit. |
| Evidence fidelity | 20 | Claims bind the correct source and locator; chemistry, conditions, epistemic type, mechanism strength, and uncertainty are preserved. |
| Synthesis and critique | 20 | Cross-study comparisons follow declared axes and address conflicts, counterevidence, limitations, boundary conditions, and alternative interpretations. |
| Structure and narrative | 15 | Sections answer the Review Contract in a coherent progression, with calibrated conclusions and a useful outlook. |
| Figure information value | 10 | Source figures and researcher-owned synthesis figures carry defined scientific tasks; labels, units, captions, claims, and text agree. |
| Citation and traceability | 10 | Scientific prose traces to approved evidence and references entail the claims they support. |

Scores below 80 fail the internal regression threshold. Scores from 80 through 89 are acceptable only as internal drafts requiring revision. Scores from 90 through 100 are benchmark-level internal drafts. A score is never a substitute for scientific review.

Chemistry correctness and epistemic classification are emphasized under evidence fidelity. Counterexamples and limitations are emphasized under synthesis and critique. Figure-to-text agreement and caption information content are emphasized under figure information value.

## Hard Fail projection

The internal and expert projections share these Hard Fails: wrong source binding; unread supporting body or SI; unapproved high-risk claims; stale approval; fabricated conditions, mechanisms, facts, or consensus; disagreement between disk, API, UI, and release state; unsourced scientific claims; repackaged legacy drafts; and system-generated or system-composed scientific synthesis figures.

A clearly marked, lineage-complete synthesis figure placeholder is reported as `SYNTHESIS_FIGURE_PENDING` but is not an internal-draft Hard Fail. For `EXPERT_REVIEWED_RELEASE`, that same condition is a Hard Fail until the researcher supplies the required figure and its scientific acceptance is recorded.

## Standard corpus comparison

The external corpus binding must validate all manifest hashes, 14/14 MinerU jobs, eight benchmark reviews, six writing/artwork guides, and one ChemDraw stylesheet. The repository stores only identifiers and validation code, not benchmark prose.

Comparison prompts cover section proportions, comparison/critique paragraph density, Source Figure density, caption information content, citation density, and claim traceability. These observations inform the item rationales; they do not automatically assign a scientific score.
