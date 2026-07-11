# Phase 2 Quality Gates PR Notes

## PR Title

`feat: add chemistry review quality gates`

## Summary

This PR adds the first deterministic chemistry review quality gate for the
review-writer workflow, integrates it into the final audit stage, and exposes
the resulting quality report in the Final dashboard.

The implementation is intentionally offline-first. It does not call a real LLM,
DashScope, MinerU API, image generation API, or Alibaba provider adapter.

## Changed Files

- `.gitignore`
- `Makefile`
- `docs/migration/03_chem_review_quality_rules.md`
- `docs/migration/05_incremental_pr_plan.md`
- `docs/quality/chem_review_quality_rules.md`
- `scripts/install_qoderwork_skills.py`
- `scripts/validators/validate_review_quality.py`
- `skills/review-final-audit-release/SKILL.md`
- `skills/review-final-audit-release/scripts/final_audit_scan.py`
- `tests/fixtures/quality/*.md`
- `tests/test_quality_validators.py`
- `view/assets/dashboard/final.html`
- `view/assets/dashboard/review-ui.css`
- `view/serve_review_dashboard.py`

## Implemented Quality Rules

- `CRQ001_SOURCE_FIGURE_TRACEABILITY`: checks Markdown image paths and optional figure manifest source paths.
- `CRQ002_CITATION_CALLOUT_ORDER`: detects unordered numeric citation callouts such as `[3,1]`, `[5, 2, 4]`, and descending ranges such as `[7-5]`.
- `CRQ003_DUPLICATE_CAPTIONS`: detects exact or normalized duplicate `Figure X.` / `图 X` captions.
- `CRQ004_CHEMICAL_FORMULA_TYPOGRAPHY`: warns on suspicious plain-text chemistry notation such as `CO2`, `H2O`, `Fe3+`, and `SO4 2-`, then emits human review tasks.
- `CRQ005_REFERENCE_FORMAT_COMPLETENESS`: performs weak offline checks for empty references and basic author/year/DOI-like fields.
- `CRQ008_PROMPT_WORKFLOW_LEAKAGE`: flags likely prompt/workflow leakage such as `写作思路`, `本节应当`, `请生成`, `LLM judge`, `rule pack`, `blueprint`, and `workflow`.

## Placeholder Rules

- `CRQ006_SECTION_HEADING_FIT`: creates LLM judge tasks with title, section preview, and rubric. It does not pretend static checks can judge semantic fit.
- `CRQ007_REVIEW_TITLE_FIT`: creates LLM judge tasks with review title and body preview. It remains offline and does not call an LLM.

## Final Audit Integration

- `final_audit_scan.py` now invokes the offline validator against `final_draft.md`.
- The final audit stage writes:
  - `05_final_audit/quality_report.json`
  - `05_final_audit/quality_report.md`
- A validator `fail` status adds `quality_report_has_errors` to final audit blocking issues.
- A validator execution error adds `quality_report_scan_failed`.

## Final Dashboard Integration

- `/api/project/<project_id>/final` includes:
  - `quality_report`
  - `quality_report_md`
- `view/assets/dashboard/final.html` includes a `Quality Report` tab.
- The right-side Review Gate summarizes quality status, errors, warnings, LLM judge tasks, and human review tasks.
- The dashboard `/file?path=` endpoint is constrained to allowed roots so arbitrary absolute paths and path traversal are rejected.

## Validation Commands And Results

Fresh commands run during Phase 2 QA:

```bash
make smoke
make quality-check
python tests/test_quality_validators.py
```

Observed results:

- `make smoke`: passed.
- `make quality-check`: passed.
- `python tests/test_quality_validators.py`: passed.

Dashboard QA used an offline temporary review root:

```text
/tmp/review_writer_dashboard_qa_project
```

Observed results:

- Good final audit fixture generated `quality_report.json` and `quality_report.md` with status `pass`.
- Bad citation final audit fixture generated `quality_report.json` and `quality_report.md` with status `fail`.
- Bad citation final audit added `quality_report_has_errors` to blocking issues.
- Final dashboard payload includes both quality report JSON and Markdown.
- Final HTML includes the `Quality Report` tab and references the required fields.
- `/file?path=` returns `200` for files under `review_root`.
- `/file?path=/etc/passwd` returns `403`.
- `/file?path=../../../../etc/passwd` returns `403`.

## Risks And False Positive / False Negative Notes

- Citation parsing is numeric and Markdown-oriented; unusual citation styles may need later adapters.
- Duplicate caption detection is intentionally conservative and may miss paraphrased duplicates.
- Chemical formula checks are warnings only because plain text formulas can be acceptable in draft contexts.
- Reference checks are weak offline heuristics and should not replace bibliography tooling.
- Prompt/workflow leakage detection may warn on legitimate meta-discussion, but this is acceptable for a final manuscript gate.
- Heading and title semantic consistency remains a placeholder LLM judge task.

## Not Included

- No real LLM API calls.
- No DashScope calls.
- No MinerU API calls.
- No real image generation calls.
- No global QoderWork skill installation.
- No Alibaba provider adapter implementation.
- No PDF/LaTeX export implementation.
- No remote push or release.

## Recommended Next Stage

- Run QoderWork install dry-run and optional local install QA after explicit confirmation.
- Add Alibaba provider adapter skeletons for LLM, retrieval, and image generation without real keys.
- Add PDF/LaTeX export skeleton and offline smoke test.
- Design human review, local partial regeneration, and figure regeneration handoff points.
