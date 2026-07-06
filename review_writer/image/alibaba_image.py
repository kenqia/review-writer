from __future__ import annotations

from .base import ImageRequest, ImageResult


class AlibabaImageAdapter:
    provider_name = "alibaba_image"

    def __init__(self, *, enabled: bool = False, allow_network: bool = False, api_key_env: str = "DASHSCOPE_API_KEY") -> None:
        self.enabled = enabled
        self.allow_network = allow_network
        self.api_key_env = api_key_env

    def generate(self, request: ImageRequest) -> ImageResult:
        if not self.enabled:
            reason = "Alibaba image provider disabled by config"
        elif not self.allow_network:
            reason = "Alibaba image network calls disabled; explicit user approval required"
        else:
            reason = "Alibaba image placeholder does not generate or upload images in Phase 4a"
        return ImageResult(
            provider_name=self.provider_name,
            status="disabled",
            warnings=[reason],
            metadata={"api_key_env": self.api_key_env, "network": "not_used", "uploads": "not_used"},
        )
