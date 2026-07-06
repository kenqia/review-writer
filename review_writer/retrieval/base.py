from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class RetrievalQuery:
    query: str
    top_k: int = 5
    filters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalResult:
    provider_name: str
    status: str
    items: list[dict[str, Any]] = field(default_factory=list)
    content: str = ""
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class RetrievalProvider(Protocol):
    provider_name: str

    def search(self, query: RetrievalQuery) -> RetrievalResult:
        ...
