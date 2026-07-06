---
name: chem-review-planning
description: Use when turning a chemistry review topic and local paper metadata into discovery results, literature matrix, outline options, and section blueprint for human approval.
---

# Chem Review Planning

## Scope

Run or guide:

```text
topic discovery
literature matrix
outline options
section blueprint
```

## Rules

- Local retrieval uses the fixed structured chemistry tags before any external search.
- External retrieval is optional and must degrade to local-only mode.
- The selected outline and section blueprint require human approval before drafting.
- Blueprint entries must map sections to claims, paper IDs, comparison axes, and figure/table needs.
- Default to offline smoke; do not call real retrieval or LLM APIs unless explicitly approved.
- Do not read, print, or persist real credentials.
- Preserve the human checkpoint after discovery, literature matrix, outline selection, and section blueprint.
- Carry figure/table needs forward; if no figures are available, mark that state explicitly for the quality gate.

## Deterministic Scripts

Prefer repo scripts and JSON artifacts for repeatable planning state:

```text
make smoke
make quality-check
python skills/review-topic-paper-discovery/scripts/discover.py
python skills/review-section-blueprint/scripts/init_section_blueprint.py
```

## Outputs

```text
00_discovery/
01_matrix_outline/
```
