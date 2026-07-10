---
name: chem-review-orchestrator
description: Use when orchestrating an AI Scientist chemistry review workflow from topic to audited deliverables, while preserving human checkpoints and offline smoke-test behavior.
---

# Chem Review Orchestrator

This is the QoderWork main entry for review-writer.

## Inputs

Required:

```text
project_id
review_root
topic
paper_library
output_format
```

Optional:

```text
provider_config / <PROVIDER_CONFIG>
data_root
skip_figures=false
retrieval_mode=offline_fixture
generation_provider=offline
section_id
section_title
max_evidence_items
```

Use placeholders in portable instructions:

```text
<REPO_ROOT>
<REVIEW_ROOT>
<PAPER_LIBRARY>
<OUTPUT_ROOT>
<QODERWORK_SKILLS_DIR>
```

## Contract

1. Inspect project status before taking action.
2. Route to library prep, planning, drafting, quality release, or export.
3. Stop at every human checkpoint unless the user explicitly approves continuation.
4. Never silently produce a no-figure final review.
5. Prefer deterministic scripts for status, format gates, exports, and offline smoke checks.
6. Do not read, print, or persist real credentials; report only missing or risky paths.
7. Do not call real LLM, DashScope, MinerU, retrieval, or image APIs by default.
8. Do not skip the final quality gate before release or export.
9. Resolve user-provided paths before running commands; never guess personal paths.
10. If required paths are missing, ask the user or use a repo-relative demo.
11. For retrieval-backed generation, default to `retrieval_mode=offline_fixture` and `generation_provider=offline`.
12. Retrieval-backed generation must stop at the `Sections` checkpoint after one section is marked `ready_for_human_review`.

Windows/WSL is only an optional runtime example:

```powershell
wsl.exe --cd <REPO_ROOT_IN_WSL> bash -lc "make smoke"
```

## Deterministic Scripts

Use repo scripts and Makefile targets before model-driven work:

```text
make smoke
make quality-check
make qoderwork-check
python skills/review-writing-orchestrator/scripts/project_status.py
python skills/review-final-audit-release/scripts/final_audit_scan.py
python scripts/validators/validate_review_quality.py
```

## Human Checkpoints

```text
Library -> Discovery -> Matrix -> Blueprint -> Sections -> Figures -> Draft -> Final -> Export
```

## Retrieval-backed Section Pilot

When `retrieval_mode` or `generation_provider` is supplied, run only this checkpointed path:

```text
retrieve evidence
-> build EvidencePack
-> generate one section
-> validate citations/evidence
-> ready_for_human_review
-> STOP
```

Allowed modes:

```text
retrieval_mode: offline_fixture | local | bailian
generation_provider: offline | qwen
section_id
section_title
max_evidence_items
```

Do not continue automatically into Figures, Draft, Final, or Export. Do not write local absolute paths into portable instructions.

## Outputs

Return the next required action, missing files, blocking issues, and human checkpoint instructions.
