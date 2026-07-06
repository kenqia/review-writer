---
name: chem-review-quality-release
description: Use when validating chemistry review quality, checking citations, figures, captions, formulas, headings, prompt leakage, and exporting Markdown/DOCX/PDF-ready deliverables.
---

# Chem Review Quality Release

## Scope

Final quality gate and export coordination.

Default to offline smoke and deterministic validation. Do not call real LLM,
DashScope, MinerU, retrieval, or image APIs unless the user explicitly approves
that provider step. Do not read, print, or persist real credentials.

## Required Checks

```text
reference callouts exist and match reference list
reference numbers appear in valid order
images resolve and are not unapproved placeholders
captions are non-duplicate
formula formatting risks are reported
headings match section content
prompt or workflow instructions do not leak into manuscript prose
```

## Human Checkpoints

- Stop for human review when the quality report contains errors, warnings, LLM judge tasks, human review tasks, unresolved placeholders, broken images, or no approved figures.
- Never silently produce a no-figure final review; require an explicit no-figure reason or approved figure plan.
- Do not export DOCX/PDF-ready deliverables until the final quality gate is pass or the user accepts documented residual risks.

## Deterministic Scripts

Prefer repo scripts and Makefile targets for release checks:

```text
make smoke
make quality-check
python skills/review-final-audit-release/scripts/final_audit_scan.py
python scripts/validators/validate_review_quality.py
```

## Outputs

```text
05_final_audit/format_scan.json
05_final_audit/quality_report.json
05_final_audit/quality_report.md
05_final_audit/final_draft.md
05_final_audit/release_report.md
05_final_audit/final_draft.docx
```
