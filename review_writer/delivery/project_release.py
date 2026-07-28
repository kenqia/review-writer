"""Single-source manuscript editing and deterministic project release."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from review_writer.delivery.figure_policy import (
    FigurePolicyError,
    figure_validation_is_current,
    validate_figure_policy,
)
from review_writer.project.vertical_review import VerticalReviewError, benchmark_metrics


_ATX_HEADING_RE = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_DOCX_CODE_FENCE_RE = re.compile(r"^```(\w*)\s*$")
_IMAGE_MARKER_RE = re.compile(r"!\[")
_CANONICAL_IMAGE_RE = re.compile(r"^!\[([^\]\r\n]*)\]\(([^\s()<>\"']+)\)[ \t]*$")
_REFERENCE_RE = re.compile(r"^\s*(?:\[(\d+)\]|(\d+)[.)])\s+\S")
_CITATION_RE = re.compile(r"(?<!!)\[([0-9][0-9,;\s\-–—]*)\]")
_CLAIM_MARKER_RE = re.compile(
    r"(?:\[claim:([A-Za-z0-9._:-]+)\]|<!--\s*claim(?:_id)?\s*:\s*([A-Za-z0-9._:-]+)\s*-->)",
    flags=re.IGNORECASE,
)
PROJECT_RELEASE_LOCK = threading.RLock()


class ProjectReleaseError(ValueError):
    """The authoritative manuscript cannot be released safely."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def _section_id(heading: str, seen: dict[str, int]) -> str:
    base = re.sub(r"[^\w]+", "-", heading.casefold(), flags=re.UNICODE).strip("-_")
    base = base or "section"
    seen[base] = seen.get(base, 0) + 1
    return base if seen[base] == 1 else f"{base}-{seen[base]}"


def _split_manuscript_sections(markdown: str, *, include_spans: bool) -> list[dict[str, Any]]:
    if not isinstance(markdown, str):
        raise ProjectReleaseError("MANUSCRIPT_INVALID", "markdown must be text")

    matches: list[tuple[int, int, int, str]] = []
    offset = 0
    fence: str | None = None
    for line in markdown.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        fence_match = _FENCE_RE.match(content)
        if fence_match:
            marker = fence_match.group(1)
            if fence is None:
                fence = marker[0]
            elif marker[0] == fence:
                fence = None
        elif fence is None:
            heading_match = _ATX_HEADING_RE.match(content)
            if heading_match:
                matches.append(
                    (
                        offset,
                        offset + len(line),
                        len(heading_match.group(1)),
                        heading_match.group(2).strip(),
                    )
                )
        offset += len(line)

    if not matches:
        raise ProjectReleaseError("MANUSCRIPT_SECTIONS_INVALID", "manuscript requires ATX headings")
    if markdown[: matches[0][0]].strip():
        raise ProjectReleaseError("MANUSCRIPT_SECTIONS_INVALID", "content before the first heading is not supported")

    seen: dict[str, int] = {}
    sections: list[dict[str, Any]] = []
    for index, (_, heading_end, level, heading) in enumerate(matches):
        body_end = matches[index + 1][0] if index + 1 < len(matches) else len(markdown)
        body = markdown[heading_end:body_end].strip("\r\n")
        section = {
            "id": _section_id(heading, seen),
            "heading": heading,
            "level": level,
            "body": body,
        }
        if include_spans:
            section["_body_start"] = heading_end
            section["_body_end"] = body_end
        sections.append(section)
    return sections


def split_manuscript_sections(markdown: str) -> list[dict[str, Any]]:
    """Split an ATX-heading manuscript into ordered, editable sections."""
    return _split_manuscript_sections(markdown, include_spans=False)


def replace_manuscript_section_body(markdown: str, section_id: str, body: str) -> str:
    """Replace one section body while preserving every non-target manuscript byte."""
    if not isinstance(section_id, str) or not section_id or not isinstance(body, str):
        raise ProjectReleaseError("MANUSCRIPT_SECTIONS_INVALID", "section_id and body are required")
    sections = _split_manuscript_sections(markdown, include_spans=True)
    targets = [section for section in sections if section["id"] == section_id]
    if len(targets) != 1:
        raise ProjectReleaseError("MANUSCRIPT_SECTIONS_INVALID", "target section must exist exactly once")
    target = targets[0]
    body_start = int(target["_body_start"])
    body_end = int(target["_body_end"])
    original_body = markdown[body_start:body_end]
    newline = "\r\n" if markdown[:body_start].endswith("\r\n") else "\n"
    normalized_body = body.strip("\r\n").replace("\r\n", "\n").replace("\r", "\n").replace("\n", newline)

    if not normalized_body:
        replacement = original_body if not original_body.strip("\r\n") else (
            original_body[: len(original_body) - len(original_body.lstrip("\r\n"))]
            + original_body[len(original_body.rstrip("\r\n")) :]
        )
    elif original_body.strip("\r\n"):
        leading_length = len(original_body) - len(original_body.lstrip("\r\n"))
        trailing_start = len(original_body.rstrip("\r\n"))
        replacement = original_body[:leading_length] + normalized_body + original_body[trailing_start:]
    else:
        replacement = newline + normalized_body
        replacement += newline * (2 if body_end < len(markdown) else 1)
    return markdown[:body_start] + replacement + markdown[body_end:]


