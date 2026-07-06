"""Retrieval adapters."""

from .base import RetrievalQuery, RetrievalResult
from .local_library import LocalLibraryRetrieval
from .bailian_retrieval import BailianRetrieval

__all__ = ["RetrievalQuery", "RetrievalResult", "LocalLibraryRetrieval", "BailianRetrieval"]
