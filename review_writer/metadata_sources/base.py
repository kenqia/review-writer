from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class MetadataQuery:
    candidate_id: str
    query: str
    filename: str = ""


@dataclass
class MetadataSourceResult:
    source_name: str
    query: str
    matched_title: str = ""
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str = ""
    doi: str = ""
    url: str = ""
    confidence: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "source_name": self.source_name,
            "query": self.query,
            "matched_title": self.matched_title,
            "authors": self.authors,
            "year": self.year,
            "venue": self.venue,
            "doi": self.doi,
            "url": self.url,
            "confidence": round(self.confidence, 3),
            "warnings": self.warnings,
        }


class MetadataSource(Protocol):
    source_name: str

    def search(self, query: MetadataQuery, *, allow_network: bool = False, timeout_seconds: float = 10.0) -> MetadataSourceResult:
        ...
