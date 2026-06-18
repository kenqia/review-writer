---
name: review-metadata-prep
description: Prepare a MinerU-parsed review-writing paper library for metadata review. Use when Codex needs to extract or validate paper metadata, keywords, abstracts, topic tags, and review-ready JSON files from PDF/Markdown/content_list outputs.
---

# Review Metadata Prep

Use this skill to implement the writing-preparation stage for a review-writing agent.

The skill assumes PDFs have already been parsed by MinerU and that a `mineru-outputs/manifest.json` exists.

## Workflow

1. Build paper metadata:

```bash
python /home/ps/review-writer/skills/review-metadata-prep/scripts/prepare_metadata.py \
  --review-root /home/ps/review-writer \
  --mineru-output /home/ps/review-writer/mineru-outputs \
  --pdf-root /home/ps/review-writer/source-paper/Progargylic \
  --discover-from-pdf-root \
  --append-registry
```

Use `--discover-from-pdf-root` when `manifest.json` only records the latest MinerU batch.
Use `--append-registry` when adding a new source-paper folder to an existing library.

2. Validate metadata:

```bash
python /home/ps/review-writer/skills/review-metadata-prep/scripts/validate_metadata.py \
  --review-root /home/ps/review-writer
```

3. Launch the local review dashboard from the separate view module when human audit is needed:

```bash
python /home/ps/review-writer/view/serve_review_dashboard.py \
  --review-root /home/ps/review-writer \
  --host 127.0.0.1 \
  --port 8765
```

Open:

```text
http://127.0.0.1:8765/library
```

## LLM Mode

By default, `prepare_metadata.py` uses deterministic rules so the pipeline can run without API credentials.

To enable LLM enhancement, set:

```bash
export OPENAI_API_KEY=...
```

Then run:

```bash
python /home/ps/review-writer/skills/review-metadata-prep/scripts/prepare_metadata.py \
  --review-root /home/ps/review-writer \
  --mineru-output /home/ps/review-writer/mineru-outputs \
  --pdf-root /home/ps/review-writer/source-paper/Progargylic \
  --use-llm \
  --model gpt-4.1-mini
```

LLM extraction is constrained to the first-page blocks, title/author/abstract candidates, and early Markdown context. Do not send full papers unless explicitly needed.

## Outputs

The skill writes:

```text
review-library/
  registry/
    papers.jsonl
  metadata/
    papers/<paper_id>.metadata.json
    metadata_validation.json
    metadata_validation.md
    extraction_prompts/
      metadata_extraction_system.md
      metadata_schema.json
```

## Metadata Rules

Each paper metadata JSON must include:

```text
paper_id
slug
title
authors
year
journal
doi
abstract
keywords
llm_tags
human_tags
topic_category
reaction_category
mechanism_category
application_category
source_paths
extraction
human_review
quality
```

Every extracted field should carry:

```text
value
source
confidence
human_checked
```

Use `human_tags` and `human_review` for human edits. Do not overwrite human-confirmed values automatically.

## Human Audit Dashboard

The dashboard code lives outside this skill:

```text
/home/ps/review-writer/view/
```

The dashboard is a local review console, not the source of truth. The source of truth is the JSON file on disk.

The dashboard should support:

```text
paper list
PDF preview
MinerU Markdown preview
metadata view
JSON editing
save metadata
mark reviewed
basic search by title, author, keyword, tag
```

## Validation

Run validation after extraction and after manual edits. Treat these as blocking issues:

```text
missing paper_id
missing title
missing source PDF
missing Markdown
missing metadata JSON
invalid JSON
```

Treat these as review warnings:

```text
missing abstract
missing authors
missing year
missing journal
missing DOI
empty keywords
empty tags
low confidence title
low confidence abstract
not human reviewed
```
