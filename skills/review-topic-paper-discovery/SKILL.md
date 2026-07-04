---
name: review-topic-paper-discovery
description: Start a review project from a user topic, expand keywords against the eight LLM allene classification tags, retrieve local candidates from the metadata library, and optionally enrich with the hosted SciAtlas knowledge-graph search; produce 20-30 candidate papers for human check.
---

# Review Topic Paper Discovery

Goal: from the user review topic, select `20-30` local candidate papers and
keep an external evidence pool from SciAtlas for the matrix stage.

## Hard Rules

```text
Use only the 8 LLM structured tag categories for local retrieval:
product
substrate
catalyst_or_method
organometallic_partner
ligand_or_chiral_source
leaving_group
reaction_type
document_scope
```

Use `/home/ps/review-writer/allene_classification_rules.py` as the tag
vocabulary and synonym source. Do not rank local papers by metadata abstract.

External retrieval (both run in parallel when requested):

```text
SciAtlas /v1/search    enabled by --sciatlas-search (KG-grounded)
Crossref title search  enabled by --web-search       (open metadata)
none                   default when no flag is passed
```

When both flags are set, results are merged per keyword and de-duplicated by
DOI / URL / normalized title. Each merged record carries `sources` (e.g.
`['sciatlas']`, `['crossref']`, or `['sciatlas','crossref']`) and `source` is
the joined label for quick reading.

## Run

Local-only (default):

```bash
python /home/ps/review-writer/skills/review-topic-paper-discovery/scripts/discover.py \
  --review-root /home/ps/review-writer \
  --topic "<review topic>" \
  --keywords "<optional user keywords>" \
  --project-id <project_id>
```

Local + SciAtlas KG:

```bash
export SCIATLAS_API_BASE_URL=http://sciatlas.openkg.cn
export SCIATLAS_API_KEY=sciatlas_xxx     # required for /v1/search

python /home/ps/review-writer/skills/review-topic-paper-discovery/scripts/discover.py \
  --review-root /home/ps/review-writer \
  --topic "<review topic>" \
  --keywords "<optional user keywords>" \
  --project-id <project_id> \
  --sciatlas-search \
  --sciatlas-limit 8 \
  --sciatlas-time-range 2015-2025 \
  --sciatlas-domain "organic chemistry"
```

Both SciAtlas and Crossref together (results merged per keyword):

```bash
python /home/ps/review-writer/skills/review-topic-paper-discovery/scripts/discover.py \
  --review-root /home/ps/review-writer \
  --topic "<review topic>" \
  --project-id <project_id> \
  --sciatlas-search \
  --web-search
```

Crossref only (no SciAtlas token available):

```bash
python /home/ps/review-writer/skills/review-topic-paper-discovery/scripts/discover.py \
  --review-root /home/ps/review-writer \
  --topic "<review topic>" \
  --project-id <project_id> \
  --web-search
```

If the user gives no keywords, Codex must extract concise keywords from the
topic first. `keyword_set.draft.json` must not introduce extra local-retrieval
categories. Every keyword category should be one of the eight structured tag
categories above. If a topic token does not fit cleanly, classify it as
`reaction_type` and let human check remove it if needed.

## External Source: SciAtlas

SciAtlas is a hosted scientific knowledge graph. The skill calls
`POST /v1/search` once per expanded keyword with these defaults:

```text
retrieval_mode  hybrid
top_keywords    0
max_titles      0
max_refs        0
bias_exploration low
ranking_profile  precision
```

Per-keyword time range / domain hints come from CLI flags. Returned papers are
normalized into the same shape as Crossref results so the dashboard can render
both: `title, authors, year, journal, doi, url, abstract, score (0..1),
raw_score, source="sciatlas"`.

Auth:

```text
Authorization: Bearer $SCIATLAS_API_KEY
X-API-Key:     $SCIATLAS_API_KEY
```

Health check before searching:

```bash
curl -s http://sciatlas.openkg.cn/healthz
```

If SciAtlas health or auth fails, the script records the failure in
`web_results_by_keyword.json.status` and continues with local-only retrieval.

## Required Output

Write under:

```text
review-projects/<project_id>/00_discovery/
```

Required files:

```text
topic_input.md
keyword_set.draft.json
local_results_by_keyword.json
web_results_by_keyword.json
combined_results_by_keyword.json
selected_discovery_results.json
discovery_report.md
human_check_state.json
```

`web_results_by_keyword.json.source` is `sciatlas`, `crossref`, `sciatlas+crossref`, or `none`. Per-result rows carry a `sources` array so you can see which sources contributed.
`selected_discovery_results.json` should contain `20-30` kept local papers
when enough matches exist. External (SciAtlas/Crossref) papers go into
`web_papers`; they are a topic-coverage check pool only. They never enter
the local `paper_id` registry and the matrix stage may cite them only as
references without assigning a `paper_id`. If fewer than 20 local papers
are found, record why in `discovery_report.md`.

## Human Check

Stop after discovery. The human checks `/discovery`, deletes irrelevant
keywords/papers, and confirms the candidate set. SciAtlas papers are visible
in the same "external" panel as Crossref papers; deletions take effect for
both sources.
