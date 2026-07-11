from __future__ import annotations

from .base import RetrievalQuery, RetrievalResult


class BailianRetrieval:
    provider_name = "bailian_retrieval"

    def __init__(self, *, enabled: bool = False, knowledge_base_id_env: str = "BAILIAN_KNOWLEDGE_BASE_ID", allow_network: bool = False) -> None:
        self.enabled = enabled
        self.knowledge_base_id_env = knowledge_base_id_env
        self.allow_network = allow_network

    def search(self, query: RetrievalQuery) -> RetrievalResult:
        if not self.enabled:
            reason = "Bailian retrieval disabled by config"
        elif not self.allow_network:
            reason = "Bailian network calls disabled; explicit user approval required"
        else:
            reason = "Bailian retrieval placeholder does not create knowledge bases or call APIs in Phase 4a"
        return RetrievalResult(
            provider_name=self.provider_name,
            status="disabled",
            warnings=[reason],
            metadata={
                "knowledge_base_id_env": self.knowledge_base_id_env,
                "network": "not_used",
                "uploads": "not_used",
            },
        )
