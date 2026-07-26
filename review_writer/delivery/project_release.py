"""Single-source manuscript editing and deterministic project release."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from review_writer.project.vertical_review import VerticalReviewError, benchmark_metrics


_ATX_HEADING_RE = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\((?:<([^>]+)>|([^\s)]+))(?:\s+['\"][^'\"]*['\"])?\)")
_REFERENCE_RE = re.compile(r"^\s*(?:\[(\d+)\]|(\d+)[.)])\s+\S")
_CITATION_RE = re.compile(r"(?<!!)\[([0-9][0-9,;\s\-–—]*)\]")
_CLAIM_MARKER_RE = re.compile(
    r"(?:\[claim:([A-Za-z0-9._:-]+)\]|<!--\s*claim(?:_id)?\s*:\s*([A-Za-z0-9._:-]+)\s*-->)",
    flags=re.IGNORECASE,
)


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


def validate_project_file_path(project: Path, relative: Path, code: str) -> Path:
    """Return a required project file after rejecting symlink/reparse components."""
    _reject_reparse_components(project, (relative,))
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


def _without_fenced_blocks(markdown: str) -> str:
    visible: list[str] = []
    fence: str | None = None
    for line in markdown.splitlines(keepends=True):
        match = _FENCE_RE.match(line.rstrip("\r\n"))
        if match:
            marker = match.group(1)[0]
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
            visible.append("\n" if line.endswith(("\n", "\r")) else "")
        elif fence is None:
            visible.append(line)
        else:
            visible.append("\n" if line.endswith(("\n", "\r")) else "")
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
    raw = unquote(relative_url.strip())
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


def _lineage_entries(lineage: dict[str, Any]) -> list[dict[str, Any]]:
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


def _validate_manuscript_lineage(
    project: Path,
    markdown: str,
    *,
    lineage_override: dict[str, Any] | None = None,
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
    lineage_path = validate_project_file_path(
        project_path, Path("04_first_draft/manuscript_lineage.json"), "MANUSCRIPT_LINEAGE_INVALID"
    )
    projection = _read_jsonl(projection_path, "PROJECTION_INVALID")
    writer_packet = _read_json(writer_path, "WRITER_PACKET_INVALID")
    lineage = lineage_override if lineage_override is not None else _read_json(
        lineage_path, "MANUSCRIPT_LINEAGE_INVALID"
    )
    if not isinstance(writer_packet, dict) or not isinstance(lineage, dict):
        raise ProjectReleaseError("RELEASE_STATE_INVALID", "writer packet and lineage must be objects")

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
    reference_count = _validate_references(sections)
    entries = _lineage_entries(lineage)
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
        section_id = entry.get("section_id")
        if section_id is not None and section_id not in section_ids:
            raise ProjectReleaseError("MANUSCRIPT_LINEAGE_DRIFT", "lineage references an unknown manuscript section")
        text_span = entry.get("text_span") or entry.get("manuscript_text") or entry.get("text")
        if text_span is not None:
            if not isinstance(text_span, str) or not text_span:
                raise ProjectReleaseError("MANUSCRIPT_LINEAGE_DRIFT", "lineage text span is absent from the manuscript")
            bound_text = sections_by_id[section_id]["body"] if section_id is not None else markdown
            if text_span not in bound_text:
                raise ProjectReleaseError(
                    "MANUSCRIPT_LINEAGE_DRIFT",
                    "lineage text span is absent from its bound manuscript section",
                )
        referenced.add(claim_id)

    marker_ids = {match.group(1) or match.group(2) for match in _CLAIM_MARKER_RE.finditer(markdown)}
    if not marker_ids <= referenced:
        raise ProjectReleaseError("MANUSCRIPT_LINEAGE_DRIFT", "manuscript claim markers are absent from lineage")

    visible_markdown = _without_fenced_blocks(markdown)
    image_paths = [match.group(1) or match.group(2) for match in _IMAGE_RE.finditer(visible_markdown)]
    for image_path in image_paths:
        _validated_image(project_path, image_path)

    return {
        "status": "valid",
        "project_id": metrics["project_id"],
        "manuscript_sha256": manuscript_sha256,
        "projection_sha256": projection_sha256,
        "claim_reference_count": len(referenced),
        "reference_count": reference_count,
        "image_count": len(image_paths),
    }


def validate_manuscript_lineage(project: Path, markdown: str) -> dict[str, Any]:
    """Validate current Task4 state, manuscript lineage, citations, and images."""
    return _validate_manuscript_lineage(project, markdown)


def refreshed_manuscript_lineage(
    project: Path,
    current_markdown: str,
    candidate_markdown: str,
) -> dict[str, Any]:
    """Return lineage with only its manuscript hash refreshed after full candidate validation."""
    project_path = Path(project)
    validate_manuscript_lineage(project_path, current_markdown)
    lineage_path = validate_project_file_path(
        project_path, Path("04_first_draft/manuscript_lineage.json"), "MANUSCRIPT_LINEAGE_INVALID"
    )
    lineage = _read_json(lineage_path, "MANUSCRIPT_LINEAGE_INVALID")
    if not isinstance(lineage, dict):
        raise ProjectReleaseError("MANUSCRIPT_LINEAGE_INVALID", "lineage must be an object")
    updated = dict(lineage)
    updated["manuscript_sha256"] = _sha256_bytes(candidate_markdown.encode("utf-8"))
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