def render_manuscript_sections(sections: list[dict[str, Any]]) -> str:
    """Render ordered section data back to one canonical Markdown manuscript."""
    if not isinstance(sections, list) or not sections:
        raise ProjectReleaseError("MANUSCRIPT_SECTIONS_INVALID", "sections must be a nonempty list")

    rendered: list[str] = []
    ids: list[str] = []
    headings: list[str] = []
    for section in sections:
        if not isinstance(section, dict):
            raise ProjectReleaseError("MANUSCRIPT_SECTIONS_INVALID", "section rows must be objects")
        section_id = section.get("id")
        heading = section.get("heading")
        level = section.get("level")
        body = section.get("body")
        if not isinstance(section_id, str) or not section_id.strip():
            raise ProjectReleaseError("MANUSCRIPT_SECTIONS_INVALID", "section ids must be nonempty")
        if not isinstance(heading, str) or not heading.strip() or "\n" in heading or "\r" in heading:
            raise ProjectReleaseError("MANUSCRIPT_SECTIONS_INVALID", "section headings must be single nonempty lines")
        if isinstance(level, bool) or not isinstance(level, int) or not 1 <= level <= 6:
            raise ProjectReleaseError("MANUSCRIPT_SECTIONS_INVALID", "section levels must be within 1..6")
        if not isinstance(body, str):
            raise ProjectReleaseError("MANUSCRIPT_SECTIONS_INVALID", "section bodies must be text")
        ids.append(section_id)
        headings.append(heading.strip().casefold())
        block = f"{'#' * level} {heading.strip()}"
        if body.strip("\r\n"):
            block += f"\n\n{body.strip(chr(13) + chr(10))}"
        rendered.append(block)

    if len(ids) != len(set(ids)) or len(headings) != len(set(headings)):
        raise ProjectReleaseError("MANUSCRIPT_SECTIONS_INVALID", "section ids and headings must be unique")
    return "\n\n".join(rendered)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


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
        raise ProjectReleaseError("RELEASE_STATE_INVALID", "release state must be finite JSON") from exc
    return _sha256_bytes(payload)


def is_reparse_component(path: Path) -> bool:
    return path.is_symlink() or bool(hasattr(path, "is_junction") and path.is_junction())


def _reject_reparse_components(project: Path, relatives: tuple[Path, ...]) -> None:
    if is_reparse_component(project) or not project.is_dir():
        raise ProjectReleaseError("PROJECT_PATH_INVALID", "project root must be a real directory")
    for relative in relatives:
        component = project
        for part in relative.parts:
            component /= part
            if is_reparse_component(component):
                raise ProjectReleaseError("PROJECT_PATH_INVALID", "release path contains a symlink or reparse point")


def validate_project_path_components(project: Path, relatives: tuple[Path, ...]) -> None:
    """Reject symlink/reparse components across project-relative paths, including optional files."""
    _reject_reparse_components(Path(project), relatives)


