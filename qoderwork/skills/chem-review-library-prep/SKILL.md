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

## Outputs

```text
review-library/registry/papers.jsonl
review-library/metadata/papers/*.metadata.json
review-library/metadata/metadata_validation.*
```
