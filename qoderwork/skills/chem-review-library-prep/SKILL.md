---
name: chem-review-library-prep
description: Use when preparing a local chemistry paper library from PDFs or MinerU outputs into review-writer metadata, with no committed secrets and a required human metadata audit.
---

# Chem Review Library Prep

## Scope

Prepare local paper data before review writing:

```text
PDF -> MinerU outputs -> metadata -> validation -> human audit
```

## Rules

- Read tokens only from environment variables or local untracked files.
- Do not commit PDF libraries, MinerU outputs, metadata, raw zips, or real tokens.
- If API access is unavailable, run deterministic metadata validation and report the missing API capability.
- Use the dashboard only as a local human review console; JSON files are the source of truth.
- Default to offline smoke and local-only checks; do not call real MinerU or LLM APIs unless the user explicitly provides project-scoped approval.
- Preserve the human metadata audit checkpoint before discovery or planning.
- Run the relevant quality gate or metadata validation before handing data to downstream skills.
- If a project has no usable figures, report the no-figure state explicitly instead of promising a figure-rich final review.

## Deterministic Scripts

Prefer repo scripts for repeatable work:

```text
make smoke
make quality-check
python skills/review-metadata-prep/scripts/prepare_metadata.py
python skills/review-metadata-prep/scripts/validate_metadata.py
python scripts/repo_safety_check.py
```

## Outputs

```text
review-library/registry/papers.jsonl
review-library/metadata/papers/*.metadata.json
review-library/metadata/metadata_validation.*
```
