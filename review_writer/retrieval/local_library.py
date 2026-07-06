from __future__ import annotations

import json
from pathlib import Path

from .base import RetrievalQuery, RetrievalResult


class LocalLibraryRetrieval:
    provider_name = "local_library"

    def __init__(self, library_root: str | Path) -> None:
        self.library_root = Path(library_root)

    def search(self, query: RetrievalQuery) -> RetrievalResult:
        registry = self.library_root / "registry" / "papers.jsonl"
        if not registry.exists():
            return RetrievalResult(
                provider_name=self.provider_name,
                status="error",
                warnings=[f"registry not found: {registry}"],
                metadata={"network": "not_used", "library_root": str(self.library_root)},
            )
        items: list[dict[str, object]] = []
        needle = query.query.lower()
        try:
            for line in registry.read_text(encoding="utf-8", errors="ignore").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                haystack = " ".join(str(row.get(key, "")) for key in ("paper_id", "title", "abstract", "journal", "year")).lower()
                if not needle or needle in haystack:
                    items.append({k: row.get(k) for k in ("paper_id", "title", "year", "journal", "doi")})
                if len(items) >= query.top_k:
                    break
        except Exception as exc:
            return RetrievalResult(
                provider_name=self.provider_name,
                status="error",
                warnings=[f"failed to read local registry: {exc}"],
                metadata={"network": "not_used"},
            )
        return RetrievalResult(
            provider_name=self.provider_name,
            status="ok",
            items=items,
            warnings=["local registry search only; PDF or paper body was not read"],
            metadata={"network": "not_used", "top_k": query.top_k, "library_root": str(self.library_root)},
        )
