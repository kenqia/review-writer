from __future__ import annotations

from .base import ProviderResult, TextGenerationRequest


class OpenAICompatibleProvider:
    provider_name = "alibaba_openai_compatible"

    def __init__(
        self,
        *,
        base_url: str = "",
        model: str = "qwen-plus",
        api_key_env: str = "DASHSCOPE_API_KEY",
        allow_network: bool = False,
        enabled: bool = False,
    ) -> None:
        self.base_url = base_url
        self.model = model
        self.api_key_env = api_key_env
        self.allow_network = allow_network
        self.enabled = enabled

    def generate_text(self, request: TextGenerationRequest) -> ProviderResult:
        if not self.enabled:
            return self._disabled("provider disabled by config")
        if not self.allow_network:
            return self._disabled("network calls disabled; pass allow_network=True only after explicit user approval")
        return ProviderResult(
            provider_name=self.provider_name,
            status="disabled",
            warnings=["real OpenAI-compatible call is not implemented in Phase 4a"],
            metadata={"base_url": self.base_url, "model": self.model, "api_key_env": self.api_key_env},
        )

    def _disabled(self, reason: str) -> ProviderResult:
        return ProviderResult(
            provider_name=self.provider_name,
            status="disabled",
            warnings=[reason],
            metadata={
                "model": self.model,
                "base_url": self.base_url,
                "api_key_env": self.api_key_env,
                "network": "not_used",
            },
        )
