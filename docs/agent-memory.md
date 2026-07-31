# Project Agent Memory

## 2026-07-31 — Keep Evidence-to-Release execution on the mainline

The dual-parse complete-loop run showed that valid P1 repairs can drift into an open-ended security review when each reviewer adds a new threat-model dimension and long gates are started before contracts stabilize.

Reusable operating rule:

1. Lock the current acceptance objective and its explicit stop line.
2. Close known P0/P1 and science-affecting P2 findings that directly violate the approved design.
3. Treat new non-scientific P2/P3 observations as residual risk unless they block the current end-to-end contract.
4. During repair, run only RED/GREEN and focused Owner tests.
5. Merge cross-Owner contracts once, add one combined regression, then run the prescribed long Task 9 gates once from the final clean revision.
6. Return immediately to a fresh non-overwriting project and a new checkpoint-1 browser run.
7. Never trade scientific truth for completion: unsupported SMILES stays blocked.

WSL test environment:

- Prefer `TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 python3 -m pytest ...` so pytest and `TemporaryDirectory` use native ext4 semantics instead of Windows DrvFS.
- Add `-s` only when capture/tempdir fails, not as a default product workaround.
- The `RequestsDependencyWarning` from the user shell is separate from pytest tempdir behavior; resolve it later in an isolated Python environment, not inside an active acceptance repair.
