"""Resolve editable ProjectManifest input into a deterministic config snapshot."""

from __future__ import annotations

import copy
import hashlib
import json
import unicodedata
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schemas/project/project_manifest.schema.json"
CONFIG_AFFECTED_STAGES = ("CORPUS", "CLAIMS", "CHECKPOINT", "DRAFT", "RUN", "RELEASE")
_INTENT_LIMITS = {"goal": 4000, "scope": 8000}


class ManifestResolutionError(ValueError):
    """Raised when a manifest cannot produce a valid resolved configuration."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _schema() -> dict[str, Any]:
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestResolutionError("PROJECT_MANIFEST_SCHEMA_UNAVAILABLE", str(exc)) from exc
    Draft202012Validator.check_schema(schema)
    return schema


def _validate_schema(manifest: dict[str, Any]) -> None:
    errors = sorted(
        Draft202012Validator(_schema()).iter_errors(manifest),
        key=lambda item: tuple(str(part) for part in item.path),
    )
    if not errors:
        return
    first = errors[0]
    location = ".".join(str(part) for part in first.absolute_path) or "<root>"
    raise ManifestResolutionError("PROJECT_MANIFEST_SCHEMA_INVALID", f"{location}: {first.message}")


def _normalize_intent_text(field: str, value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    normalized = unicodedata.normalize("NFC", normalized).strip()
    for character in normalized:
        if character in {"\n", "\t"}:
            continue
        if character == "\x00" or unicodedata.category(character) == "Cc":
            raise ManifestResolutionError(
                f"INITIAL_USER_INTENT_{field.upper()}_CONTROL_CHARACTER",
                f"initial_user_intent.{field} contains a forbidden control character",
            )
    if not normalized:
        raise ManifestResolutionError(
            f"INITIAL_USER_INTENT_{field.upper()}_EMPTY",
            f"initial_user_intent.{field} is empty after normalization",
        )
    limit = _INTENT_LIMITS[field]
    if len(normalized) > limit:
        raise ManifestResolutionError(
            f"INITIAL_USER_INTENT_{field.upper()}_TOO_LONG",
            f"initial_user_intent.{field} exceeds {limit} Unicode code points after normalization",
        )
    return normalized


def resolve_project_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return a normalized copy without modifying the editable source manifest."""

    if not isinstance(manifest, dict):
        raise ManifestResolutionError("PROJECT_MANIFEST_NOT_OBJECT", "ProjectManifest must be a JSON object")
    _validate_schema(manifest)
    resolved = copy.deepcopy(manifest)
    intent = resolved["initial_user_intent"]
    for field in ("goal", "scope"):
        intent[field] = _normalize_intent_text(field, intent[field])
    _validate_schema(resolved)
    return resolved


def resolved_config_sha256(resolved: dict[str, Any]) -> str:
    """Hash the complete resolved configuration using stable local JSON bytes."""

    try:
        payload = json.dumps(
            resolved,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ManifestResolutionError("RESOLVED_CONFIG_NOT_SERIALIZABLE", str(exc)) from exc
    return hashlib.sha256(payload).hexdigest()


def load_resolved_project_manifest(path: Path) -> tuple[dict[str, Any], str]:
    """Load and resolve one manifest without writing back to its source file."""

    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestResolutionError("PROJECT_MANIFEST_UNREADABLE", str(exc)) from exc
    resolved = resolve_project_manifest(manifest)
    return resolved, resolved_config_sha256(resolved)
