"""Source-grounded figure registry and human synthesis-figure briefs.

This module deliberately has no image generation or image composition path. Source
figures are references to the bytes extracted from a verified Source Truth bundle;
cross-study figures remain researcher-owned placeholders.
"""

from __future__ import annotations

import copy
import hashlib
import heapq
import json
import math
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
from review_writer.project.chemical_paper import (
    STATE_NAME as CHEMICAL_PAPER_STATE_NAME,
    STATE_ROOT as CHEMICAL_PAPER_STATE_ROOT,
    ChemicalPaperError,
    load_chemical_paper_state,
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
_V2_LAYOUT_GAP = 80.0


def _content_v2_pages(project: Path, source: dict[str, Any]) -> list[list[dict[str, Any]]]:
    descriptor = source.get("content_list_v2")
    if not isinstance(descriptor, dict):
        _fail("FIGURE_CONTENT_LIST_V2_INVALID")
    relative = descriptor.get("path")
    expected_sha256 = descriptor.get("sha256")
    if (
        not isinstance(relative, str)
        or not isinstance(expected_sha256, str)
        or not _SHA256.fullmatch(expected_sha256)
    ):
        _fail("FIGURE_CONTENT_LIST_V2_INVALID")
    path = _safe_asset(project, relative)
    if _sha256(path) != expected_sha256:
        _fail("FIGURE_CONTENT_LIST_V2_DRIFT")
    payload = _read_json(path, "FIGURE_CONTENT_LIST_V2_INVALID")
    page_count = source.get("page_count")
    if (
        not isinstance(page_count, int)
        or isinstance(page_count, bool)
        or not isinstance(payload, list)
        or len(payload) != page_count
        or not all(
            isinstance(page, list) and all(isinstance(row, dict) for row in page)
            for page in payload
        )
    ):
        _fail("FIGURE_CONTENT_LIST_V2_INVALID")
    return payload


def _content_list_v2_digest(root: Path) -> str:
    bindings: list[dict[str, str]] = []
    try:
        studies = declared_study_ids(root)
    except SourceTruthError as exc:
        raise ReviewFigureError(exc.code) from exc
    for study_id in studies:
        try:
            bundle = load_source_truth_bundle(root, study_id)
        except SourceTruthError as exc:
            raise ReviewFigureError(exc.code) from exc
        for source in bundle.get("sources", []):
            if not isinstance(source, dict) or source.get("document_role") != "MAIN":
                continue
            _content_v2_pages(root, source)
            descriptor = source["content_list_v2"]
            bindings.append(
                {
                    "study_id": study_id,
                    "source_id": source["source_id"],
                    "sha256": descriptor["sha256"],
                }
            )
    return canonical_digest(bindings)


def _caption_text(raw: object) -> str | None:
    if not isinstance(raw, list):
        return None
    parts: list[str] = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("content"), str):
            return None
        clean = " ".join(item["content"].split())
        if clean:
            parts.append(clean)
    return " ".join(parts)


def _valid_bbox(value: object) -> list[int | float] | None:
    if (
        not isinstance(value, list)
        or len(value) != 4
        or any(
            isinstance(item, bool)
            or not isinstance(item, (int, float))
            or not math.isfinite(item)
            for item in value
        )
    ):
        return None
    x0, y0, x1, y1 = value
    if x0 < 0 or y0 < 0 or x1 <= x0 or y1 <= y0:
        return None
    return list(value)


