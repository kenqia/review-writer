from __future__ import annotations

import re


def confidence_from_titles(query: str, matched_title: str) -> float:
    query_tokens = set(tokens(query))
    title_tokens = set(tokens(matched_title))
    if not query_tokens or not title_tokens:
        return 0.0
    overlap = len(query_tokens & title_tokens)
    union = len(query_tokens | title_tokens)
    return overlap / union if union else 0.0


def tokens(text: str) -> list[str]:
    stop = {"the", "and", "of", "in", "with", "for", "from", "via", "type", "into", "onto", "a", "an"}
    return [token for token in re.findall(r"[a-z0-9]+", text.lower()) if len(token) > 2 and token not in stop]
