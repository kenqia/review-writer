from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class TextGenerationRequest:
    messages: list[dict[str, str]]
    model: str = "offline"
    temperature: float = 0.0
    response_format: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderResult:
    provider_name: str
    status: str
    content: str = ""
    items: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class TextProvider(Protocol):
    provider_name: str

    def generate_text(self, request: TextGenerationRequest) -> ProviderResult:
        ...
