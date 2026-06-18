---
name: review-topic-paper-discovery
description: Create the first-stage review discovery workflow from a user topic and keywords. Use when Codex needs to expand/merge keywords, search local and optional web literature per keyword, rank papers by explainable relevance, and generate discovery JSON files for human deletion/confirmation of keywords and papers.
---

# Review Topic Paper Discovery

Use this skill for the first three steps of the review-writing workflow:

```text
1. User provides topic + keywords.
2. Codex expands and merges keywords.
3. Search local and optional web papers per keyword, rank by relevance.
4. Human checks keywords and paper relevance in a dashboard.
```

This skill replaces the old separate `review-topic-init`, `review-local-retrieval`, and `review-paper-selection` skills.

## Run Discovery

Local-only:

```bash
python /home/ps/review-writer/skills/review-topic-paper-discovery/scripts/discover.py \
  --review-root /home/ps/review-writer \
  --topic "Synthesis of polysubstituted allenes from propargylic alcohols and their derivatives" \
  --keywords "polysubstituted allenes, propargylic alcohols, propargylic acetates" \
  --project-id <optional-project-id>
```

With web search:

```bash
python /home/ps/review-writer/skills/review-topic-paper-discovery/scripts/discover.py \
  --review-root /home/ps/review-writer \
  --topic "..." \
  --keywords "..." \
  --web-search
```

## Launch Unified Dashboard

```bash
python /home/ps/review-writer/view/serve_review_dashboard.py \
  --review-root /home/ps/review-writer \
  --host 127.0.0.1 \
  --port 8765
```

Open:

```text
http://127.0.0.1:8765/discovery
```

The same server also provides the library-preparation audit page:

```text
http://127.0.0.1:8765/library
```

The root URL redirects to `/library`. Use the top navigation bar to switch between `Library Audit` and `Topic Discovery`.

The dashboard code lives in `/home/ps/review-writer/view/`, not inside this skill. This skill is responsible for discovery data generation; the view module is responsible for human check UI.

## Outputs

The skill writes:

```text
review-projects/<project_id>/00_discovery/
  topic_input.md
  keyword_set.draft.json
  local_results_by_keyword.json
  web_results_by_keyword.json
  combined_results_by_keyword.json
  selected_discovery_results.json
  human_check_state.json
  discovery_report.md
```

The dashboard edits `combined_results_by_keyword.json`, `selected_discovery_results.json`, and `human_check_state.json`.

## Ranking Principles

Local relevance ranking is explainable and deterministic:

```text
title match > human_tags > keywords > auto/llm tags > abstract > journal/year
```

The score is not only keyword frequency. It also rewards:

```text
topic terms co-occurring with the keyword
matches in high-value fields
recent papers
local parsed paper availability
```

Web search ranking uses title/snippet/topic overlap, year hints, DOI presence, and deduplication against local papers where possible.

## Human Check

The human should:

```text
delete irrelevant keywords
delete irrelevant papers under each keyword
open local PDF/Markdown/metadata for checking
open web result links
mark local papers as core_candidate, supporting_candidate, background, excluded, or uncertain
confirm discovery when keyword-paper mapping is acceptable
```

After confirmation, continue the review process from `selected_discovery_results.json`.
