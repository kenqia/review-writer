from __future__ import annotations

from pathlib import Path

from .base import ImageRequest, ImageResult


class SourceFigureAdapter:
    provider_name = "source_figure"

    def resolve(self, request: ImageRequest) -> ImageResult:
        if not request.source_path:
            return ImageResult(
                provider_name=self.provider_name,
                status="error",
                warnings=["source_path is required for source figure resolution"],
                metadata={"network": "not_used"},
            )
        path = Path(request.source_path)
        if not path.exists():
            return ImageResult(
                provider_name=self.provider_name,
                status="error",
                warnings=[f"source figure not found: {path}"],
                metadata={"network": "not_used", "source_path": str(path)},
            )
        return ImageResult(
            provider_name=self.provider_name,
            status="ok",
            items=[{"source_path": str(path), "size": path.stat().st_size}],
            warnings=["source figure resolved locally; no upload was performed"],
            metadata={"network": "not_used"},
        )

    def generate(self, request: ImageRequest) -> ImageResult:
        return self.resolve(request)