def validate_project_file_path(project: Path, relative: Path, code: str) -> Path:
    """Return a required project file after rejecting symlink/reparse components."""
    validate_project_path_components(project, (relative,))
    candidate = project / relative
    if not candidate.is_file():
        raise ProjectReleaseError(code, "required release input is missing")
    try:
        candidate.resolve(strict=True).relative_to(project.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise ProjectReleaseError("PROJECT_PATH_INVALID", "release input escapes the project") from exc
    return candidate


def _read_json(path: Path, code: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectReleaseError(code, "required JSON release state is missing or invalid") from exc


def _read_jsonl(path: Path, code: str) -> list[dict[str, Any]]:
    try:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectReleaseError(code, "required JSONL release state is missing or invalid") from exc
    if not all(isinstance(row, dict) for row in rows):
        raise ProjectReleaseError(code, "release JSONL must contain objects")
    return rows


def _without_docx_code_blocks(markdown: str) -> str:
    visible: list[str] = []
    in_code_block = False
    for line in markdown.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        if not in_code_block and _DOCX_CODE_FENCE_RE.match(content):
            in_code_block = True
            visible.append("\n" if line.endswith(("\n", "\r")) else "")
        elif in_code_block:
            if content.startswith("```"):
                in_code_block = False
            visible.append("\n" if line.endswith(("\n", "\r")) else "")
        else:
            visible.append(line)
    return "".join(visible)


def _citation_numbers(markdown: str) -> set[int]:
    numbers: set[int] = set()
    for match in _CITATION_RE.finditer(markdown):
        for token in re.split(r"[,;\s]+", match.group(1).strip()):
            if not token:
                continue
            range_match = re.fullmatch(r"(\d+)[\-–—](\d+)", token)
            if range_match:
                start, end = map(int, range_match.groups())
                if start > end or end - start > 1000:
                    raise ProjectReleaseError("REFERENCES_INVALID", "citation range is invalid")
                numbers.update(range(start, end + 1))
            elif token.isdigit():
                numbers.add(int(token))
    return numbers


def _validate_references(sections: list[dict[str, Any]]) -> int:
    reference_sections = [section for section in sections if section["heading"].strip().casefold() == "references"]
    if len(reference_sections) != 1:
        raise ProjectReleaseError("REFERENCES_INVALID", "manuscript requires exactly one References section")
    body = reference_sections[0]["body"]
    if not body.strip():
        raise ProjectReleaseError("REFERENCES_INVALID", "References section must not be empty")
    reference_numbers: list[int] = []
    for line in body.splitlines():
        match = _REFERENCE_RE.match(line)
        if match:
            reference_numbers.append(int(match.group(1) or match.group(2)))
    if not reference_numbers or len(reference_numbers) != len(set(reference_numbers)):
        raise ProjectReleaseError("REFERENCES_INVALID", "references must have unique numeric entries")
    body_markdown = "\n\n".join(
        section["body"]
        for section in sections
        if section["heading"].strip().casefold() != "references"
    )
    missing = _citation_numbers(body_markdown) - set(reference_numbers)
    if missing:
        raise ProjectReleaseError("REFERENCES_INVALID", "manuscript cites a missing reference")
    return len(reference_numbers)


def _validated_image(project: Path, relative_url: str) -> Path:
    raw = relative_url.strip()
    parsed = urlparse(raw)
    if (
        not raw
        or parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or raw.startswith(("/", "\\"))
        or "\\" in raw
    ):
        raise ProjectReleaseError("IMAGE_INVALID", "release images must use project-local relative paths")
    relative = Path(parsed.path)
    if any(part in {"", "."} for part in relative.parts):
        raise ProjectReleaseError("IMAGE_INVALID", "release image path is not canonical")

    project_root = project.resolve(strict=True)
    resolved_by_stage: list[Path] = []
    for stage in (project / "04_first_draft", project / "05_final_audit"):
        candidate = Path(os.path.normpath(os.fspath(stage / relative)))
        try:
            lexical_relative = candidate.relative_to(project)
        except ValueError as exc:
            raise ProjectReleaseError("IMAGE_INVALID", "release image is outside the project") from exc
        checked = project
        for part in lexical_relative.parts:
            checked /= part
            if is_reparse_component(checked):
                raise ProjectReleaseError("IMAGE_INVALID", "release image path contains a symlink or reparse point")
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(project_root)
        except (OSError, ValueError) as exc:
            raise ProjectReleaseError("IMAGE_INVALID", "release image is missing or outside the project") from exc
        if not resolved.is_file():
            raise ProjectReleaseError("IMAGE_INVALID", "release image is not a regular file")
        resolved_by_stage.append(resolved)
    if resolved_by_stage[0] != resolved_by_stage[1]:
        raise ProjectReleaseError("IMAGE_INVALID", "image path does not bind draft and release to one source")
    return resolved_by_stage[0]


def manuscript_lineage_entries(lineage: dict[str, Any]) -> list[dict[str, Any]]:
    """Return claim-lineage rows across supported manuscript lineage layouts."""
    for key in ("claims", "claim_lineage", "manuscript_claims", "lineage"):
        value = lineage.get(key)
        if isinstance(value, list):
            return value
    sections = lineage.get("sections")
    entries: list[dict[str, Any]] = []
    if isinstance(sections, list):
        for section in sections:
            if not isinstance(section, dict):
                continue
            if isinstance(section.get("claims"), list):
                entries.extend(section["claims"])
            elif isinstance(section.get("claim_ids"), list):
                entries.extend(
                    {"claim_id": claim_id, "section_id": section.get("section_id") or section.get("id")}
                    for claim_id in section["claim_ids"]
                )
    return entries


def _pending_scientific_edits(lineage: dict[str, Any]) -> list[dict[str, Any]]:
    pending = lineage.get("pending_scientific_edits", [])
    if not isinstance(pending, list):
        raise ProjectReleaseError(
            "MANUSCRIPT_LINEAGE_INVALID",
            "pending_scientific_edits must be a list",
        )
    normalized: list[dict[str, Any]] = []
    section_ids: set[str] = set()
    for row in pending:
        if not isinstance(row, dict):
            raise ProjectReleaseError(
                "MANUSCRIPT_LINEAGE_INVALID",
                "pending_scientific_edits must contain objects",
            )
        section_id = row.get("section_id")
        verified_body = row.get("verified_body")
        reasons = row.get("reasons")
        if (
            not isinstance(section_id, str)
            or not section_id
            or section_id in section_ids
            or not isinstance(verified_body, str)
            or not isinstance(reasons, list)
            or not reasons
            or not all(isinstance(reason, str) and reason for reason in reasons)
        ):
            raise ProjectReleaseError(
                "MANUSCRIPT_LINEAGE_INVALID",
                "pending_scientific_edits require unique sections, verified text, and reasons",
            )
        section_ids.add(section_id)
        normalized.append(
            {
                "section_id": section_id,
                "verified_body": verified_body,
                "reasons": list(reasons),
            }
        )
    return normalized


def _literal_occurrence_count(text: str, needle: str) -> int:
    count = 0
    offset = 0
    while True:
        index = text.find(needle, offset)
        if index < 0:
            return count
        count += 1
        offset = index + 1


def _validate_manuscript_lineage(
    project: Path,
    markdown: str,
    *,
    lineage_override: dict[str, Any] | None = None,
    allow_pending_scientific_edits: bool = False,
    allow_pending_text_span_drift: bool = False,
) -> dict[str, Any]:
    project_path = Path(project)
    if not isinstance(markdown, str):
        raise ProjectReleaseError("MANUSCRIPT_INVALID", "markdown must be text")
    try:
        metrics = benchmark_metrics(project_path)
    except VerticalReviewError as exc:
        raise ProjectReleaseError(exc.code, "Task4 projection state is not release-ready") from exc

    projection_path = validate_project_file_path(
        project_path, Path("02_claims/claim_projection.jsonl"), "PROJECTION_INVALID"
    )
    writer_path = validate_project_file_path(
        project_path, Path("02_claims/writer_packet.json"), "WRITER_PACKET_INVALID"
    )
    lineage_path = None
    if lineage_override is None:
        lineage_path = validate_project_file_path(
            project_path,
            Path("04_first_draft/manuscript_lineage.json"),
            "MANUSCRIPT_LINEAGE_INVALID",
        )
    projection = _read_jsonl(projection_path, "PROJECTION_INVALID")
    writer_packet = _read_json(writer_path, "WRITER_PACKET_INVALID")
    lineage = lineage_override if lineage_override is not None else _read_json(
        lineage_path, "MANUSCRIPT_LINEAGE_INVALID"  # type: ignore[arg-type]
    )
    if not isinstance(writer_packet, dict) or not isinstance(lineage, dict):
        raise ProjectReleaseError("RELEASE_STATE_INVALID", "writer packet and lineage must be objects")
    pending = _pending_scientific_edits(lineage)
    if pending and not allow_pending_scientific_edits:
        raise ProjectReleaseError(
            "MANUSCRIPT_NEEDS_EVIDENCE_REVIEW",
            "pending scientific edits must be evidence-reviewed before release",
        )

    claim_ids = [row.get("claim_id") for row in projection]
    if any(not isinstance(claim_id, str) or not claim_id for claim_id in claim_ids) or len(claim_ids) != len(set(claim_ids)):
        raise ProjectReleaseError("PROJECTION_INVALID", "projection claim ids must be unique")
    projection_by_id = {row["claim_id"]: row for row in projection}
    projection_sha256 = _canonical_sha256(projection)
    if writer_packet.get("projection_sha256") != projection_sha256:
        raise ProjectReleaseError("WRITER_PACKET_STALE", "writer packet does not bind the current projection")
    approved_rows = [row for row in projection if row.get("decision") == "APPROVED"]
    packet_claims = writer_packet.get("claims")
    if not isinstance(packet_claims, list) or not all(isinstance(row, dict) for row in packet_claims):
        raise ProjectReleaseError("WRITER_PACKET_INVALID", "writer packet claims must be objects")
    if packet_claims != approved_rows:
        raise ProjectReleaseError("WRITER_PACKET_STALE", "writer packet whitelist differs from the current projection")
    whitelist = {row["claim_id"] for row in packet_claims}

    manuscript_sha256 = _sha256_bytes(markdown.encode("utf-8"))
    if lineage.get("manuscript_sha256") != manuscript_sha256:
        raise ProjectReleaseError("MANUSCRIPT_LINEAGE_DRIFT", "lineage does not bind the authoritative manuscript")
    if lineage.get("projection_sha256") != projection_sha256:
        raise ProjectReleaseError("MANUSCRIPT_LINEAGE_DRIFT", "lineage does not bind the current projection")

    sections = split_manuscript_sections(markdown)
    sections_by_id = {section["id"]: section for section in sections}
    section_ids = set(sections_by_id)
    pending_section_ids = {row["section_id"] for row in pending}
    if not pending_section_ids <= section_ids:
        raise ProjectReleaseError(
            "MANUSCRIPT_LINEAGE_DRIFT",
            "pending scientific edits reference an unknown manuscript section",
        )
    reference_count = _validate_references(sections)
    entries = manuscript_lineage_entries(lineage)
    if not all(isinstance(entry, dict) for entry in entries):
        raise ProjectReleaseError("MANUSCRIPT_LINEAGE_INVALID", "lineage claim entries must be objects")
    referenced: set[str] = set()
    for entry in entries:
        claim_id = entry.get("claim_id")
        if not isinstance(claim_id, str) or not claim_id:
            raise ProjectReleaseError("MANUSCRIPT_LINEAGE_INVALID", "lineage entries require claim_id")
        projected = projection_by_id.get(claim_id)
        if projected is None or claim_id not in whitelist:
            raise ProjectReleaseError("CLAIM_NOT_WHITELISTED", "manuscript lineage references a claim outside the writer whitelist")
        if projected.get("decision") in {"BLOCKED", "HUMAN_REQUIRED"}:
            raise ProjectReleaseError("CLAIM_NOT_APPROVED", "blocked or human-required claims cannot enter the manuscript")
        if claim_id in referenced:
            raise ProjectReleaseError(
                "MANUSCRIPT_LINEAGE_DRIFT",
                "each lineage claim must appear exactly once",
            )
        section_id = entry.get("section_id")
        if section_id is not None and section_id not in section_ids:
            raise ProjectReleaseError("MANUSCRIPT_LINEAGE_DRIFT", "lineage references an unknown manuscript section")
        text_span = entry.get("text_span") or entry.get("manuscript_text") or entry.get("text")
        if text_span is not None:
            if not isinstance(text_span, str) or not text_span:
                raise ProjectReleaseError("MANUSCRIPT_LINEAGE_DRIFT", "lineage text span is absent from the manuscript")
            bound_text = sections_by_id[section_id]["body"] if section_id is not None else markdown
            span_may_drift = (
                allow_pending_text_span_drift
                and section_id is not None
                and section_id in pending_section_ids
            )
            if not span_may_drift and _literal_occurrence_count(bound_text, text_span) != 1:
                raise ProjectReleaseError(
                    "MANUSCRIPT_LINEAGE_DRIFT",
                    "lineage text span must occur exactly once in its bound manuscript section",
                )
        referenced.add(claim_id)

    marker_ids = [match.group(1) or match.group(2) for match in _CLAIM_MARKER_RE.finditer(markdown)]
    if set(marker_ids) != referenced or len(marker_ids) != len(set(marker_ids)):
        raise ProjectReleaseError(
            "MANUSCRIPT_LINEAGE_DRIFT",
            "manuscript claim markers and lineage claims must match one-to-one",
        )

    visible_markdown = _without_docx_code_blocks(markdown)
    image_paths: list[str] = []
    for line in visible_markdown.splitlines():
        if not _IMAGE_MARKER_RE.search(line):
            continue
        image_match = _CANONICAL_IMAGE_RE.fullmatch(line)
        if image_match is None:
            raise ProjectReleaseError(
                "IMAGE_INVALID",
                "release images must use standalone ![alt](project-relative-path) syntax without titles",
            )
        image_paths.append(image_match.group(2))
    for image_path in image_paths:
        _validated_image(project_path, image_path)

    return {
        "status": "valid",
        "project_id": metrics["project_id"],
        "manuscript_sha256": manuscript_sha256,
        "projection_sha256": projection_sha256,
        "claim_reference_count": len(referenced),
        "approved_claim_ids": sorted(whitelist),
        "reference_count": reference_count,
        "image_count": len(image_paths),
        "image_paths": image_paths,
    }


def validate_manuscript_lineage(project: Path, markdown: str) -> dict[str, Any]:
    """Validate current Task4 state, manuscript lineage, citations, and images."""
    return _validate_manuscript_lineage(project, markdown)


def bind_authoritative_draft(
    project: Path,
    manuscript_input: Path,
    lineage_input: Path,
) -> dict[str, Any]:
    """Validate and bind exact provider outputs to the one canonical draft location."""
    project_path = Path(project).resolve()
    try:
        manuscript_bytes = Path(manuscript_input).read_bytes()
        lineage_bytes = Path(lineage_input).read_bytes()
        manuscript = manuscript_bytes.decode("utf-8")
        lineage = json.loads(lineage_bytes.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProjectReleaseError(
            "DRAFT_BIND_INPUT_INVALID",
            "provider manuscript and lineage must be readable UTF-8 files",
        ) from exc
    if not isinstance(lineage, dict):
        raise ProjectReleaseError("DRAFT_BIND_INPUT_INVALID", "provider lineage must be an object")
    validation = _validate_manuscript_lineage(
        project_path,
        manuscript,
        lineage_override=lineage,
    )
    manuscript_path = project_path / "04_first_draft" / "first_draft.md"
    lineage_path = project_path / "04_first_draft" / "manuscript_lineage.json"
    for destination, payload in (
        (manuscript_path, manuscript_bytes),
        (lineage_path, lineage_bytes),
    ):
        if destination.exists() and destination.read_bytes() != payload:
            raise ProjectReleaseError(
                "DRAFT_BIND_CONFLICT",
                "canonical draft already exists with different bytes",
            )
    _atomic_write(manuscript_path, manuscript_bytes)
    _atomic_write(lineage_path, lineage_bytes)
    state_path = project_path / "00_brief" / "review_state.json"
    state = _read_json(state_path, "PROJECT_STATE_INVALID")
    if not isinstance(state, dict):
        raise ProjectReleaseError("PROJECT_STATE_INVALID", "review state must be an object")
    updated_state = {**state, "current_stage": "drafting", "status": "in_progress"}
    _atomic_write(state_path, _json_bytes(updated_state))
    return {
        "claim_reference_count": validation["claim_reference_count"],
        "image_count": validation["image_count"],
        "project_id": validation["project_id"],
    }


def validated_draft_manuscript_lineage(project: Path, markdown: str) -> dict[str, Any]:
    """Read and validate authoritative lineage for the researcher draft view.

    Pending scientific edits may temporarily invalidate text-span placement only in
    their bound sections. Manuscript/projection hashes, writer-packet binding, the
    claim whitelist, references, section bindings, and images remain mandatory.
    """
    project_path = Path(project)
    lineage_path = validate_project_file_path(
        project_path,
        Path("04_first_draft/manuscript_lineage.json"),
        "MANUSCRIPT_LINEAGE_INVALID",
    )
    lineage = _read_json(lineage_path, "MANUSCRIPT_LINEAGE_INVALID")
    if not isinstance(lineage, dict):
        raise ProjectReleaseError("MANUSCRIPT_LINEAGE_INVALID", "lineage must be an object")
    pending = _pending_scientific_edits(lineage)
    if not pending:
        validate_manuscript_lineage(project_path, markdown)
        return lineage
    _validate_manuscript_lineage(
        project_path,
        markdown,
        lineage_override=lineage,
        allow_pending_scientific_edits=True,
        allow_pending_text_span_drift=True,
    )
    return lineage


def refreshed_manuscript_lineage(
    project: Path,
    current_markdown: str,
    candidate_markdown: str,
    *,
    section_id: str | None = None,
    scientific_reasons: list[str] | None = None,
) -> dict[str, Any]:
    """Refresh lineage, retaining scientific edits as release-blocking pending revisions."""
    project_path = Path(project)
    lineage_path = validate_project_file_path(
        project_path, Path("04_first_draft/manuscript_lineage.json"), "MANUSCRIPT_LINEAGE_INVALID"
    )
    lineage = _read_json(lineage_path, "MANUSCRIPT_LINEAGE_INVALID")
    if not isinstance(lineage, dict):
        raise ProjectReleaseError("MANUSCRIPT_LINEAGE_INVALID", "lineage must be an object")
    pending = _pending_scientific_edits(lineage)
    current_sha256 = _sha256_bytes(current_markdown.encode("utf-8"))
    if lineage.get("manuscript_sha256") != current_sha256:
        raise ProjectReleaseError(
            "MANUSCRIPT_LINEAGE_DRIFT",
            "lineage does not bind the current authoritative manuscript",
        )
    if not pending:
        validate_manuscript_lineage(project_path, current_markdown)

    updated = dict(lineage)
    updated["manuscript_sha256"] = _sha256_bytes(candidate_markdown.encode("utf-8"))
    reasons = list(dict.fromkeys(scientific_reasons or []))
    if any(not isinstance(reason, str) or not reason for reason in reasons):
        raise ProjectReleaseError(
            "MANUSCRIPT_LINEAGE_INVALID",
            "scientific edit reasons must be nonempty text",
        )
    if reasons and not section_id:
        raise ProjectReleaseError(
            "MANUSCRIPT_LINEAGE_INVALID",
            "scientific edits require a manuscript section",
        )

    touched_pending = False
    if section_id is not None:
        current_sections = {row["id"]: row for row in split_manuscript_sections(current_markdown)}
        candidate_sections = {row["id"]: row for row in split_manuscript_sections(candidate_markdown)}
        if section_id not in current_sections or section_id not in candidate_sections:
            raise ProjectReleaseError(
                "MANUSCRIPT_SECTIONS_INVALID",
                "scientific edit section is missing",
            )
        existing = next((row for row in pending if row["section_id"] == section_id), None)
        candidate_body = candidate_sections[section_id]["body"]
        if existing is not None and candidate_body == existing["verified_body"]:
            pending = [row for row in pending if row["section_id"] != section_id]
            touched_pending = True
        elif reasons:
            if existing is None:
                pending.append(
                    {
                        "section_id": section_id,
                        "verified_body": current_sections[section_id]["body"],
                        "reasons": reasons,
                    }
                )
            else:
                existing["reasons"] = list(dict.fromkeys([*existing["reasons"], *reasons]))
            touched_pending = True

    pending.sort(key=lambda row: row["section_id"])
    if pending:
        updated["pending_scientific_edits"] = pending
    elif "pending_scientific_edits" in lineage or touched_pending:
        updated["pending_scientific_edits"] = []
    else:
        updated.pop("pending_scientific_edits", None)
    if not pending:
        _validate_manuscript_lineage(project_path, candidate_markdown, lineage_override=updated)
    return updated


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _json_bytes(value: Any) -> bytes:
    try:
        return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProjectReleaseError("QUALITY_REPORT_INVALID", "quality report must be finite JSON") from exc


def _release_status(project: Path) -> str:
    state = _read_json(project / "00_brief" / "review_state.json", "PROJECT_STATE_INVALID")
    candidates = []
    if isinstance(state, dict):
        candidates.extend((state.get("release_status"), state.get("review_status"), state.get("status")))
        brief = state.get("brief")
        if isinstance(brief, dict):
            candidates.extend((brief.get("release_status"), brief.get("review_status"), brief.get("status")))
    return "DOMAIN_EXPERT_REVIEWED" if "DOMAIN_EXPERT_REVIEWED" in candidates else "AI_REVIEWED_BENCHMARK"


def _validate_docx_attributions(docx_path: Path, figure_validation: dict[str, Any]) -> None:
    required = [
        row["attribution"]
        for row in figure_validation.get("figures", [])
        if isinstance(row, dict)
        and isinstance(row.get("attribution"), str)
        and row["attribution"].strip()
    ]
    try:
        with zipfile.ZipFile(docx_path) as archive:
            names = set(archive.namelist())
            required_parts = {"[Content_Types].xml", "word/document.xml"}
            if not required_parts <= names:
                raise ProjectReleaseError(
                    "DOCX_EXPORT_FAILED",
                    "DOCX converter output is missing required document parts",
                )
            ET.fromstring(archive.read("[Content_Types].xml"))
            text_parts = ["".join(ET.fromstring(archive.read("word/document.xml")).itertext())]
            for name in ("word/footnotes.xml", "word/endnotes.xml"):
                if name in names:
                    text_parts.append("".join(ET.fromstring(archive.read(name)).itertext()))
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
        raise ProjectReleaseError("DOCX_EXPORT_FAILED", "DOCX converter output is invalid") from exc
    document_text = " ".join("\n".join(text_parts).split())
    if any(" ".join(attribution.split()) not in document_text for attribution in required):
        raise ProjectReleaseError(
            "DOCX_ATTRIBUTION_MISSING",
            "released DOCX must include every required source attribution",
        )


def _release_figure_validation(
    project: Path,
    *,
    approved_claim_ids: list[str],
    manuscript_sha256: str,
    manuscript_image_paths: list[str],
    manuscript_markdown: str,
) -> dict[str, Any]:
    manifest_relative = Path("03_figure_redraw/figure_manifest.json")
    validate_project_path_components(project, (manifest_relative,))
    manifest_path = project / manifest_relative
    if manifest_path.is_file():
        manifest = _read_json(manifest_path, "FIGURE_POLICY_INVALID")
    else:
        manifest = {"schema_version": "review-writer-figure-manifest.v1", "figures": []}
    image_files_by_markdown_path = {
        image_path: _validated_image(project, image_path)
        for image_path in manuscript_image_paths
    }
    try:
        return validate_figure_policy(
            manifest,
            approved_claim_ids=approved_claim_ids,
            manuscript_sha256=manuscript_sha256,
            manuscript_image_paths=manuscript_image_paths,
            manuscript_markdown=manuscript_markdown,
            image_files_by_markdown_path=image_files_by_markdown_path,
        )
    except FigurePolicyError as exc:
        raise ProjectReleaseError(exc.code, str(exc).split(": ", 1)[-1]) from exc


def project_figure_validation_is_current(
    project: Path,
    validation: Any,
    *,
    manuscript_sha256: str,
) -> bool:
    """Check whether stored figure validation still binds current manifest and image bytes."""
    project_path = Path(project)
    manifest_relative = Path("03_figure_redraw/figure_manifest.json")
    try:
        manifest_path = validate_project_file_path(
            project_path,
            manifest_relative,
            "FIGURE_POLICY_INVALID",
        )
        manifest = _read_json(manifest_path, "FIGURE_POLICY_INVALID")
        raw_figures = manifest.get("figures") if isinstance(manifest, dict) else None
        if not isinstance(raw_figures, list):
            return False
        image_files: dict[str, Path] = {}
        for row in raw_figures:
            if not isinstance(row, dict) or row.get("figure_type") == "FIGURE_BRIEF_PLACEHOLDER":
                return False
            markdown_path = row.get("markdown_path")
            if not isinstance(markdown_path, str) or not markdown_path:
                return False
            image_files[markdown_path] = _validated_image(project_path, markdown_path)
    except (OSError, ProjectReleaseError):
        return False
    return figure_validation_is_current(
        validation,
        manuscript_sha256=manuscript_sha256,
        manifest=manifest,
        image_files_by_markdown_path=image_files,
    )


def _restore_release(paths: tuple[Path, ...], previous: dict[Path, bytes | None]) -> None:
    for path in paths:
        payload = previous[path]
        if payload is None:
            path.unlink(missing_ok=True)
        else:
            _atomic_write(path, payload)


def build_project_release(
    project: Path,
    python_executable: Path = Path(sys.executable),
) -> dict[str, Any]:
    """Snapshot and export one validated authoritative manuscript without editing it."""
    with PROJECT_RELEASE_LOCK:
        return _build_project_release_unlocked(project, python_executable)


def _build_project_release_unlocked(
    project: Path,
    python_executable: Path,
) -> dict[str, Any]:
    project_path = Path(project)
    source = validate_project_file_path(
        project_path, Path("04_first_draft/first_draft.md"), "MANUSCRIPT_INVALID"
    )
    try:
        manuscript_bytes = source.read_bytes()
        markdown = manuscript_bytes.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ProjectReleaseError("MANUSCRIPT_INVALID", "authoritative manuscript must be readable UTF-8") from exc

    validation = validate_manuscript_lineage(project_path, markdown)
    figure_validation = _release_figure_validation(
        project_path,
        approved_claim_ids=validation["approved_claim_ids"],
        manuscript_sha256=validation["manuscript_sha256"],
        manuscript_image_paths=validation["image_paths"],
        manuscript_markdown=markdown,
    )
    stage = project_path / "05_final_audit"
    snapshot = stage / "final_draft.md"
    docx = stage / "final_draft.docx"
    quality = stage / "quality_report.json"
    release_paths = (snapshot, docx, quality)
    _reject_reparse_components(
        project_path,
        tuple(path.relative_to(project_path) for path in release_paths),
    )
    previous = {path: path.read_bytes() if path.is_file() else None for path in release_paths}
    converter = Path(__file__).resolve().parents[2] / "skills" / "review-export-docx" / "scripts" / "md2docx.py"
    temporary_docx: Path | None = None

    try:
        _atomic_write(snapshot, manuscript_bytes)
        if not converter.is_file():
            raise ProjectReleaseError("DOCX_CONVERTER_MISSING", "repository DOCX converter is unavailable")
        with tempfile.NamedTemporaryFile(
            dir=stage,
            prefix=".final_draft.",
            suffix=".docx.tmp",
            delete=False,
        ) as handle:
            temporary_docx = Path(handle.name)
        temporary_docx.unlink()
        try:
            completed = subprocess.run(
                [
                    str(Path(python_executable)),
                    str(converter),
                    "--input",
                    str(snapshot),
                    "--output",
                    str(temporary_docx),
                ],
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ProjectReleaseError("DOCX_EXPORT_FAILED", "DOCX converter could not complete") from exc
        if completed.returncode != 0 or not temporary_docx.is_file() or temporary_docx.stat().st_size <= 0:
            raise ProjectReleaseError("DOCX_EXPORT_FAILED", "DOCX converter did not produce a document")
        if not zipfile.is_zipfile(temporary_docx):
            raise ProjectReleaseError("DOCX_EXPORT_FAILED", "DOCX converter output is invalid")
        _validate_docx_attributions(temporary_docx, figure_validation)

        docx_bytes = temporary_docx.read_bytes()
        docx_sha256 = _sha256_bytes(docx_bytes)
        status = _release_status(project_path)
        existing_report = _read_json(quality, "QUALITY_REPORT_INVALID") if quality.is_file() else {}
        if not isinstance(existing_report, dict):
            raise ProjectReleaseError("QUALITY_REPORT_INVALID", "quality report must be an object")
        report = {
            **existing_report,
            "schema_version": "project-release.v1",
            "status": status,
            "release_status": status,
            "manuscript_sha256": validation["manuscript_sha256"],
            "docx_sha256": docx_sha256,
            "figure_validation": figure_validation,
            "release": {
                "status": status,
                "manuscript_sha256": validation["manuscript_sha256"],
                "docx_sha256": docx_sha256,
            },
        }
        _atomic_write(docx, docx_bytes)
        _atomic_write(quality, _json_bytes(report))
        return {
            "status": status,
            "release_status": status,
            "manuscript_sha256": validation["manuscript_sha256"],
            "docx_sha256": docx_sha256,
            "snapshot": snapshot,
            "docx": docx,
            "quality_report": quality,
        }
    except Exception:
        _restore_release(release_paths, previous)
        raise
    finally:
        if temporary_docx is not None:
            temporary_docx.unlink(missing_ok=True)
