from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from .base import MetadataQuery, MetadataSourceResult
from .utils import confidence_from_titles


class CrossrefSource:
    source_name = "crossref"

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
                warnings=["disabled: pass --allow-network-metadata to query Crossref"],
            )
        params = urllib.parse.urlencode({"query.title": query.query, "rows": "1"})
        url = f"https://api.crossref.org/works?{params}"
        try:
            data = fetch_json(url, timeout_seconds)
            items = data.get("message", {}).get("items", [])
            if not items:
                return MetadataSourceResult(source_name=self.source_name, query=query.query, warnings=["no match"])
            item = items[0]
            title = first(item.get("title"))
            authors = format_authors(item.get("author") or [])
            year = extract_year(item)
            venue = first(item.get("container-title"))
            doi = str(item.get("DOI") or "").strip()
            match_url = str(item.get("URL") or "")
            return MetadataSourceResult(
                source_name=self.source_name,
                query=query.query,
                matched_title=title,
                authors=authors,
                year=year,
                venue=venue,
                doi=doi,
                url=match_url,
                confidence=confidence_from_titles(query.query, title),
            )
        except Exception as exc:  # noqa: BLE001 - external metadata failures are warnings, not crashes.
            return MetadataSourceResult(source_name=self.source_name, query=query.query, warnings=[f"network_warning: {type(exc).__name__}"])


def fetch_json(url: str, timeout_seconds: float) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "review-writer-metadata-check/0.1 (mailto:metadata@example.invalid)"})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - fixed public metadata endpoint.
        return json.loads(response.read().decode("utf-8", errors="replace"))


def first(value: Any) -> str:
    if isinstance(value, list) and value:
        return str(value[0])
    return str(value or "")


def format_authors(authors: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for author in authors[:12]:
        given = str(author.get("given") or "").strip()
        family = str(author.get("family") or "").strip()
        name = " ".join(part for part in [given, family] if part)
        if name:
            names.append(name)
    return names


def extract_year(item: dict[str, Any]) -> int | None:
    for key in ["published-print", "published-online", "published", "issued"]:
        parts = item.get(key, {}).get("date-parts")
        if parts and parts[0]:
            try:
                return int(parts[0][0])
            except (TypeError, ValueError):
                continue
    return None
