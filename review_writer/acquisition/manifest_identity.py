"""Shared identity contract for public-corpus acquisition rows."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit


DOI_RE = re.compile(r"^10\.\d{4,9}/[-._;()/:a-z0-9]+$", re.IGNORECASE)
REQUIRED_FIELDS = frozenset({"download_id", "study_id", "document_role", "url", "target_path", "source_class"})
DOCUMENT_ROLES = frozenset({"MAIN", "SI"})
EXPECTED_FORMATS = frozenset({"PDF", "DOCX", "XLSX"})


class ManifestIdentityError(ValueError):
    """An acquisition row violates the shared identity contract."""


def normalize_doi(value: str | None) -> str | None:
    """Return a normalized DOI, rejecting decorated or malformed values."""

    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.lower().startswith("doi:"):
        raw = raw[4:].strip()
    elif "://" in raw:
        parsed = urlsplit(raw)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"doi.org", "dx.doi.org"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            return None
        raw = parsed.path.lstrip("/")
    elif any(marker in raw for marker in ("?", "#", "@")):
        return None
    raw = raw.lower().rstrip(".,; ")
    return raw if DOI_RE.fullmatch(raw) else None


def validate_acquisition_row(record: Any) -> dict[str, Any]:
    """Validate and normalize fields shared by acquisition and audits."""

    if not isinstance(record, dict) or not REQUIRED_FIELDS.issubset(record):
        raise ManifestIdentityError(
            "acquisition rows require download_id, study_id, document_role, "
            "url, target_path, and source_class"
        )
    normalized = dict(record)
    for field in ("download_id", "study_id"):
        value = record[field]
        if not isinstance(value, str) or not value.strip():
            raise ManifestIdentityError(f"{field} must be a nonempty string")
        normalized[field] = value.strip()
    for field in ("url", "target_path", "source_class"):
        value = record[field]
        if not isinstance(value, str) or not value.strip():
            raise ManifestIdentityError(f"{field} must be a nonempty string")
    role = record["document_role"]
    if not isinstance(role, str) or role not in DOCUMENT_ROLES:
        raise ManifestIdentityError("document_role must be MAIN or SI")
    expected_format = record.get("expected_format", "PDF")
    if not isinstance(expected_format, str) or expected_format not in EXPECTED_FORMATS:
        raise ManifestIdentityError("expected_format must be PDF, DOCX, or XLSX")
    normalized["expected_format"] = expected_format
    if "doi" in record and record["doi"] is not None:
        doi = normalize_doi(record["doi"])
        if doi is None:
            raise ManifestIdentityError("doi must be a valid DOI string or null")
        normalized["doi"] = doi
    return normalized
