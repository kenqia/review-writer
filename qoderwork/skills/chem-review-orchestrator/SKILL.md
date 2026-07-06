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
provider_config
data_root
skip_figures=false
```

## Contract

1. Inspect project status before taking action.
2. Route to library prep, planning, drafting, quality release, or export.
3. Stop at every human checkpoint unless the user explicitly approves continuation.
4. Never silently produce a no-figure final review.
5. Prefer deterministic scripts for status, format gates, exports, and offline smoke checks.

## Human Checkpoints

```text
Library -> Discovery -> Matrix -> Blueprint -> Sections -> Figures -> Draft -> Final -> Export
```

## Outputs

Return the next required action, missing files, blocking issues, and human checkpoint instructions.
