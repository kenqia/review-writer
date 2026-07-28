"""Release-time policy for manuscript figures."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError


ORIGINAL_GENERATED = "ORIGINAL_GENERATED"
LICENSED_SOURCE = "LICENSED_SOURCE"
FIGURE_BRIEF_PLACEHOLDER = "FIGURE_BRIEF_PLACEHOLDER"
_FIGURE_TYPES = {ORIGINAL_GENERATED, LICENSED_SOURCE, FIGURE_BRIEF_PLACEHOLDER}
_CC_LICENSE_RE = re.compile(
    r"^cc(?:\s*-\s*|\s+)by(?P<sa>(?:\s*-\s*|\s+)sa)?"
    r"(?:\s*-\s*|\s+)(?P<version>1\.0|2\.0|2\.5|3\.0|4\.0)"
    r"(?P<international>\s+international)?$",
    flags=re.IGNORECASE,
)
_CC_LONG_LICENSE_RE = re.compile(
    r"^creative\s+commons\s+attribution(?P<sa>(?:-|\s+)sharealike)?\s+"
    r"(?P<version>1\.0|2\.0|2\.5|3\.0|4\.0)(?P<international>\s+international)?$",
    flags=re.IGNORECASE,
)
_CC0_RE = re.compile(
    r"^(?:cc0(?:\s*-\s*|\s+)1\.0|creative\s+commons\s+zero\s+1\.0"
    r"(?:\s+universal)?)$",
    flags=re.IGNORECASE,
)
_PUBLIC_DOMAIN_RE = re.compile(
    r"^public\s+domain(?P<kind>\s+dedication|\s+mark\s+1\.0)?$",
    flags=re.IGNORECASE,
)
_WRITTEN_AUTHORIZATION_RE = re.compile(
    r"^(?:explicit\s+)?written\s+(?:authorization|permission)$",
    flags=re.IGNORECASE,
)
_EXTENSION_FORMATS = {
    ".bmp": "BMP",
    ".gif": "GIF",
    ".jpeg": "JPEG",
    ".jpg": "JPEG",
    ".png": "PNG",
    ".tif": "TIFF",
    ".tiff": "TIFF",
    ".webp": "WEBP",
}
_HASH_CHUNK_BYTES = 1024 * 1024
_MAX_IMAGE_BYTES = 32 * 1024 * 1024
_MAX_IMAGE_PIXELS = 40_000_000


class FigurePolicyError(ValueError):
    """A figure manifest is not eligible for verified release."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def _canonical_sha256(value: Any) -> str:
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FigurePolicyError("FIGURE_POLICY_INVALID", "figure manifest must be finite JSON") from exc
    return hashlib.sha256(payload).hexdigest()


def _required_text(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise FigurePolicyError("FIGURE_POLICY_INVALID", f"figure {key} must be nonempty text")
    return value.strip()


def _figure_type(row: dict[str, Any]) -> str:
    value = row.get("figure_type")
    if value is None and row.get("license") in _FIGURE_TYPES:
        value = row.get("license")
    if value not in _FIGURE_TYPES:
        raise FigurePolicyError("FIGURE_POLICY_INVALID", "figure_type is unsupported")
    return str(value)


def _required_text_list(row: dict[str, Any], key: str) -> list[str]:
    value = row.get(key)
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item.strip() for item in value)
    ):
        raise FigurePolicyError("FIGURE_POLICY_INVALID", f"figure {key} must be a nonempty text list")
    normalized = [item.strip() for item in value]
    if len(normalized) != len(set(normalized)):
        raise FigurePolicyError("FIGURE_POLICY_INVALID", f"figure {key} values must be unique")
    return normalized


def _canonical_permitted_license(value: str) -> str | None:
    normalized = " ".join(value.split())
    match = _CC_LICENSE_RE.fullmatch(normalized) or _CC_LONG_LICENSE_RE.fullmatch(normalized)
    if match:
        family = "CC BY-SA" if match.group("sa") else "CC BY"
        international = " International" if match.group("international") else ""
        return f"{family} {match.group('version')}{international}"
    if _CC0_RE.fullmatch(normalized):
        return "CC0 1.0"
    match = _PUBLIC_DOMAIN_RE.fullmatch(normalized)
    if match:
        kind = (match.group("kind") or "").casefold()
        if "mark" in kind:
            return "Public Domain Mark 1.0"
        if "dedication" in kind:
            return "Public Domain Dedication"
        return "Public Domain"
    match = _WRITTEN_AUTHORIZATION_RE.fullmatch(normalized)
    if match:
        return "Written Permission" if "permission" in normalized.casefold() else "Written Authorization"
    return None


