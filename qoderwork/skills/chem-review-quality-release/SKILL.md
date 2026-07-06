---
name: chem-review-quality-release
description: Use when validating chemistry review quality, checking citations, figures, captions, formulas, headings, prompt leakage, and exporting Markdown/DOCX/PDF-ready deliverables.
---

# Chem Review Quality Release

## Scope

Final quality gate and export coordination.

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

## Outputs

```text
05_final_audit/format_scan.json
05_final_audit/quality_scan.json
05_final_audit/final_draft.md
05_final_audit/release_report.md
05_final_audit/final_draft.docx
```
