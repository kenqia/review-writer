"""Source-grounded figure registry and human synthesis-figure briefs.

This module deliberately has no image generation or image composition path. Source
figures are references to the bytes extracted from a verified Source Truth bundle;
cross-study figures remain researcher-owned placeholders.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from review_writer.project.source_truth import (
    REPO_ROOT,
    SourceTruthError,
    canonical_digest,
    declared_study_ids,
    load_source_truth_bundle,
)


SOURCE_FIGURE_SCHEMA = REPO_ROOT / "schemas/figures/source_figure.v1.schema.json"
PLACEHOLDER_SCHEMA = REPO_ROOT / "schemas/figures/synthesis_figure_placeholder.v1.schema.json"
FIGURE_ROOT = Path("03_figures")
REGISTRY_PATH = FIGURE_ROOT / "source_figure_registry.json"
PLACEHOLDER_PATH = FIGURE_ROOT / "synthesis_figure_placeholders.json"
FIGURE_POLICY = "source_figures_or_synthesis_placeholders_only"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ReviewFigureError(ValueError):
    """A stable, fail-closed figure registry failure."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code


def _fail(code: str, message: str = "") -> None:
    raise ReviewFigureError(code, message)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ReviewFigureError("FIGURE_ASSET_INVALID") from exc
    return digest.hexdigest()


def _safe_project(project: Path) -> Path:
    supplied = Path(project)
    if supplied.is_symlink() or not supplied.is_dir():
        _fail("PROJECT_INVALID")
    try:
        return supplied.resolve(strict=True)
    except OSError as exc:
        raise ReviewFigureError("PROJECT_INVALID") from exc


