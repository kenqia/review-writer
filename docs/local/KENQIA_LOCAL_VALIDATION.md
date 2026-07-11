# Kenqia Local Validation

This file records one developer's local validation environment.
It is not a default path guide for general users.
Do not copy these paths into generic skills or product docs.

## Environment

- WSL repo path used for validation: `/home/kenqia/my_folder/review-writer`
- QoderWork CN skill install dir used for validation:
  `/mnt/c/Users/26960/.qoderworkcn/skills`
- Previous incorrect Windows Desktop path:
  `C:\Users\26960\Desktop\review-writer`
- Real-lite output root used during validation:
  `/tmp/review_writer_real_lite_e2e`

## QoderWork CN Validation Notes

- The five `chem-review-*` skills were installed into the QoderWork CN skill
  directory above during local validation.
- QoderWork CN successfully loaded `chem-review-orchestrator`.
- QoderWork CN could access the real WSL repo through:

```powershell
wsl.exe --cd /home/kenqia/my_folder/review-writer bash -lc "make smoke && make quality-check && make qoderwork-check && git status --short"
```

## Desktop Wrong Path Incident

The path below was used once during an incorrect smoke attempt and represented
an empty or wrong project root:

```text
C:\Users\26960\Desktop\review-writer
```

Do not use that path as a generic `review_root`.

## Codex-Simulated QoderWork Manual Flow Result

During local validation, Codex simulated the QoderWork manual-flow questions
against the real-lite output root. This is not proof of QoderWork CN product UX;
actual QoderWork CN product-run validation still requires the user to run the
installed skills inside QoderWork CN and paste the resulting transcript.

The real-lite output root contained 9 checkpoints:

```text
Library -> Discovery -> Matrix -> Blueprint -> Sections -> Figures -> Draft -> Final -> Export
```

The run summary recorded no network, PDF read, Qwen call, MinerU API call, or
upload.

## Actual QoderWork CN Product-Run Validation

Phase 5i was later run inside QoderWork CN itself, using the installed
`chem-review-orchestrator` skill and the WSL repository path above.

Key result:

- QoderWork CN loaded `chem-review-orchestrator`.
- QoderWork CN identified the WSL repository.
- The runtime HEAD was `7b9a8af docs: add merge readiness audit`, before the
  Phase 5h reality-audit commit.
- The 11 offline gates passed.
- The real-lite mock/demo output can be inspected at Export.
- A true production review should still start at Library until the paper
  library, MinerU parse outputs, metadata, and human checks are trustworthy.

The detailed product-run record lives in:

```text
docs/qoderwork/actual_qoderwork_cn_product_run_validation.md
```
