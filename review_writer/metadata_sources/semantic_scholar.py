from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from .base import MetadataQuery, MetadataSourceResult
from .utils import confidence_from_titles


class SemanticScholarSource:
    source_name = "semantic_scholar"

    def search(
        self,
        query: MetadataQuery,
        *,
        allow_network: bool = False,
        timeout_seconds: float = 10.0,
    ) -> MetadataSourceResult:
        if not allow_network:
            return MetadataSourceResult(
                source_name=self.source_name,
                query=query.query,
                warnings=["disabled: pass --allow-network-metadata to query Semantic Scholar"],
            )
        params = urllib.parse.urlencode({"query": query.query, "limit": "1", "fields": "title,authors,year,venue,externalIds,url"})
        url = f"https://api.semanticscholar.org/graph/v1/paper/search?{params}"
        try:
            data = fetch_json(url, timeout_seconds)
            rows = data.get("data") or []
            if not rows:
                return MetadataSourceResult(source_name=self.source_name, query=query.query, warnings=["no match"])
            item = rows[0]
            title = str(item.get("title") or "")
            external = item.get("externalIds") or {}
            return MetadataSourceResult(
                source_name=self.source_name,
                query=query.query,
                matched_title=title,
                authors=[str(author.get("name") or "") for author in (item.get("authors") or [])[:12] if author.get("name")],
                year=item.get("year"),
                venue=str(item.get("venue") or ""),
                doi=str(external.get("DOI") or ""),
                url=str(item.get("url") or ""),
                confidence=confidence_from_titles(query.query, title),
            )
        except Exception as exc:  # noqa: BLE001
            return MetadataSourceResult(source_name=self.source_name, query=query.query, warnings=[f"network_warning: {type(exc).__name__}"])


def fetch_json(url: str, timeout_seconds: float) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "review-writer-metadata-check/0.1"})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - fixed public metadata endpoint.
        return json.loads(response.read().decode("utf-8", errors="replace"))