def _safe_asset(project: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or relative.startswith("/") or "\\" in relative:
        _fail("FIGURE_ASSET_INVALID")
    candidate = project / relative
    try:
        resolved = candidate.resolve(strict=True)
        root = project.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ReviewFigureError("FIGURE_ASSET_INVALID") from exc
    if candidate.is_symlink() or not candidate.is_file():
        _fail("FIGURE_ASSET_INVALID")
    return resolved


def _read_json(path: Path, code: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReviewFigureError(code) from exc


def _validate(payload: object, schema_path: Path, code: str) -> None:
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReviewFigureError("FIGURE_SCHEMA_INVALID") from exc
    errors = sorted(Draft202012Validator(schema).iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        raise ReviewFigureError(code)


def _atomic_json(project: Path, path: Path, payload: object) -> None:
    target = project / path
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or (os.path.lexists(target) and not target.is_file()):
        _fail("FIGURE_STATE_INVALID")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=parent, prefix=f".{target.name}.", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        temporary = None
    except (OSError, TypeError, ValueError) as exc:
        raise ReviewFigureError("FIGURE_STATE_WRITE_FAILED") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _content_entries(project: Path, source: dict[str, Any]) -> list[dict[str, Any]]:
    descriptor = source.get("content_list")
    if not isinstance(descriptor, dict):
        _fail("FIGURE_CONTENT_LIST_INVALID")
    relative = descriptor.get("path")
    expected_sha256 = descriptor.get("sha256")
    if not isinstance(relative, str) or not isinstance(expected_sha256, str) or not _SHA256.fullmatch(expected_sha256):
        _fail("FIGURE_CONTENT_LIST_INVALID")
    content_path = _safe_asset(project, relative)
    if _sha256(content_path) != expected_sha256:
        _fail("FIGURE_CONTENT_LIST_DRIFT")
    payload = _read_json(content_path, "FIGURE_CONTENT_LIST_INVALID")
    if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
        _fail("FIGURE_CONTENT_LIST_INVALID")
    return payload


def _verify_source_images(project: Path, source: dict[str, Any]) -> None:
    slug = source.get("mineru_slug")
    if not isinstance(slug, str):
        _fail("FIGURE_SOURCE_INVALID")
    image_root = project / "01_evidence/parses/extracted" / slug / "images"
    rows: list[dict[str, Any]] = []
    if image_root.is_dir() and not image_root.is_symlink():
        for path in sorted(image_root.rglob("*")):
            if path.is_symlink():
                _fail("FIGURE_ASSET_INVALID")
            if path.is_file():
                relative = path.relative_to(project).as_posix()
                rows.append({"path": relative, "sha256": _sha256(path), "size_bytes": path.stat().st_size})
    expected = source.get("images")
    if not isinstance(expected, dict) or expected.get("count") != len(rows) or expected.get("digest") != canonical_digest(rows):
        _fail("FIGURE_IMAGE_SET_DRIFT")


_SOURCE_FIGURE_LABEL = re.compile(
    r"(?:Figure|Fig\.?|Scheme|Chart)\s*[A-Za-z]?\s*\d+",
    re.I,
)


def _explicit_caption(entry: dict[str, Any]) -> tuple[str, str] | None:
    raw = entry.get("image_caption")
    values = raw if isinstance(raw, list) else [raw] if isinstance(raw, str) else []
    clean = " ".join(
        " ".join(value.split())
        for value in values
        if isinstance(value, str) and value.strip()
    ).strip()
    match = _SOURCE_FIGURE_LABEL.search(clean)
    if not clean or match is None:
        return None
    return match.group(0), clean


def _source_truth_digest(root: Path) -> str:
    bindings: list[dict[str, str]] = []
    try:
        study_ids = declared_study_ids(root)
    except SourceTruthError as exc:
        raise ReviewFigureError(exc.code) from exc
    for study_id in study_ids:
        try:
            bundle = load_source_truth_bundle(root, study_id)
        except SourceTruthError as exc:
            raise ReviewFigureError(exc.code) from exc
        bundle_digest = bundle.get("bundle_digest")
        if not isinstance(bundle_digest, str) or not _SHA256.fullmatch(bundle_digest):
            _fail("FIGURE_SOURCE_INVALID")
        bindings.append({"study_id": study_id, "bundle_digest": bundle_digest})
    return canonical_digest(bindings)


def load_source_figure_registry(project: Path) -> dict[str, Any]:
    """Load a registry only when it is bound to the current Source Truth."""
    root = _safe_project(project)
    path = root / REGISTRY_PATH
    if path.is_symlink() or not path.is_file():
        _fail("FIGURE_STATE_INVALID")
    payload = _read_json(path, "FIGURE_STATE_INVALID")
    if not isinstance(payload, dict):
        _fail("FIGURE_STATE_INVALID")
    figures = payload.get("figures")
    locator_gaps = payload.get("locator_gaps")
    if (
        not isinstance(figures, list)
        or not all(isinstance(row, dict) for row in figures)
        or not isinstance(locator_gaps, list)
        or payload.get("source_truth_digest") != _source_truth_digest(root)
    ):
        _fail("FIGURE_REGISTRY_STALE")
    expected = canonical_digest(
        {
            "source_truth_digest": payload["source_truth_digest"],
            "figures": figures,
            "locator_gaps": locator_gaps,
        }
    )
    if payload.get("registry_digest") != expected:
        _fail("FIGURE_REGISTRY_INVALID")
    figure_ids: set[str] = set()
    for figure in figures:
        _validate(figure, SOURCE_FIGURE_SCHEMA, "FIGURE_REGISTRY_INVALID")
        figure_id = figure.get("figure_id")
        if not isinstance(figure_id, str) or figure_id in figure_ids:
            _fail("FIGURE_REGISTRY_INVALID")
        figure_ids.add(figure_id)
    return copy.deepcopy(payload)


def _evidence_ids(project: Path, study_id: str, source_id: str, page: int, label: str) -> list[str]:
    path = project / "01_evidence/paper_evidence_projection.jsonl"
    if not path.is_file() or path.is_symlink():
        return []
    ids: list[str] = []
    try:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, UnicodeError, json.JSONDecodeError):
        _fail("FIGURE_EVIDENCE_INVALID")
    for row in rows:
        if not isinstance(row, dict) or row.get("study_id") != study_id or row.get("source_id") != source_id:
            continue
        locator = row.get("locator")
        if not isinstance(locator, dict) or locator.get("page") != page:
            continue
        located = str(locator.get("figure_or_table") or "")
        if not located or label.lower() in located.lower() or "figure" in located.lower() or "fig" in located.lower():
            if isinstance(row.get("evidence_id"), str):
                ids.append(row["evidence_id"])
    return sorted(set(ids))


def build_source_figure_registry(project: Path) -> dict[str, Any]:
    """Rebuild source-figure entries from current Source Truth bytes."""
    root = _safe_project(project)
    try:
        studies = declared_study_ids(root)
    except SourceTruthError as exc:
        raise ReviewFigureError(exc.code) from exc
    figures: list[dict[str, Any]] = []
    locator_gaps: list[dict[str, Any]] = []
    source_truth_digest = _source_truth_digest(root)
    for study_id in studies:
        try:
            bundle = load_source_truth_bundle(root, study_id)
        except SourceTruthError as exc:
            raise ReviewFigureError(exc.code) from exc
        for source in bundle.get("sources", []):
            if not isinstance(source, dict) or source.get("document_role") != "MAIN":
                continue
            source_id = source.get("source_id")
            slug = source.get("mineru_slug")
            if not isinstance(source_id, str) or not isinstance(slug, str):
                _fail("FIGURE_SOURCE_INVALID")
            pdf_descriptor = source.get("pdf")
            if not isinstance(pdf_descriptor, dict) or not isinstance(pdf_descriptor.get("path"), str):
                _fail("FIGURE_SOURCE_INVALID")
            pdf_path = _safe_asset(root, pdf_descriptor["path"])
            if _sha256(pdf_path) != pdf_descriptor.get("sha256"):
                _fail("SOURCE_PDF_HASH_MISMATCH")
            _verify_source_images(root, source)
            extracted = root / "01_evidence/parses/extracted" / slug
            entries = _content_entries(root, source)
            image_root = (extracted / "images").resolve(strict=True)
            if image_root.is_symlink() or not image_root.is_dir():
                _fail("FIGURE_ASSET_INVALID")
            image_number = 0
            image_entries_by_page: dict[int, list[dict[str, Any]]] = {}
            for entry in entries:
                page_idx = entry.get("page_idx")
                if (
                    entry.get("type") == "image"
                    and isinstance(page_idx, int)
                    and page_idx >= 0
                ):
                    image_entries_by_page.setdefault(page_idx + 1, []).append(entry)
            ambiguous_pages = {
                page
                for page, page_entries in image_entries_by_page.items()
                if len(page_entries) > 1
                and sum(_explicit_caption(entry) is not None for entry in page_entries) == 1
            }
            for page, page_entries in sorted(image_entries_by_page.items()):
                if page in ambiguous_pages:
                    locator_gaps.append(
                        {
                            "study_id": study_id,
                            "source_id": source_id,
                            "page": page,
                            "reason": (
                                "同页多个图片碎片无法可靠归并为一张完整原论文图。"
                            ),
                        }
                    )
                elif not any(_explicit_caption(entry) is not None for entry in page_entries):
                    locator_gaps.append(
                        {
                            "study_id": study_id,
                            "source_id": source_id,
                            "page": page,
                            "reason": (
                                "抽取图片未绑定明确的原论文 Figure/Scheme 图注。"
                            ),
                        }
                    )
            seen_labels: set[str] = set()
            for entry in entries:
                if entry.get("type") != "image" or not isinstance(entry.get("img_path"), str):
                    continue
                raw_path = Path(entry["img_path"])
                if raw_path.is_absolute() or ".." in raw_path.parts:
                    _fail("FIGURE_ASSET_INVALID")
                asset = _safe_asset(root, (extracted / raw_path).relative_to(root).as_posix())
                try:
                    asset.relative_to(image_root)
                except ValueError as exc:
                    raise ReviewFigureError("FIGURE_ASSET_INVALID") from exc
                page_idx = entry.get("page_idx")
                if not isinstance(page_idx, int) or page_idx < 0:
                    _fail("FIGURE_LOCATOR_INVALID")
                page = page_idx + 1
                explicit = _explicit_caption(entry)
                if page in ambiguous_pages or explicit is None:
                    continue
                label, caption = explicit
                normalized_label = label.casefold().replace(".", "")
                if normalized_label in seen_labels:
                    locator_gaps.append(
                        {
                            "study_id": study_id,
                            "source_id": source_id,
                            "page": page,
                            "reason": "检测到重复图号，已拒绝重复定位。",
                        }
                    )
                    continue
                seen_labels.add(normalized_label)
                image_number += 1
                figure = {
                    "figure_id": (
                        f"{study_id}:{source_id}:"
                        f"{label.replace(' ', '-').replace('.', '').lower()}"
                    ),
                    "study_id": study_id,
                    "source_id": source_id,
                    "page": page,
                    "figure_label": label,
                    "caption": caption,
                    "asset_path": asset.relative_to(root).as_posix(),
                    "asset_sha256": _sha256(asset),
                    "source_pdf_sha256": source["pdf"]["sha256"],
                    "evidence_ids": _evidence_ids(root, study_id, source_id, page, label),
                    "selection_status": "selected" if image_number == 1 else "available",
                }
                _validate(figure, SOURCE_FIGURE_SCHEMA, "FIGURE_REGISTRY_INVALID")
                figures.append(figure)
    figures.sort(key=lambda row: (row["study_id"], row["source_id"], row["page"], row["figure_id"]))
    selected = [row for row in figures if row["selection_status"] == "selected"]
    minimum_slots, maximum_slots = 5, 8
    if len(selected) < minimum_slots:
        budget_status = "needs_human_selection"
        budget_gaps = [
            f"Select {minimum_slots - len(selected)} additional non-duplicative source figure(s) or register a synthesis placeholder."
        ]
    elif len(selected) > maximum_slots:
        budget_status = "over_budget"
        budget_gaps = [f"Reduce selected figures by {len(selected) - maximum_slots} slot(s)."]
    else:
        budget_status = "within_target"
        budget_gaps = []
    registry = {
        "schema_version": "review-writer-source-figure-registry.v1",
        "project_id": root.name,
        "figure_policy": FIGURE_POLICY,
        "figures": figures,
        "selected_count": len(selected),
        "available_count": len(figures),
        "target_figure_slots": {"minimum": minimum_slots, "maximum": maximum_slots},
        "source_truth_digest": source_truth_digest,
        "locator_gaps": locator_gaps,
        "figure_budget": {
            "status": budget_status,
            "selected_count": len(selected),
            "minimum": minimum_slots,
            "maximum": maximum_slots,
            "gaps": budget_gaps,
        },
        "registry_digest": canonical_digest(
            {
                "source_truth_digest": source_truth_digest,
                "figures": figures,
                "locator_gaps": locator_gaps,
            }
        ),
    }
    _atomic_json(root, REGISTRY_PATH, registry)
    return registry


def _load_placeholders(root: Path) -> list[dict[str, Any]]:
    path = root / PLACEHOLDER_PATH
    if not path.is_file() or path.is_symlink():
        return []
    payload = _read_json(path, "FIGURE_STATE_INVALID")
    if not isinstance(payload, dict) or not isinstance(payload.get("placeholders"), list):
        _fail("FIGURE_STATE_INVALID")
    placeholders = payload["placeholders"]
    if not all(isinstance(item, dict) for item in placeholders):
        _fail("FIGURE_STATE_INVALID")
    for item in placeholders:
        _validate(item, PLACEHOLDER_SCHEMA, "PLACEHOLDER_INVALID")
    return copy.deepcopy(placeholders)


def register_synthesis_figure_placeholder(project: Path, payload: object) -> dict[str, Any]:
    """Persist a researcher-facing brief; never creates an image asset."""
    root = _safe_project(project)
    if not isinstance(payload, dict):
        _fail("PLACEHOLDER_INVALID")
    candidate = copy.deepcopy(payload)
    _validate(candidate, PLACEHOLDER_SCHEMA, "PLACEHOLDER_INVALID")
    placeholders = _load_placeholders(root)
    placeholder_id = candidate["placeholder_id"]
    existing = next((row for row in placeholders if row["placeholder_id"] == placeholder_id), None)
    if existing is not None and existing != candidate:
        _fail("PLACEHOLDER_CONFLICT")
    if existing is None:
        placeholders.append(candidate)
        placeholders.sort(key=lambda row: row["placeholder_id"])
    state = {
        "schema_version": "review-writer-synthesis-figure-placeholders.v1",
        "project_id": root.name,
        "figure_policy": FIGURE_POLICY,
        "placeholders": placeholders,
        "placeholder_count": len(placeholders),
    }
    _atomic_json(root, PLACEHOLDER_PATH, state)
    return candidate


def synthesis_figure_placeholders(project: Path) -> list[dict[str, Any]]:
    return _load_placeholders(_safe_project(project))
