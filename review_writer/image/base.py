from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ImageRequest:
    prompt: str = ""
    source_path: str = ""
    constraints: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ImageResult:
    provider_name: str
    status: str
    content: str = ""
    items: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class ImageProvider(Protocol):
    provider_name: str

    def generate(self, request: ImageRequest) -> ImageResult:
        ...
