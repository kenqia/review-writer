from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from .base import MetadataQuery, MetadataSourceResult
from .utils import confidence_from_titles


class OpenAlexSource:
    source_name = "openalex"

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
                warnings=["disabled: pass --allow-network-metadata to query OpenAlex"],
            )
        params = urllib.parse.urlencode({"search": query.query, "per-page": "1"})
        url = f"https://api.openalex.org/works?{params}"
        try:
            data = fetch_json(url, timeout_seconds)
            results = data.get("results") or []
            if not results:
                return MetadataSourceResult(source_name=self.source_name, query=query.query, warnings=["no match"])
            item = results[0]
            title = str(item.get("display_name") or "")
            authors = [
                str(authorship.get("author", {}).get("display_name") or "")
                for authorship in (item.get("authorships") or [])[:12]
                if authorship.get("author", {}).get("display_name")
            ]
            venue = str((item.get("primary_location") or {}).get("source", {}).get("display_name") or "")
            doi = str(item.get("doi") or "").replace("https://doi.org/", "")
            return MetadataSourceResult(
                source_name=self.source_name,
                query=query.query,
                matched_title=title,
                authors=authors,
                year=item.get("publication_year"),
                venue=venue,
                doi=doi,
                url=str(item.get("id") or ""),
                confidence=confidence_from_titles(query.query, title),
            )
        except Exception as exc:  # noqa: BLE001
            return MetadataSourceResult(source_name=self.source_name, query=query.query, warnings=[f"network_warning: {type(exc).__name__}"])


def fetch_json(url: str, timeout_seconds: float) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "review-writer-metadata-check/0.1"})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - fixed public metadata endpoint.
        return json.loads(response.read().decode("utf-8", errors="replace"))