def _is_written_permission(value: str) -> bool:
    return _WRITTEN_AUTHORIZATION_RE.fullmatch(" ".join(value.split())) is not None


def _content_sha256(path: Path, *, max_bytes: int | None = None) -> str:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_BYTES):
            total += len(chunk)
            if max_bytes is not None and total > max_bytes:
                raise FigurePolicyError(
                    "FIGURE_IMAGE_INVALID",
                    "figure image exceeds the release input limit",
                )
            digest.update(chunk)
    return digest.hexdigest()


def _image_binding(path: Path, markdown_path: str) -> dict[str, Any]:
    expected_format = _EXTENSION_FORMATS.get(Path(markdown_path).suffix.casefold())
    if expected_format is None:
        raise FigurePolicyError("FIGURE_IMAGE_INVALID", "figure image extension is unsupported")
    try:
        content_sha256 = _content_sha256(path, max_bytes=_MAX_IMAGE_BYTES)
        with Image.open(path) as image:
            image_format = image.format
            width, height = image.size
            if width <= 0 or height <= 0:
                raise FigurePolicyError(
                    "FIGURE_IMAGE_INVALID",
                    "figure image dimensions must be positive",
                )
            if width * height > _MAX_IMAGE_PIXELS:
                raise FigurePolicyError(
                    "FIGURE_IMAGE_INVALID",
                    "figure image exceeds the release pixel limit",
                )
            image.verify()
        with Image.open(path) as decoded:
            decoded.load()
    except (OSError, UnidentifiedImageError, ValueError, Image.DecompressionBombError) as exc:
        raise FigurePolicyError("FIGURE_IMAGE_INVALID", "figure image must be decodable") from exc
    if image_format != expected_format:
        raise FigurePolicyError(
            "FIGURE_IMAGE_INVALID",
            "figure image format must match its extension",
        )
    return {
        "content_sha256": content_sha256,
        "image_format": image_format,
        "width": width,
        "height": height,
    }


