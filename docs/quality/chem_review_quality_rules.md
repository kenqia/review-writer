# Chemistry Review Quality Rules

This document defines the first quality gate for chemistry review manuscripts.
The initial implementation is intentionally offline: static and heuristic checks
run locally, while chemistry judgment and title/content alignment are emitted as
explicit LLM or human review tasks.

## CRQ001 Source Figure Traceability

- rule_id: `CRQ001_SOURCE_FIGURE_TRACEABILITY`
- 规则说明: Every figure used in the manuscript must resolve to an existing Markdown image path; source figure manifest paths should also resolve.
- 为什么重要: Chemistry figures can change scientific meaning. Missing or ambiguous source figures block human verification.
- 输入文件: `final_draft.md`, `figure_manifest.json`
- static check 能否做: yes
- heuristic check 能否做: yes
- LLM judge 是否需要: optional, for claim-to-figure fit
- 人工审核是否需要: yes, compare source and redrawn figures
- fail 示例: `![Scheme 1](figures/missing.png)`
- pass 示例: `![Scheme 1](figures/scheme_01.png)` where the file exists
- 输出字段: `image_count`, `missing_images`, `missing_manifest_paths`, `human_review_tasks`
- 推荐 workflow 阶段: section drafting, figure redraw, final audit
- 严重级别: error

## CRQ002 Citation Callout Order

- rule_id: `CRQ002_CITATION_CALLOUT_ORDER`
- 规则说明: Numeric citation groups must be ascending; reversed ranges are invalid.
- 为什么重要: Out-of-order citations make reference verification unreliable and violate common chemistry journal style.
- 输入文件: `final_draft.md`
- static check 能否做: yes
- heuristic check 能否做: no
- LLM judge 是否需要: no
- 人工审核是否需要: spot check
- fail 示例: `[3,1]`, `[5, 2, 4]`, `[7-5]`
- pass 示例: `[1,3]`, `[2, 4, 7]`, `[5-7]`
- 输出字段: `bad_callouts`
- 推荐 workflow 阶段: merge, final audit
- 严重级别: error

## CRQ003 Duplicate Captions

- rule_id: `CRQ003_DUPLICATE_CAPTIONS`
- 规则说明: Figure captions should not be duplicated after normalizing labels, spacing, and punctuation.
- 为什么重要: Duplicate captions often indicate copied placeholder text or figure insertion mistakes.
- 输入文件: `final_draft.md`
- static check 能否做: yes
- heuristic check 能否做: yes
- LLM judge 是否需要: optional for semantic duplicates
- 人工审核是否需要: spot check
- fail 示例: two captions both reading `Figure 1. Reaction scope.`
- pass 示例: captions describe distinct schemes or figures
- 输出字段: `duplicate_captions`, `similar_captions`
- 推荐 workflow 阶段: figure redraw, merge, final audit
- 严重级别: error

## CRQ004 Chemical Formula Typography Risk

- rule_id: `CRQ004_CHEMICAL_FORMULA_TYPOGRAPHY`
- 规则说明: Plain-text formulas such as `CO2`, `H2O`, `Fe3+`, and `SO4 2-` are flagged for human review.
- 为什么重要: Subscripts, superscripts, charges, and isotope labels must be typographically correct in final chemistry prose.
- 输入文件: `final_draft.md`
- static check 能否做: partial
- heuristic check 能否做: yes
- LLM judge 是否需要: optional
- 人工审核是否需要: yes
- fail 示例: not automatically failed in Phase 2
- pass 示例: `CO_2`, `H_2O`, `Fe^{3+}`, or journal-approved typography
- 输出字段: `formula_risks`, `human_review_tasks`
- 推荐 workflow 阶段: final audit, DOCX/PDF export
- 严重级别: warning

## CRQ005 Reference Format Completeness

- rule_id: `CRQ005_REFERENCE_FORMAT_COMPLETENESS`
- 规则说明: References files should be non-empty and contain basic author/year/DOI-like signals where available.
- 为什么重要: Weak references make citation and publication checks brittle.
- 输入文件: `references.md` or `references.bib`
- static check 能否做: partial
- heuristic check 能否做: yes
- LLM judge 是否需要: optional for ACS formatting
- 人工审核是否需要: yes for final target style
- fail 示例: empty references file
- pass 示例: numbered reference or BibTeX entry with authors and year
- 输出字段: `reference_entry_count`, `reference_warnings`
- 推荐 workflow 阶段: merge, final audit, export
- 严重级别: warning

## CRQ006 Section Heading Fit

- rule_id: `CRQ006_SECTION_HEADING_FIT`
- 规则说明: Section headings should summarize the section thesis and match section body content.
- 为什么重要: Chemistry reviews need navigable conceptual structure, not generic or mismatched headings.
- 输入文件: `final_draft.md`, section body previews
- static check 能否做: no, except empty/duplicate heading checks
- heuristic check 能否做: limited
- LLM judge 是否需要: yes
- 人工审核是否需要: yes
- fail 示例: heading `Applications` for a section about catalyst optimization only
- pass 示例: `Copper-catalyzed propargylic substitution toward axially chiral allenes`
- 输出字段: `llm_judge_tasks`
- 推荐 workflow 阶段: blueprint, final audit
- 严重级别: warning

## CRQ007 Review Title Fit

- rule_id: `CRQ007_REVIEW_TITLE_FIT`
- 规则说明: The review title should summarize the topic, scope, and central chemical axis.
- 为什么重要: A vague or mismatched title misrepresents the review and hurts discoverability.
- 输入文件: `final_draft.md`
- static check 能否做: no, except title extraction
- heuristic check 能否做: limited
- LLM judge 是否需要: yes
- 人工审核是否需要: yes
- fail 示例: `Recent Advances` with no chemistry scope
- pass 示例: `Catalytic allene synthesis from propargylic alcohols and derivatives`
- 输出字段: `llm_judge_tasks`
- 推荐 workflow 阶段: final audit
- 严重级别: warning

## CRQ008 Prompt And Workflow Leakage

- rule_id: `CRQ008_PROMPT_WORKFLOW_LEAKAGE`
- 规则说明: Draft prose must not contain skill, prompt, workflow, or editor instructions.
- 为什么重要: Leaked instructions make the manuscript unusable and expose internal process text.
- 输入文件: `final_draft.md`
- static check 能否做: yes
- heuristic check 能否做: yes
- LLM judge 是否需要: optional
- 人工审核是否需要: spot check
- fail 示例: `本节应当...`, `请生成...`, `不要直接出现在正文`
- pass 示例: manuscript prose without process instructions
- 输出字段: `leakage_hits`
- 推荐 workflow 阶段: merge, final audit
- 严重级别: error for direct instructions; warning for ambiguous process terms
