# Phase 5h Reality Audit PR Notes

## Title Suggestion

Add real-lite data provenance and output quality audits

## Summary

Phase 5h adds explicit reality checks for the real-lite demo package. The goal
is to prevent a misleading conclusion where E2E, dashboard, and eval gates pass
but the project accidentally treats trimmed fixture data as scientific-quality
review evidence.

## Added Files

```text
scripts/audit/audit_real_lite_inputs.py
scripts/audit/audit_real_lite_outputs.py
tests/test_real_lite_input_audit.py
tests/test_real_lite_output_audit.py
docs/audit/real_lite_reality_audit.md
docs/pr/phase5h_reality_audit_pr.md
```

## Updated Files

```text
Makefile
docs/local/KENQIA_LOCAL_VALIDATION.md
docs/migration/05_incremental_pr_plan.md
docs/pr/phase5g_merge_readiness_audit.md
docs/qoderwork/qoderwork_cn_smoke_prompt.md
```

## Input Audit Conclusion

- Status: warn
- Selected papers: 5
- Trusted for engineering fixture: yes
- Trusted for scientific quality: no
- Main reasons: missing DOI values, not human checked, needs human check,
  author-field page-chrome pollution, trimmed excerpts, pointer-only
  content/figure assets, placeholder source paths.

## Output Audit Conclusion

- Engineering status: pass
- Content quality status: needs human review
- Trusted for demo: yes
- Trusted for scientific quality: no
- Main reasons: compact skeleton draft, pointer/placeholder figure manifest,
  fixture excerpt scope, and lack of human-verified source grounding.

## Safety Boundary

This phase does not:

- read PDFs
- read full `chem_papers`
- call MinerU
- call Qwen
- call Bailian
- upload files
- create a knowledge base
- call image generation

## Verification

```bash
make release-readiness-check
make reality-audit-check
python tests/test_real_lite_input_audit.py
python tests/test_real_lite_output_audit.py
```

## Follow-Ups

- Phase 5i: Actual QoderWork CN product-run validation. The user must run the
  installed skills inside QoderWork CN and paste the result.
- Phase 5j: Clean 3-paper human-verified dataset.
- Phase 6a: Bailian RAG no-upload preflight.