def validate_figure_policy(
    manifest: Any,
    *,
    approved_claim_ids: list[str],
    manuscript_sha256: str,
    manuscript_image_paths: list[str],
    manuscript_markdown: str,
    image_files_by_markdown_path: dict[str, Path],
) -> dict[str, Any]:
    """Validate release figure provenance and bind it to one manuscript revision."""
    if not isinstance(manifest, dict) or not isinstance(manifest.get("figures"), list):
        raise FigurePolicyError("FIGURE_POLICY_INVALID", "figure manifest must contain a figures list")
    if not manifest["figures"]:
        raise FigurePolicyError("FIGURE_POLICY_INVALID", "figure manifest must contain at least one figure")
    if not isinstance(manuscript_sha256, str) or not manuscript_sha256:
        raise FigurePolicyError("FIGURE_POLICY_INVALID", "manuscript digest is required")
    if (
        not isinstance(approved_claim_ids, list)
        or not all(isinstance(claim_id, str) and claim_id for claim_id in approved_claim_ids)
        or len(approved_claim_ids) != len(set(approved_claim_ids))
    ):
        raise FigurePolicyError("FIGURE_POLICY_INVALID", "approved claim ids must be unique text")
    approved_claim_id_set = set(approved_claim_ids)
    if not all(isinstance(path, str) and path for path in manuscript_image_paths):
        raise FigurePolicyError("FIGURE_POLICY_INVALID", "manuscript image paths must be nonempty text")
    if not manuscript_image_paths:
        raise FigurePolicyError("FIGURE_POLICY_INVALID", "manuscript must reference at least one figure")
    if not isinstance(manuscript_markdown, str):
        raise FigurePolicyError("FIGURE_POLICY_INVALID", "authoritative manuscript text is required")
    if not isinstance(image_files_by_markdown_path, dict):
        raise FigurePolicyError("FIGURE_POLICY_INVALID", "figure image bindings are required")

    normalized: list[dict[str, Any]] = []
    figure_ids: set[str] = set()
    release_paths: set[str] = set()
    for raw in manifest["figures"]:
        if not isinstance(raw, dict):
            raise FigurePolicyError("FIGURE_POLICY_INVALID", "figure entries must be objects")
        figure_id = _required_text(raw, "figure_id")
        if figure_id in figure_ids:
            raise FigurePolicyError("FIGURE_POLICY_INVALID", "figure_id values must be unique")
        figure_ids.add(figure_id)
        figure_type = _figure_type(raw)

        if figure_type == FIGURE_BRIEF_PLACEHOLDER:
            _required_text(raw, "brief")
            raise FigurePolicyError(
                "FIGURE_PLACEHOLDER_PENDING",
                "figure brief placeholders must be resolved before verified release",
            )

        markdown_path = _required_text(raw, "markdown_path")
        if markdown_path in release_paths:
            raise FigurePolicyError("FIGURE_POLICY_INVALID", "markdown_path values must be unique")
        release_paths.add(markdown_path)
        figure = {
            "figure_id": figure_id,
            "figure_type": figure_type,
            "markdown_path": markdown_path,
        }
        if figure_type == ORIGINAL_GENERATED:
            source_claim_ids = _required_text_list(raw, "source_claim_ids")
            if not set(source_claim_ids) <= approved_claim_id_set:
                raise FigurePolicyError(
                    "FIGURE_CLAIM_NOT_APPROVED",
                    "original figure source claims must belong to the current writer whitelist",
                )
            figure["source_claim_ids"] = source_claim_ids
        elif figure_type == LICENSED_SOURCE:
            license_name = _required_text(raw, "license")
            canonical_license = _canonical_permitted_license(license_name)
            if canonical_license is None:
                raise FigurePolicyError(
                    "FIGURE_POLICY_INVALID",
                    "source figures require an open license, public domain status, or written authorization",
                )
            figure["license"] = canonical_license
            if _is_written_permission(license_name):
                for key in (
                    "permission_grantor",
                    "permission_scope",
                    "permission_evidence_reference",
                ):
                    figure[key] = _required_text(raw, key)
                if raw.get("researcher_confirmed") is not True:
                    raise FigurePolicyError(
                        "FIGURE_POLICY_INVALID",
                        "written permission requires explicit researcher confirmation",
                    )
                figure["researcher_confirmed"] = True
            attribution = _required_text(raw, "attribution")
            if attribution not in manuscript_markdown:
                raise FigurePolicyError(
                    "FIGURE_ATTRIBUTION_MISSING",
                    "source figure attribution must appear in the authoritative manuscript",
                )
            figure["attribution"] = attribution
        normalized.append(figure)

    used_paths = set(manuscript_image_paths)
    if len(used_paths) != len(manuscript_image_paths):
        raise FigurePolicyError("FIGURE_POLICY_INVALID", "each manuscript figure path must be unique")
    if used_paths != release_paths:
        raise FigurePolicyError(
            "FIGURE_POLICY_INVALID",
            "manuscript images and figure manifest entries must match exactly",
        )
    for figure in normalized:
        markdown_path = figure["markdown_path"]
        image_file = image_files_by_markdown_path.get(markdown_path)
        if not isinstance(image_file, Path):
            raise FigurePolicyError("FIGURE_IMAGE_INVALID", "figure image binding is missing")
        figure.update(_image_binding(image_file, markdown_path))

    return {
        "schema_version": "review-writer-figure-validation.v1",
        "status": "VERIFIED",
        "manuscript_sha256": manuscript_sha256,
        "manifest_sha256": _canonical_sha256(manifest),
        "figures": normalized,
    }


def figure_validation_is_current(
    validation: Any,
    *,
    manuscript_sha256: str,
    manifest: Any,
    image_files_by_markdown_path: dict[str, Path] | None = None,
) -> bool:
    """Return whether a stored figure validation still binds current inputs."""
    if not isinstance(validation, dict) or validation.get("status") != "VERIFIED":
        return False
    try:
        manifest_sha256 = _canonical_sha256(manifest)
    except FigurePolicyError:
        return False
    if not (
        validation.get("manuscript_sha256") == manuscript_sha256
        and validation.get("manifest_sha256") == manifest_sha256
    ):
        return False
    if image_files_by_markdown_path is None:
        return True
    figures = validation.get("figures")
    if not isinstance(figures, list):
        return False
    try:
        for figure in figures:
            if not isinstance(figure, dict):
                return False
            markdown_path = figure.get("markdown_path")
            image_path = image_files_by_markdown_path.get(markdown_path)
            if not isinstance(markdown_path, str) or not isinstance(image_path, Path):
                return False
            content_sha256 = figure.get("content_sha256")
            if not isinstance(content_sha256, str) or _content_sha256(image_path) != content_sha256:
                return False
    except OSError:
        return False
    return True
