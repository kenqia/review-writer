from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class TextGenerationRequest:
    messages: list[dict[str, str]]
    model: str = "offline"
    temperature: float = 0.0
    max_output_tokens: int = 900
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

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "provider_name": self.provider_name,
            "status": self.status,
            "content_present": bool(self.content),
            "content_chars": len(self.content),
            "items": self.items,
            "warnings": self.warnings,
            "metadata": self.metadata,
        }


class TextProvider(Protocol):
    provider_name: str

    def generate_text(self, request: TextGenerationRequest) -> ProviderResult:
        ...