def _v2_image_blocks(
    root: Path,
    *,
    study_id: str,
    source_id: str,
    source: dict[str, Any],
    extracted: Path,
    image_root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    blocks: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    for page_index, page_rows in enumerate(_content_v2_pages(root, source)):
        page = page_index + 1
        for block_index, entry in enumerate(page_rows):
            if entry.get("type") != "image":
                continue
            bbox = _valid_bbox(entry.get("bbox"))
            content = entry.get("content")
            image_source = content.get("image_source") if isinstance(content, dict) else None
            image_path = image_source.get("path") if isinstance(image_source, dict) else None
            caption = _caption_text(
                content.get("image_caption") if isinstance(content, dict) else None
            )
            if bbox is None or not isinstance(image_path, str) or caption is None:
                gaps.append(
                    {
                        "study_id": study_id,
                        "source_id": source_id,
                        "page": page,
                        "reason": "content_list_v2 图块缺少完整 bbox、图片来源或图注关系，已拒绝定位。",
                    }
                )
                continue
            raw_path = Path(image_path)
            if raw_path.is_absolute() or ".." in raw_path.parts:
                _fail("FIGURE_ASSET_INVALID")
            asset = _safe_asset(
                root,
                (extracted / raw_path).relative_to(root).as_posix(),
            )
            try:
                asset.relative_to(image_root)
            except ValueError as exc:
                raise ReviewFigureError("FIGURE_ASSET_INVALID") from exc
            labels = [match.group(0) for match in _SOURCE_FIGURE_LABEL.finditer(caption)]
            blocks.append(
                {
                    "page": page,
                    "block_index": block_index,
                    "bbox": bbox,
                    "asset_path": asset.relative_to(root).as_posix(),
                    "asset_sha256": _sha256(asset),
                    "caption": caption,
                    "labels": labels,
                }
            )
    return blocks, gaps


def _spatially_related(left: dict[str, Any], right: dict[str, Any]) -> bool:
    lx0, ly0, lx1, ly1 = left["bbox"]
    rx0, ry0, rx1, ry1 = right["bbox"]
    overlap_x = min(lx1, rx1) - max(lx0, rx0)
    overlap_y = min(ly1, ry1) - max(ly0, ry0)
    horizontal_gap = max(rx0 - lx1, lx0 - rx1, 0)
    vertical_gap = max(ry0 - ly1, ly0 - ry1, 0)
    return (
        overlap_x > 0 and vertical_gap <= _V2_LAYOUT_GAP
    ) or (
        overlap_y > 0 and horizontal_gap <= _V2_LAYOUT_GAP
    )


def _spatial_cost(left: dict[str, Any], right: dict[str, Any]) -> float:
    if not _spatially_related(left, right):
        return math.inf
    lx0, ly0, lx1, ly1 = left["bbox"]
    rx0, ry0, rx1, ry1 = right["bbox"]
    overlap_x = max(0.0, min(lx1, rx1) - max(lx0, rx0))
    overlap_y = max(0.0, min(ly1, ry1) - max(ly0, ry0))
    horizontal_gap = max(rx0 - lx1, lx0 - rx1, 0)
    vertical_gap = max(ry0 - ly1, ly0 - ry1, 0)
    costs: list[float] = []
    if overlap_x > 0:
        overlap_ratio = overlap_x / min(lx1 - lx0, rx1 - rx0)
        costs.append(vertical_gap / overlap_ratio)
    if overlap_y > 0:
        overlap_ratio = overlap_y / min(ly1 - ly0, ry1 - ry0)
        costs.append(horizontal_gap / overlap_ratio)
    return min(costs, default=math.inf)


def _anchor_distances(
    blocks: list[dict[str, Any]],
    anchor_index: int,
) -> list[float]:
    distances = [math.inf] * len(blocks)
    distances[anchor_index] = 0.0
    queue: list[tuple[float, int]] = [(0.0, anchor_index)]
    while queue:
        distance, current = heapq.heappop(queue)
        if distance != distances[current]:
            continue
        for candidate in range(len(blocks)):
            if candidate == current or (
                candidate != anchor_index and blocks[candidate]["labels"]
            ):
                continue
            edge = _spatial_cost(blocks[current], blocks[candidate])
            proposed = distance + edge
            if proposed < distances[candidate]:
                distances[candidate] = proposed
                heapq.heappush(queue, (proposed, candidate))
    return distances


def _spatial_components(blocks: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    remaining = set(range(len(blocks)))
    components: list[list[dict[str, Any]]] = []
    while remaining:
        pending = [remaining.pop()]
        indexes: list[int] = []
        while pending:
            current = pending.pop()
            indexes.append(current)
            neighbours = {
                candidate
                for candidate in remaining
                if not (blocks[current]["labels"] and blocks[candidate]["labels"])
                and _spatially_related(blocks[current], blocks[candidate])
            }
            remaining.difference_update(neighbours)
            pending.extend(neighbours)
        components.append(
            sorted(
                (blocks[index] for index in indexes),
                key=lambda row: (row["bbox"][1], row["bbox"][0], row["block_index"]),
            )
        )
    return sorted(
        components,
        key=lambda rows: (rows[0]["page"], rows[0]["bbox"][1], rows[0]["bbox"][0]),
    )


def _normalized_label(label: str) -> str:
    return re.sub(r"[.\s]+", "", label.casefold())


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


def _chemical_paper_bindings(root: Path) -> tuple[str | None, dict[str, str]]:
    state_root = root / CHEMICAL_PAPER_STATE_ROOT
    if not state_root.exists():
        return None, {}
    try:
        studies = declared_study_ids(root)
    except SourceTruthError as exc:
        raise ReviewFigureError(exc.code) from exc
    rows: list[dict[str, str]] = []
    by_study: dict[str, str] = {}
    for study_id in studies:
        path = state_root / study_id / CHEMICAL_PAPER_STATE_NAME
        if not path.exists():
            continue
        try:
            state = load_chemical_paper_state(root, study_id)
        except ChemicalPaperError as exc:
            raise ReviewFigureError(exc.code) from exc
        digest = state["current_import_digest"]
        rows.append({"study_id": study_id, "chemical_paper_import_digest": digest})
        by_study[study_id] = digest
    return canonical_digest(rows), by_study


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
    try:
        content_list_v2_digest = _content_list_v2_digest(root)
    except ReviewFigureError as exc:
        raise ReviewFigureError("FIGURE_REGISTRY_STALE") from exc
    chemical_digest, _ = _chemical_paper_bindings(root)
    if (
        not isinstance(figures, list)
        or not all(isinstance(row, dict) for row in figures)
        or not isinstance(locator_gaps, list)
        or payload.get("source_truth_digest") != _source_truth_digest(root)
        or payload.get("content_list_v2_digest") != content_list_v2_digest
        or payload.get("chemical_paper_project_binding_digest") != chemical_digest
    ):
        _fail("FIGURE_REGISTRY_STALE")
    expected = canonical_digest(
        {
            "source_truth_digest": payload["source_truth_digest"],
            "content_list_v2_digest": content_list_v2_digest,
            "chemical_paper_project_binding_digest": chemical_digest,
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
    content_list_v2_digest = _content_list_v2_digest(root)
    chemical_paper_project_binding_digest, chemical_imports = _chemical_paper_bindings(root)
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
            if study_id in chemical_imports:
                locator_gaps.append(
                    {
                        "study_id": study_id,
                        "source_id": source_id,
                        "page": 1,
                        "reason": (
                            "MinerU Chemical Paper 导出包未提供独立图片文件；"
                            "其页面区域仅作为原始 PDF 定位，Source Figure 仍只使用"
                            "当前 Generic MinerU 的显式 caption 与原图资产。"
                        ),
                    }
                )
            _verify_source_images(root, source)
            extracted = root / "01_evidence/parses/extracted" / slug
            # v1 remains part of Source Truth byte integrity, but is never used
            # for page, caption, label, or grouping decisions.
            _content_entries(root, source)
            image_root = (extracted / "images").resolve(strict=True)
            if image_root.is_symlink() or not image_root.is_dir():
                _fail("FIGURE_ASSET_INVALID")
            blocks, block_gaps = _v2_image_blocks(
                root,
                study_id=study_id,
                source_id=source_id,
                source=source,
                extracted=extracted,
                image_root=image_root,
            )
            locator_gaps.extend(block_gaps)
            label_counts: dict[str, int] = {}
            for block in blocks:
                for label in block["labels"]:
                    normalized = _normalized_label(label)
                    label_counts[normalized] = label_counts.get(normalized, 0) + 1
            duplicate_labels = {
                label for label, count in label_counts.items() if count > 1
            }
            for normalized in sorted(duplicate_labels):
                duplicate_blocks = [
                    block
                    for block in blocks
                    if any(_normalized_label(label) == normalized for label in block["labels"])
                ]
                locator_gaps.append(
                    {
                        "study_id": study_id,
                        "source_id": source_id,
                        "page": min(block["page"] for block in duplicate_blocks),
                        "reason": "检测到重复图号，所有重复定位均已拒绝。",
                    }
                )
            candidates: list[dict[str, Any]] = []
            blocks_by_page: dict[int, list[dict[str, Any]]] = {}
            for block in blocks:
                blocks_by_page.setdefault(block["page"], []).append(block)
            for page, page_blocks in sorted(blocks_by_page.items()):
                anchors = [
                    index
                    for index, block in enumerate(page_blocks)
                    if len(block["labels"]) == 1
                ]
                invalid_anchors = {
                    index
                    for index, block in enumerate(page_blocks)
                    if len(block["labels"]) > 1
                    or (
                        len(block["labels"]) == 1
                        and _normalized_label(block["labels"][0]) in duplicate_labels
                    )
                }
                for index, block in enumerate(page_blocks):
                    if len(block["labels"]) > 1:
                        locator_gaps.append(
                            {
                                "study_id": study_id,
                                "source_id": source_id,
                                "page": page,
                                "reason": "单个 content_list_v2 图块图注包含多个图号，已拒绝定位。",
                            }
                        )
                distances = {
                    anchor: _anchor_distances(page_blocks, anchor)
                    for anchor in anchors
                }
                assignments: dict[int, list[int]] = {anchor: [] for anchor in anchors}
                missing: list[dict[str, Any]] = []
                for index, block in enumerate(page_blocks):
                    if block["labels"]:
                        continue
                    reachable = sorted(
                        (values[index], anchor)
                        for anchor, values in distances.items()
                        if math.isfinite(values[index])
                    )
                    if not reachable:
                        missing.append(block)
                        continue
                    best_distance, best_anchor = reachable[0]
                    ambiguity_limit = best_distance * 1.10 + 5.0
                    ambiguous_anchors = [
                        anchor
                        for distance, anchor in reachable
                        if distance <= ambiguity_limit
                    ]
                    if len(ambiguous_anchors) > 1:
                        invalid_anchors.update(ambiguous_anchors)
                        locator_gaps.append(
                            {
                                "study_id": study_id,
                                "source_id": source_id,
                                "page": page,
                                "reason": "同一图块可关联多个图号，无法可靠确定 caption 聚合关系。",
                            }
                        )
                        continue
                    assignments[best_anchor].append(index)
                for _component in _spatial_components(missing):
                    locator_gaps.append(
                        {
                            "study_id": study_id,
                            "source_id": source_id,
                            "page": page,
                            "reason": "content_list_v2 图块未绑定明确的原论文 Figure/Scheme/Chart 图注。",
                        }
                    )
                for anchor_index in anchors:
                    if anchor_index in invalid_anchors:
                        continue
                    anchor = page_blocks[anchor_index]
                    label = anchor["labels"][0]
                    fragment_indexes = sorted(
                        [anchor_index, *assignments[anchor_index]],
                        key=lambda index: (
                            page_blocks[index]["bbox"][1],
                            page_blocks[index]["bbox"][0],
                            page_blocks[index]["block_index"],
                        ),
                    )
                    candidates.append(
                        {
                            "page": page,
                            "label": label,
                            "caption": anchor["caption"],
                            "anchor": anchor,
                            "fragments": [page_blocks[index] for index in fragment_indexes],
                        }
                    )
            for image_number, candidate in enumerate(candidates, start=1):
                page = candidate["page"]
                label = candidate["label"]
                caption = candidate["caption"]
                anchor = candidate["anchor"]
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
                    "asset_path": anchor["asset_path"],
                    "asset_sha256": anchor["asset_sha256"],
                    "source_pdf_sha256": source["pdf"]["sha256"],
                    "evidence_ids": _evidence_ids(root, study_id, source_id, page, label),
                    "selection_status": "selected" if image_number == 1 else "available",
                    "fragments": [
                        {
                            "page": fragment["page"],
                            "block_index": fragment["block_index"],
                            "bbox": fragment["bbox"],
                            "asset_path": fragment["asset_path"],
                            "asset_sha256": fragment["asset_sha256"],
                            "caption_association": (
                                "explicit_caption_anchor"
                                if fragment is anchor
                                else "same_page_spatial_group"
                            ),
                        }
                        for fragment in candidate["fragments"]
                    ],
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
        "content_list_v2_digest": content_list_v2_digest,
        "chemical_paper_project_binding_digest": chemical_paper_project_binding_digest,
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
                "content_list_v2_digest": content_list_v2_digest,
                "chemical_paper_project_binding_digest": chemical_paper_project_binding_digest,
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
