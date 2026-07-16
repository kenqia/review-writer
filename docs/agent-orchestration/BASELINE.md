# ORCH-001 Baseline

Recorded at `2026-07-16T01:25:34+08:00` before orchestration changes.

## review-writer

- Git repository: yes
- Branch: `feat/phase8b-grounded-review-integration`
- HEAD: `fbf17251ead3e7edf7bf09881d24ef9da4ac95ad`
- Existing orchestration files in allowed paths: none
- Existing business changes, preserved and outside this task:
  - `Makefile` (overlaps only at the entry file; existing content must be preserved)
  - `review_writer/delivery/finished_review.py`
  - `scripts/delivery/run_finished_mini_review.py`
  - `skills/review-export-docx/scripts/md2docx.py`
  - `tests/test_finished_review_delivery.py`
  - `docs/handoff/PRODUCT_LEADER_CURRENT.md`
  - `tests/test_docx_product_quality.py`
  - `tests/test_fresh_source_syntax.py`

Entry-file SHA-256 before modification:

```text
4d142ff89a982cde456a5c06a4f328b3f0d2554c8cc59225496379dd7e391c7b  AGENTS.md
48de7cf6dad24703c1fdcbd45081b75e43920d4ecf41470ff333d13a6668ebf8  Makefile
0e1fe176513ab29619ee20705c7545c4c273b2f8c973ce25e3e7b17b5d965908  .gitignore
```

## Generic Project Template

- Git repository: no
- Branch: not applicable
- HEAD: not applicable
- Existing orchestration files in allowed paths: none

Entry-file SHA-256 before modification:

```text
03311d1a3401e368712ccd6aa805381fb0e047f8f980fae9f8b6062d32620bdd  AGENTS.md
e9e2d3f2d4797c4f185a38d8d44ea74b8e074c2d1102d42a7721e1dbb101c92e  Makefile
2be03588b014d20c996b8d668324cb2179e2e5cd9f75ebc20f69dadc41560d25  .gitignore
387de5e161a1f32fc27a5a58667c32e54ac8a2fcb9a389a5d9424c133be98e33  .codex/config.toml
```

Local backups exist in each directory at `.agent-orchestration-runs/20260716T012534+0800/backups/` and match the hashes above.
