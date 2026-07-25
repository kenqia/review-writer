"""Bounded, manifest-driven source acquisition."""

from .public_corpus import ManifestError, acquire_manifest

__all__ = ["ManifestError", "acquire_manifest"]
