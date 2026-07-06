from __future__ import annotations

from .base import ProviderResult, TextGenerationRequest


class DashScopeProvider:
    provider_name = "dashscope_qwen"

    def __init__(self, *, model: str = "qwen-plus", enabled: bool = False, allow_network: bool = False) -> None:
        self.model = model
        self.enabled = enabled
        self.allow_network = allow_network

    def generate_text(self, request: TextGenerationRequest) -> ProviderResult:
        if not self.enabled:
            reason = "DashScope provider disabled by config"
        elif not self.allow_network:
            reason = "DashScope network calls disabled; explicit user approval required"
        else:
            reason = "real DashScope call is not implemented in Phase 4a"
        return ProviderResult(
            provider_name=self.provider_name,
            status="disabled",
            warnings=[reason],
            metadata={"model": self.model, "network": "not_used"},
        )
