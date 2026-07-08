# Actual QoderWork CN Product-Run Validation

## Goal

Record the first actual QoderWork CN product-environment validation for the
review-writer `chem-review-orchestrator` skill. This record is distinct from the
earlier Codex-simulated QoderWork manual-flow QA.

## Environment

- Runtime: QoderWork CN
- Skill: `chem-review-orchestrator`
- Repository access: WSL repo
- Repository path used by QoderWork CN: `<REPO_ROOT_IN_WSL>`
- Kenqia's concrete local path is recorded only in
  `docs/local/KENQIA_LOCAL_VALIDATION.md`.
- Branch at validation time: `feat/chem-review-quality-gates`
- HEAD at validation time: `7b9a8af docs: add merge readiness audit`

This validation was run before the Phase 5h reality-audit commit. A later
lightweight read-only revalidation can be run if the owner wants QoderWork CN to
verify the latest head as well.

## Gates Passed

QoderWork CN loaded `chem-review-orchestrator`, identified the WSL repository,
and reported these gates passing:

```text
make smoke
make quality-check
make qoderwork-check
make provider-check
make qwen-hello-dry-run
make judge-check
make tiny-e2e-check
make real-lite-preflight
make real-lite-e2e-check
make dashboard-real-lite-check
make eval-baseline-check
```

`git status --short` was empty before and after the run.

## Real-Lite Output Root

The product run found the real-lite output root:

```text
/tmp/review_writer_real_lite_e2e
```

These key artifacts existed:

```text
checkpoint_log.json
run_summary.json
05_final_audit/quality_report.json
04_first_draft/final_draft.md
03_figure_redraw/figure_manifest.json
```

## Checkpoint Result

- Checkpoint count: 9
- Every checkpoint had `human_review_required=True`
- In the mock/demo E2E output, all 9 checkpoints were `approved_mock`

Checkpoint interpretation:

- For the already generated mock/demo output, the flow can be inspected at the
  Export checkpoint because the demo artifacts already exist.
- For a true production review with non-simulated papers, the workflow should
  stop at the Library checkpoint until the paper library, MinerU parse outputs,
  metadata, and human audit are trustworthy.

## Eval And Safety Result

- Eval score: `100.0`
- `run_summary` safety fields were all `not_used`:
  - `network`
  - `pdf_read`
  - `qwen`
  - `mineru_api`
  - `upload`

The product run did not read PDFs, call APIs, upload files, print credentials,
or modify the repository.

## Conclusion

QoderWork CN product environment can load and execute the review-writer skill
pack against the WSL repository for offline real-lite QA.

This does not mean the real-lite output is scientifically reliable. Phase 5h
shows that real-lite data is trusted for engineering regression and demo flow,
but not for final scientific quality.

## Limits

- The validation HEAD was `7b9a8af`, not the latest Phase 5h HEAD.
- The validation does not prove full `chem_papers` readiness.
- The validation does not prove citation-accurate review quality.
- The validation does not create or validate a Bailian knowledge base.

## Next Steps

- Phase 5j: build a clean 3-paper human-verified dataset with corrected
  metadata, source excerpts, figure candidates, and human approval notes.
- Phase 6a: Bailian RAG no-upload preflight only after or alongside the clean
  dataset work, without uploading papers or creating a knowledge base.
