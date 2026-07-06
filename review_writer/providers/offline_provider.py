from __future__ import annotations

import hashlib

from .base import ProviderResult, TextGenerationRequest


class OfflineProvider:
    provider_name = "offline"

    def generate_text(self, request: TextGenerationRequest) -> ProviderResult:
        joined = "\n".join(message.get("content", "") for message in request.messages)
        digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]
        return ProviderResult(
            provider_name=self.provider_name,
            status="ok",
            content=f"offline mock response [{digest}]",
            warnings=["offline provider used; no network call was made"],
            metadata={
                "model": request.model,
                "message_count": len(request.messages),
                "deterministic_digest": digest,
                "network": "not_used",
            },
        )
