# Real-Lite Reality Audit

## Conclusion

The real-lite package is useful and trustworthy for engineering regression,
workflow demos, dashboard payload checks, and offline eval plumbing. It is not
trustworthy as final scientific review quality evidence.

The current inputs are trimmed excerpts plus pointer manifests. The current
outputs are compact skeleton drafts with placeholder figures. Passing E2E,
dashboard, and eval gates proves that the workflow wiring behaves as expected;
it does not prove citation accuracy, complete source coverage, or review-grade
chemical reasoning.

## Why E2E Pass Is Not Quality Pass

E2E checks verify artifact presence, checkpoint structure, quality-gate wiring,
and safety boundaries. They do not verify whether:

- metadata was human corrected
- paper authors and bibliographic fields are clean
- excerpts contain enough evidence for scientific claims
- source figures were actually selected or redrawn
- citations fully support the draft
- the final review is ready for scientific use

## Input Audit

The input audit reads only committed files under:

```text
demo_projects/real_lite_allene_review
```

It does not read PDFs, call MinerU, call Qwen, upload files, or access external
services.

Current conclusion:

- selected papers: 5
- trusted for engineering fixture: yes
- trusted for scientific quality: no
- DOI fields are mostly missing
- metadata is not human checked
- author fields show page-chrome pollution such as citation/read-online text
- excerpts are trimmed
- content lists and figures are pointer-only
- source paths are placeholders

Run:

```bash
make reality-audit-check
```

or:

```bash
python scripts/audit/audit_real_lite_inputs.py \
  --demo-root demo_projects/real_lite_allene_review \
  --output-json /tmp/real_lite_input_audit.json \
  --output-md /tmp/real_lite_input_audit.md \
  --strict
```

## Output Audit

The output audit reads the real-lite E2E output root and, if needed, regenerates
that output using the offline runner.

Current conclusion:

- engineering status: pass
- content quality status: needs human review
- trusted for demo: yes
- trusted for scientific quality: no
- literature matrix contains the five selected papers
- section blueprint and checkpoint log are structurally complete
- quality report and eval baseline pass
- final draft remains compact and skeleton-like
- figure manifest uses pointer/placeholder assets

Run:

```bash
python scripts/audit/audit_real_lite_outputs.py \
  --output-root /tmp/review_writer_real_lite_e2e \
  --input-demo-root demo_projects/real_lite_allene_review \
  --output-json /tmp/real_lite_output_audit.json \
  --output-md /tmp/real_lite_output_audit.md \
  --strict
```

## Trusted Uses

- engineering regression
- demo workflow smoke
- checkpoint artifact QA
- dashboard payload QA
- offline eval harness sanity check
- safety-boundary checks

## Not Trusted Uses

- final scientific review quality
- full RAG corpus readiness
- citation-accurate review evaluation
- figure-grounded final manuscript QA
- user-facing chemistry conclusion validation

## Next Actions

- Phase 5i: Actual QoderWork CN product-run validation. The user must run the
  installed skill inside QoderWork CN and paste the result.
- Phase 5j: Clean 3-paper human-verified dataset with corrected metadata,
  source excerpts, figure candidates, and human approval notes.
- Phase 6a: Bailian RAG no-upload preflight, without creating a knowledge base
  or uploading papers.
