#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import posixpath
import re
import shutil
import sys
import tempfile
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urlparse


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.project.vertical_review import (  # noqa: E402
    AWAITING_BRIEF_CONFIRMATION,
    VerticalReviewError,
    apply_risk_decisions,
    benchmark_metrics,
    confirm_review_brief,
)
from review_writer.acquisition.manifest_identity import normalize_doi  # noqa: E402
from review_writer.acquisition.manual_archive import DEFAULT_MAX_ARCHIVE_BYTES  # noqa: E402
from review_writer.delivery.project_release import (  # noqa: E402
    PROJECT_RELEASE_LOCK,
    build_project_release,
    is_reparse_component,
    manuscript_lineage_entries,
    refreshed_manuscript_lineage,
    replace_manuscript_section_body,
    split_manuscript_sections,
    validate_project_file_path,
    validate_project_path_components,
    validated_draft_manuscript_lineage,
)


_RESEARCHER_SHA256_RE = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{64}(?![0-9A-Fa-f])")
_RESEARCHER_PATH_TAIL = (
    r"(?:[^\r\n;,)\]}>`\"']*?\."
    r"(?:jsonl?|md|docx|pdf|png|jpe?g|svg|csv|tsv|txt)"
    r"|[^\r\n;,)\]}>`\"']*)"
)
_RESEARCHER_WINDOWS_PATH_RE = re.compile(
    rf"(?im)(?<![A-Za-z0-9])(?:[A-Z]:[\\/]|\\\\[A-Za-z0-9._$-]+[\\/]){_RESEARCHER_PATH_TAIL}"
)
_RESEARCHER_POSIX_PATH_RE = re.compile(
    r"(?m)(?<![:/A-Za-z0-9])/(?:home|tmp|var|mnt|opt|srv|root|Users|private|workspace|workspaces)"
    rf"(?:/|$){_RESEARCHER_PATH_TAIL}"
)
_RESEARCHER_INTERNAL_FILENAME_RE = re.compile(
    r"(?i)(?<![\w.-])(?:"
    r"claim_projection\.jsonl|final_audit_report\.(?:json|md)|final_draft\.(?:docx|md)|"
    r"first_draft\.md|manuscript_lineage\.json|merge_report\.md|quality_report\.(?:json|md)|"
    r"release_report\.md|remaining_issues\.md|writer_packet\.json"
    r")(?![\w.-])"
)
_DOI_RE = re.compile(r"(?i)\b10\.\d{4,9}/[^\s\]\[()<>]+")
_CITATION_RE = re.compile(r"\[[0-9][0-9,;\s\-–—]*\]")
_NUMBER_RE = re.compile(r"(?<![\w.])[-+−]?\d+(?:\.\d+)?(?:\s*(?:%|percent))?", re.IGNORECASE)
_SENTENCE_RE = re.compile(r".+?(?:[.!?。！？]+(?=\s|$)|$)", re.DOTALL)
_SCIENTIFIC_UNIT_RE = re.compile(
    r"(?i)^\s*(?:°\s*[CFK]|K|[ckmunµμ]?(?:mol|m|l|g|s|pa)|h(?:ours?|r)?|"
    r"min(?:utes?)?|sec(?:onds?)?|eq(?:uiv)?\.?|bar|atm|compounds?)\b"
)
_DOCUMENT_META_RE = re.compile(
    r"(?i)(?:\b(?:document|text|prose|section|paragraph|sentence|line|wording|readability|"
    r"navigation|format(?:ting)?|style|title|heading|clarity|flow|editorial|overview|version|revision)\b|"
    r"文档|文章|文字|文本|措辞|段落|句子|标题|章节|格式|样式|可读性|编辑|概述|版本|修订)"
)
_SCIENTIFIC_ASSERTION_RE = re.compile(
    r"(?i)\b(?:show(?:s|ed)?|demonstrat(?:e|es|ed)|indicat(?:e|es|ed)|"
    r"reveal(?:s|ed)?|establish(?:es|ed)?)\s+that\b"
)
_CHEMISTRY_TOKEN_RE = re.compile(
    r"(?i)(?:\b(?:mechanis(?:m|tic)|intermediate|radical|electron[ -]transfer|transition[ -]state|"
    r"oxidation|reduction|stereochem(?:istry|ical)|reaction[ -]pathway|molecular[ -]structure)\b|"
    r"机制|(?:分子|化学|立体)结构|结构式)"
)
_CHEMICAL_STRUCTURE_RE = re.compile(
    r"(?<!\w)(?:(?=[A-Za-z0-9]*\d)(?:[A-Z][a-z]?\d*){2,}|"
    r"[A-Z][a-z]?\s*(?:[-=≡–—])\s*[A-Z][a-z]?)(?!\w)"
)
SOURCE_ARCHIVE_RELATIVE = Path("00_sources/manual_upload/inbox/source_bundle.zip")
SOURCE_ARCHIVE_SUCCESS_STATUSES = frozenset({"DOWNLOADED", "IMPORTED", "VERIFIED_EXISTING"})


class DashboardHandler(BaseHTTPRequestHandler):
    review_root: Path
    library_app_path: Path
    discovery_app_path: Path
    matrix_app_path: Path
    blueprint_app_path: Path
    sections_app_path: Path
    figures_app_path: Path
    draft_app_path: Path
    final_app_path: Path
    review_app_path: Path

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    @property
    def metadata_dir(self) -> Path:
        return self.review_root / "review-library" / "metadata" / "papers"

    @property
    def registry_path(self) -> Path:
        return self.review_root / "review-library" / "registry" / "papers.jsonl"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/review")
            self.end_headers()
        elif parsed.path == "/review":
            self.send_file(self.review_app_path, "text/html; charset=utf-8")
        elif parsed.path == "/library":
            self.send_file(self.library_app_path, "text/html; charset=utf-8")
        elif parsed.path == "/discovery":
            self.send_file(self.discovery_app_path, "text/html; charset=utf-8")
        elif parsed.path == "/matrix":
            self.send_file(self.matrix_app_path, "text/html; charset=utf-8")
        elif parsed.path == "/blueprint":
            self.send_file(self.blueprint_app_path, "text/html; charset=utf-8")
        elif parsed.path == "/sections":
            self.send_file(self.sections_app_path, "text/html; charset=utf-8")
        elif parsed.path == "/figures":
            self.send_file(self.figures_app_path, "text/html; charset=utf-8")
        elif parsed.path == "/draft":
            self.send_file(self.draft_app_path, "text/html; charset=utf-8")
        elif parsed.path == "/final":
            self.send_file(self.final_app_path, "text/html; charset=utf-8")
        elif parsed.path.startswith("/assets/"):
            self.handle_static_asset(parsed.path)
        elif parsed.path == "/api/projects":
            self.handle_projects()
        elif parsed.path == "/api/papers":
            self.handle_papers()
        elif parsed.path == "/api/discovery-projects":
            self.handle_discovery_projects()
        elif parsed.path == "/api/checkpoints":
            self.send_json(checkpoint_payload(self.review_root))
        elif parsed.path.startswith("/api/project/") and parsed.path.endswith("/source"):
            project_id = project_id_from_route(parsed.path, "source")
            if project_id is None:
                self.send_error(HTTPStatus.NOT_FOUND, "project route not found")
                return
            self.handle_project_source_get(project_id, parse_qs(parsed.query).get("source_id", [""])[0])
        elif parsed.path.startswith("/api/project/") and parsed.path.endswith("/review-state"):
            project_id = project_id_from_route(parsed.path, "review-state")
            if project_id is None:
                self.send_error(HTTPStatus.NOT_FOUND, "project route not found")
                return
            self.handle_project_review_state_get(project_id)
        elif parsed.path.startswith("/api/project/") and parsed.path.endswith("/draft"):
            project_id = project_id_from_route(parsed.path, "draft")
            if project_id is None:
                self.send_error(HTTPStatus.NOT_FOUND, "project route not found")
                return
            self.handle_project_draft_get(project_id)
        elif parsed.path.startswith("/api/project/"):
            parts = parsed.path.strip("/").split("/")
            if len(parts) == 4:
                project_id = unquote(parts[2])
                stage = unquote(parts[3])
                self.handle_project_stage_get(project_id, stage)
            else:
                self.send_error(HTTPStatus.NOT_FOUND, "project stage not found")
        elif parsed.path.startswith("/api/discovery/"):
            project_id = unquote(parsed.path.rsplit("/", 1)[-1])
            self.handle_discovery_get(project_id)
        elif parsed.path.startswith("/api/metadata/"):
            paper_id = unquote(parsed.path.rsplit("/", 1)[-1])
            self.handle_metadata_get(paper_id)
        elif parsed.path.startswith("/api/local/metadata/"):
            paper_id = unquote(parsed.path.rsplit("/", 1)[-1])
            self.handle_metadata_get(paper_id)
        elif parsed.path.startswith("/api/markdown/"):
            paper_id = unquote(parsed.path.rsplit("/", 1)[-1])
            self.handle_markdown_get(paper_id)
        elif parsed.path.startswith("/api/local/markdown/"):
            paper_id = unquote(parsed.path.rsplit("/", 1)[-1])
            self.handle_markdown_get(paper_id)
        elif parsed.path == "/file":
            query = parse_qs(parsed.query)
            path = query.get("path", [""])[0]
            paper_id = query.get("paper_id", [""])[0]
            self.handle_file(path, paper_id)
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/metadata/"):
            paper_id = unquote(parsed.path.rsplit("/", 1)[-1])
            self.handle_metadata_put(paper_id)
            return
        if parsed.path.startswith("/api/project/") and parsed.path.endswith("/draft"):
            project_id = project_id_from_route(parsed.path, "draft")
            if project_id is None:
                self.send_error(HTTPStatus.NOT_FOUND, "project route not found")
                return
            self.handle_project_draft_put(project_id)
            return
        if parsed.path.startswith("/api/project/") and parsed.path.endswith("/risk-decisions"):
            project_id = project_id_from_route(parsed.path, "risk-decisions")
            if project_id is None:
                self.send_error(HTTPStatus.NOT_FOUND, "project route not found")
                return
            self.handle_project_risk_decisions_put(project_id)
            return
        if parsed.path.startswith("/api/project/") and parsed.path.endswith("/review-state"):
            project_id = project_id_from_route(parsed.path, "review-state")
            if project_id is None:
                self.send_error(HTTPStatus.NOT_FOUND, "project route not found")
                return
            self.handle_project_review_state_put(project_id)
            return
        if parsed.path.startswith("/api/discovery/"):
            project_id = unquote(parsed.path.rsplit("/", 1)[-1])
            query = parse_qs(parsed.query)
            self.handle_discovery_put(project_id, confirm=bool(query.get("confirm")))
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/project/") and parsed.path.endswith("/source-archive"):
            project_id = project_id_from_route(parsed.path, "source-archive")
            if project_id is None:
                self.send_error(HTTPStatus.NOT_FOUND, "project route not found")
                return
            replace = parse_qs(parsed.query).get("replace", [""])[0]
            self.handle_project_source_archive_post(project_id, replace=replace)
            return
        if parsed.path.startswith("/api/project/") and parsed.path.endswith("/export-docx"):
            project_id = project_id_from_route(parsed.path, "export-docx")
            if project_id is None:
                self.send_error(HTTPStatus.NOT_FOUND, "project route not found")
                return
            self.handle_project_export_docx(project_id)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def handle_project_source_archive_post(self, project_id: str, *, replace: str) -> None:
        try:
            project = project_dir(self.review_root, project_id)
        except ValueError:
            self.send_error(HTTPStatus.BAD_REQUEST, "invalid project")
            return
        if not project.is_dir():
            self.send_error(HTTPStatus.NOT_FOUND, "project not found")
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self.send_error(HTTPStatus.BAD_REQUEST, "archive length is invalid")
            return
        if length <= 0:
            self.send_error(HTTPStatus.BAD_REQUEST, "archive is empty")
            return
        if length > DEFAULT_MAX_ARCHIVE_BYTES:
            self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "archive exceeds the size limit")
            return
        archive_path = project / SOURCE_ARCHIVE_RELATIVE
        try:
            validate_project_path_components(project, (SOURCE_ARCHIVE_RELATIVE,))
        except ValueError:
            self.send_error(HTTPStatus.BAD_REQUEST, "archive destination is unavailable")
            return
        state = read_json_if_exists(project / "00_brief" / "review_state.json") or {}
        blockers = state.get("blockers") if isinstance(state, dict) else []
        replacement_allowed = (
            replace == "invalid"
            and isinstance(blockers, list)
            and any(
                isinstance(blocker, str)
                and blocker.startswith(("SOURCE_ARCHIVE_", "MANUAL_ARCHIVE_"))
                for blocker in blockers
            )
        )
        if archive_path.exists() and not replacement_allowed:
            self.send_error(HTTPStatus.CONFLICT, "a source archive is already awaiting processing")
            return
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            validate_project_path_components(project, (SOURCE_ARCHIVE_RELATIVE,))
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=archive_path.parent,
                prefix=f".{archive_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                remaining = length
                while remaining:
                    chunk = self.rfile.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError("archive body is incomplete")
                    handle.write(chunk)
                    remaining -= len(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            if not zipfile.is_zipfile(temporary):
                raise ValueError("archive is not a valid ZIP")
            validate_project_path_components(project, (SOURCE_ARCHIVE_RELATIVE,))
            os.replace(temporary, archive_path)
            temporary = None
        except (OSError, ValueError):
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            self.send_error(HTTPStatus.BAD_REQUEST, "archive is not a valid ZIP")
            return
        self.send_json(
            {"status": "received", "message": "压缩包已接收，正在核验来源。"},
            status=HTTPStatus.CREATED,
        )

    def handle_project_export_docx(self, project_id: str) -> None:
        try:
            result = export_project_docx(self.review_root, project_id)
        except ValueError as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        if result.get("http_status"):
            self.send_error(HTTPStatus(result.pop("http_status")), str(result.pop("error")))
            return
        self.send_json(result)

    def handle_projects(self) -> None:
        self.send_json(list_review_projects(self.review_root))

    def handle_papers(self) -> None:
        papers = []
        for path in sorted(self.metadata_dir.glob("*.metadata.json")):
            try:
                meta = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            structured_tags = value_of(meta.get("structured_tags")) or {}
            structured_values = list(structured_tags.values()) if isinstance(structured_tags, dict) else []
            papers.append(
                {
                    "paper_id": meta.get("paper_id"),
                    "title": value_of(meta.get("title")),
                    "authors": value_of(meta.get("authors")) or [],
                    "year": value_of(meta.get("year")),
                    "journal": value_of(meta.get("journal")),
                    "doi": value_of(meta.get("doi")),
                    "structured_tags": structured_tags,
                    "tags": structured_values,
                    "human_review_status": (meta.get("human_review") or {}).get("status"),
                    "needs_human_check": (meta.get("quality") or {}).get("needs_human_check"),
                }
            )
        self.send_json(papers)

    def handle_discovery_projects(self) -> None:
        self.send_json([p for p in list_review_projects(self.review_root) if p.get("has_discovery")])

    def handle_discovery_get(self, project_id: str) -> None:
        try:
            path = self.discovery_path(project_id)
        except ValueError as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        if not path.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "discovery data not found")
            return
        self.send_file(path, "application/json; charset=utf-8")

    def handle_discovery_put(self, project_id: str, confirm: bool = False) -> None:
        try:
            path = self.discovery_path(project_id)
        except ValueError as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, f"invalid discovery json: {exc}")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
        selected = selected_from_combined(data.get("results", []), project_id)
        selected["human_confirmed"] = bool(confirm)
        (path.parent / "selected_discovery_results.json").write_text(
            json.dumps(selected, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (path.parent / "human_check_state.json").write_text(
            json.dumps(
                {
                    "project_id": project_id,
                    "status": "confirmed" if confirm else "pending",
                    "confirmed_at": now_utc() if confirm else None,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        self.send_json({"ok": True, "confirmed": confirm})

    def handle_project_draft_get(self, project_id: str) -> None:
        try:
            project = project_dir(self.review_root, project_id)
        except ValueError as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        if not project.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "project not found")
            return
        try:
            payload = project_draft_payload(self.review_root, project_id)
        except ValueError as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        self.send_json(payload)

    def handle_project_source_get(self, project_id: str, source_id: str) -> None:
        try:
            project = project_dir(self.review_root, project_id)
        except ValueError as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        if not project.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "project not found")
            return
        if not source_id:
            self.send_error(HTTPStatus.BAD_REQUEST, "source_id is required")
            return
        try:
            source = project_source_pdf(project, source_id)
        except (OSError, ValueError):
            self.send_error(HTTPStatus.FORBIDDEN, "project source is unavailable")
            return
        if source is None:
            self.send_error(HTTPStatus.NOT_FOUND, "project source not found")
            return
        self.send_file(source, "application/pdf")

    def handle_project_review_state_get(self, project_id: str) -> None:
        try:
            project = project_dir(self.review_root, project_id)
        except ValueError as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        if not project.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "project not found")
            return
        self.send_json(project_review_state_payload(self.review_root, project_id))

    def handle_project_review_state_put(self, project_id: str) -> None:
        try:
            project = project_dir(self.review_root, project_id)
        except ValueError as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        if not project.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "project not found")
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            if isinstance(data, dict) and "action" in data:
                valid_confirmation = (
                    set(data) == {"action", "project_id"}
                    and data.get("action") == "confirm_brief"
                    and data.get("project_id") == project_id
                )
                if not valid_confirmation:
                    raise ValueError("brief confirmation requires exactly action and matching project_id")
                state = confirm_review_brief(project)
            else:
                state = write_project_review_state(self.review_root, project_id, data)
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, f"invalid review state: {exc}")
            return
        self.send_json(
            {
                "ok": True,
                "project_id": project_id,
                "current_stage": state["current_stage"],
                "status": state["status"],
            }
        )

    def handle_project_risk_decisions_put(self, project_id: str) -> None:
        try:
            project = project_dir(self.review_root, project_id)
        except ValueError as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        if not project.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "project not found")
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            result = write_project_risk_decisions(self.review_root, project_id, data)
        except json.JSONDecodeError:
            self.send_error(HTTPStatus.BAD_REQUEST, "The decisions could not be read.")
            return
        except VerticalReviewError as exc:
            message = (
                "These decisions are no longer current. Refresh and review them again."
                if exc.code == "RISK_TARGET_STALE"
                else "The decisions were not saved. Check each target and try again."
            )
            self.send_error(HTTPStatus.BAD_REQUEST, message)
            return
        except ValueError:
            self.send_error(HTTPStatus.BAD_REQUEST, "The decisions were not saved. Check each target and try again.")
            return
        self.send_json(result)

    def handle_project_stage_get(self, project_id: str, stage: str) -> None:
        try:
            project = project_dir(self.review_root, project_id)
        except ValueError as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        if not project.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "project not found")
            return
        payloads = {
            "cockpit": project_cockpit_payload,
            "sources": project_source_handoff_payload,
            "progress": project_progress_payload,
            "evidence": project_evidence_payload,
            "risk-packet": project_risk_payload,
            "matrix": project_matrix_payload,
            "blueprint": project_blueprint_payload,
            "sections": project_sections_payload,
            "figures": project_figures_payload,
            "final": project_final_payload,
        }
        builder = payloads.get(stage)
        if not builder:
            self.send_error(HTTPStatus.NOT_FOUND, "unknown stage")
            return
        try:
            payload = builder(self.review_root, project_id)
        except ValueError:
            self.send_error(HTTPStatus.BAD_REQUEST, "project stage data is unavailable")
            return
        self.send_json(payload)

    def handle_static_asset(self, path: str) -> None:
        assets_root = Path(__file__).resolve().parent / "assets"
        rel = posixpath.normpath(unquote(path.removeprefix("/assets/"))).lstrip("/")
        candidate = (assets_root / rel).resolve()
        try:
            candidate.relative_to(assets_root.resolve())
        except ValueError:
            self.send_error(HTTPStatus.FORBIDDEN, "asset path outside assets root")
            return
        if not candidate.exists() or not candidate.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "asset not found")
            return
        mime = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
        self.send_file(candidate, mime)

    def handle_project_draft_put(self, project_id: str) -> None:
        try:
            project = project_dir(self.review_root, project_id)
        except ValueError as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        if not project.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "project not found")
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            result = write_project_draft_sections(self.review_root, project_id, data)
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, f"invalid draft payload: {exc}")
            return
        self.send_json(result)

    def discovery_path(self, project_id: str) -> Path:
        return project_dir(self.review_root, project_id) / "00_discovery" / "combined_results_by_keyword.json"

    def handle_metadata_get(self, paper_id: str) -> None:
        path = self.metadata_dir / f"{paper_id}.metadata.json"
        if not path.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "metadata not found")
            return
        self.send_file(path, "application/json; charset=utf-8")

    def handle_metadata_put(self, paper_id: str) -> None:
        path = self.metadata_dir / f"{paper_id}.metadata.json"
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, f"invalid json: {exc}")
            return
        if data.get("paper_id") != paper_id:
            self.send_error(HTTPStatus.BAD_REQUEST, "paper_id mismatch")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
        rebuild_registry(self.review_root)
        self.send_json({"ok": True})

    def handle_markdown_get(self, paper_id: str) -> None:
        meta = self.load_meta(paper_id)
        if not meta:
            self.send_error(HTTPStatus.NOT_FOUND, "metadata not found")
            return
        path_value = (meta.get("source_paths") or {}).get("markdown")
        if not path_value:
            self.send_error(HTTPStatus.NOT_FOUND, "markdown path missing")
            return
        path = safe_abs_path(path_value)
        if not path or not path.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "markdown not found")
            return
        self.send_file(path, "text/markdown; charset=utf-8")

    def handle_file(self, raw_path: str, paper_id: str = "") -> None:
        if not raw_path:
            self.send_error(HTTPStatus.BAD_REQUEST, "missing path")
            return
        requested_path = Path(unquote(raw_path)).expanduser()
        release_candidate = requested_path if requested_path.is_absolute() else self.review_root / requested_path
        try:
            validate_file_request_path_components(self.review_root, requested_path)
        except (OSError, ValueError):
            self.send_error(HTTPStatus.FORBIDDEN, "file path contains a symlink or reparse point")
            return
        path = safe_abs_path(raw_path)
        if not path:
            self.send_error(HTTPStatus.BAD_REQUEST, "invalid path")
            return
        allowed_roots = [self.review_root.resolve()]
        if not path.is_absolute():
            resolved = None
            if paper_id:
                meta = self.load_meta(paper_id)
                md_value = ((meta or {}).get("source_paths") or {}).get("markdown")
                if md_value:
                    md_dir = Path(md_value).resolve().parent
                    candidate = (md_dir / path).resolve()
                    try:
                        candidate.relative_to(md_dir)
                    except ValueError:
                        candidate = None
                    if candidate and candidate.exists():
                        resolved = candidate
                        allowed_roots.append(md_dir)
            path = resolved or (self.review_root / path).resolve()
        else:
            path = path.resolve()
        if not any(is_relative_to(path, root) for root in allowed_roots):
            self.send_error(HTTPStatus.FORBIDDEN, "file path outside allowed roots")
            return
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "file not found")
            return
        if is_project_release_docx(release_candidate, self.review_root):
            try:
                current = project_release_docx_is_current(release_candidate)
            except ValueError:
                current = False
            if not current:
                self.send_error(HTTPStatus.FORBIDDEN, "release DOCX is outdated")
                return
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_file(path, ctype)

    def load_meta(self, paper_id: str) -> dict | None:
        path = self.metadata_dir / f"{paper_id}.metadata.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def send_json(self, data: object, *, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_file(self, path: Path, content_type: str) -> None:
        try:
            size = path.stat().st_size
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(size))
            self.end_headers()
            with path.open("rb") as f:
                shutil.copyfileobj(f, self.wfile)
        except BrokenPipeError:
            pass


def value_of(field):
    if isinstance(field, dict) and "value" in field:
        return field.get("value")
    return field


def safe_abs_path(raw: str) -> Path | None:
    raw = unquote(raw)
    if "\x00" in raw:
        return None
    # Keep spaces and unicode; only normalize separators.
    raw = posixpath.normpath(raw)
    return Path(raw).expanduser().resolve() if raw.startswith("/") else Path(raw)


def validate_file_request_path_components(review_root: Path, requested_path: Path) -> None:
    """Reject lexical symlink/reparse aliases below the trusted review root."""
    trusted_root = review_root.resolve(strict=True)
    lexical_root = Path(os.path.abspath(os.fspath(review_root)))
    candidate = requested_path if requested_path.is_absolute() else lexical_root / requested_path
    for root in (lexical_root, trusted_root):
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            continue
        validate_project_path_components(trusted_root, (relative,))
        return


def project_id_from_route(path: str, action: str) -> str | None:
    parts = path.strip("/").split("/")
    if len(parts) != 4 or parts[:2] != ["api", "project"] or parts[3] != action:
        return None
    return unquote(parts[2])


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def rebuild_registry(review_root: Path) -> None:
    meta_dir = review_root / "review-library" / "metadata" / "papers"
    registry = review_root / "review-library" / "registry" / "papers.jsonl"
    rows = []
    for path in sorted(meta_dir.glob("*.metadata.json")):
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        source_paths = meta.get("source_paths") or {}
        rows.append(
            {
                "paper_id": meta.get("paper_id"),
                "slug": meta.get("slug"),
                "title": value_of(meta.get("title")),
                "authors": value_of(meta.get("authors")),
                "year": value_of(meta.get("year")),
                "journal": value_of(meta.get("journal")),
                "doi": value_of(meta.get("doi")),
                "source_pdf": source_paths.get("pdf"),
                "markdown_path": source_paths.get("markdown"),
                "content_list_path": source_paths.get("content_list"),
                "metadata_path": str(path),
                "parse_status": "done",
                "human_review_status": (meta.get("human_review") or {}).get("status"),
                "needs_human_check": (meta.get("quality") or {}).get("needs_human_check"),
            }
        )
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def now_utc() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def selected_from_combined(groups: list[dict], project_id: str) -> dict:
    selected = {"project_id": project_id, "keywords": [], "local_papers": {}, "web_papers": []}
    for group in groups:
        if group.get("keep") is False:
            continue
        selected["keywords"].append({"keyword": group.get("keyword"), "category": group.get("category")})
        for row in group.get("local_results", []):
            if row.get("keep") is False:
                continue
            pid = row.get("paper_id")
            if not pid:
                continue
            item = selected["local_papers"].setdefault(
                pid,
                {
                    "paper_id": pid,
                    "title": row.get("title"),
                    "year": row.get("year"),
                    "journal": row.get("journal"),
                    "role": row.get("role", "uncertain"),
                    "matched_keywords": [],
                    "best_score": 0,
                    "keep": True,
                },
            )
            item["matched_keywords"].append(group.get("keyword"))
            item["best_score"] = max(item.get("best_score", 0), row.get("score", 0))
        for row in group.get("web_results", []):
            if row.get("keep") is not False:
                selected["web_papers"].append({**row, "matched_keyword": group.get("keyword")})
    selected["local_papers"] = sorted(
        selected["local_papers"].values(), key=lambda x: x.get("best_score", 0), reverse=True
    )[:30]
    selected["web_papers"] = selected["web_papers"][:30]
    return selected


def read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def researcher_safe_markdown(markdown: str) -> str:
    """Keep report prose while hiding local implementation details from researchers."""
    if not isinstance(markdown, str):
        return ""
    safe = _RESEARCHER_WINDOWS_PATH_RE.sub("[internal detail hidden]", markdown)
    safe = _RESEARCHER_POSIX_PATH_RE.sub("[internal detail hidden]", safe)
    safe = _RESEARCHER_SHA256_RE.sub("[internal detail hidden]", safe)
    return _RESEARCHER_INTERNAL_FILENAME_RE.sub("[project artifact]", safe)


def read_json_if_exists(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def read_jsonl_if_exists(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("project evidence is unavailable") from exc
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError("project evidence is unavailable")
    return rows


def visible_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return ", ".join(item.strip() for item in value if isinstance(item, str) and item.strip())
    if isinstance(value, dict):
        for key in ("display", "text", "value", "title"):
            text = value.get(key)
            if isinstance(text, str) and text.strip():
                return text.strip()
    return ""


def visible_text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    text = visible_text(value)
    return [text] if text else []


def _normalized_project_source_id(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _acquisition_source_relative_path(value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    portable = value.strip().replace("\\", "/")
    if portable.startswith("/") or re.match(r"^[A-Za-z]:/", portable):
        return None
    parts = portable.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return None
    if parts[0].casefold() in {"00_sources", "sources"}:
        parts = parts[1:]
    if not parts:
        return None
    relative = Path("00_sources", *parts)
    return relative if relative.suffix.casefold() == ".pdf" else None


def _acquisition_source_aliases(project: Path) -> list[tuple[set[str], Any]]:
    aliases: list[tuple[set[str], Any]] = []
    receipt = read_json_if_exists(project / "00_sources" / "acquisition_final_receipt.json")
    studies = receipt.get("studies") if isinstance(receipt, dict) else None
    for study in studies if isinstance(studies, list) else []:
        if not isinstance(study, dict):
            continue
        doi = normalize_doi(visible_text(study.get("doi")))
        for role, field in (("MAIN", "main_pdf"), ("SI", "si_pdf")):
            pdf = study.get(field)
            path = pdf.get("path") if isinstance(pdf, dict) else None
            alias = _normalized_project_source_id(f"{doi}_{role}") if doi else ""
            if alias:
                aliases.append(({alias}, path))

    for relative in (
        Path("00_discovery/acquisition_manifest.json"),
        Path("00_discovery/acquisition_manifest_converted.json"),
    ):
        manifest = read_json_if_exists(project / relative)
        if not isinstance(manifest, dict):
            continue
        for collection in ("rows", "downloads"):
            rows = manifest.get(collection)
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, dict):
                    continue
                role = visible_text(row.get("document_role")).upper()
                if role not in {"MAIN", "SI"}:
                    continue
                doi = normalize_doi(visible_text(row.get("doi")))
                normalized_aliases = {
                    alias
                    for alias in (
                        _normalized_project_source_id(visible_text(row.get("download_id"))),
                        _normalized_project_source_id(f"{doi}_{role}") if doi else "",
                    )
                    if alias
                }
                if normalized_aliases:
                    aliases.append((normalized_aliases, row.get("target_path")))
    return aliases


def build_project_source_index(
    project: Path,
    requested_source_ids: set[str],
) -> dict[str, Path | None]:
    """Index only requested, unique project-owned MAIN/SI PDFs for one request."""
    project_path = Path(project)
    sources = project_path / "00_sources"
    validate_project_path_components(project_path, (Path("00_sources"),))
    if not sources.is_dir():
        return {}
    requested = {
        normalized
        for source_id in requested_source_ids
        if isinstance(source_id, str)
        for normalized in (_normalized_project_source_id(source_id),)
        if normalized
    }
    if not requested:
        return {}
    index: dict[str, Path | None] = {}
    acquisition_declared: set[str] = set()
    for aliases, target_path in _acquisition_source_aliases(project_path):
        matched = aliases & requested
        if not matched:
            continue
        acquisition_declared.update(matched)
        relative = _acquisition_source_relative_path(target_path)
        validated: Path | None = None
        if relative is not None:
            try:
                validated = validate_project_file_path(
                    project_path,
                    relative,
                    "PROJECT_SOURCE_INVALID",
                )
            except (OSError, ValueError):
                pass
        for source_id in matched:
            if source_id in index and index[source_id] != validated:
                index[source_id] = None
            elif source_id not in index:
                index[source_id] = validated

    legacy_requested = requested - acquisition_declared
    if not legacy_requested:
        return index
    for study_dir in sorted(sources.iterdir(), key=lambda path: path.name.casefold()):
        requested_in_study = {
            _normalized_project_source_id(f"{study_dir.name}_{stem}")
            for stem in ("MAIN", "SI")
        } & legacy_requested
        if not requested_in_study:
            continue
        try:
            candidates = sorted(study_dir.iterdir(), key=lambda path: path.name.casefold())
        except OSError:
            index.update({source_id: None for source_id in requested_in_study})
            continue
        for candidate in candidates:
            if candidate.suffix.casefold() != ".pdf" or candidate.stem.casefold() not in {"main", "si"}:
                continue
            candidate_id = _normalized_project_source_id(f"{study_dir.name}_{candidate.stem}")
            if candidate_id not in legacy_requested:
                continue
            relative = candidate.relative_to(project_path)
            try:
                validated = validate_project_file_path(
                    project_path,
                    relative,
                    "PROJECT_SOURCE_INVALID",
                )
            except (OSError, ValueError):
                validated = None
            if candidate_id in index:
                index[candidate_id] = None
            else:
                index[candidate_id] = validated
    return index


def project_source_pdf(
    project: Path,
    source_id: str,
    *,
    source_index: dict[str, Path | None] | None = None,
) -> Path | None:
    """Resolve one case-neutral source id to a unique project-owned MAIN/SI PDF."""
    normalized = _normalized_project_source_id(source_id) if isinstance(source_id, str) else ""
    if not normalized:
        return None
    index = source_index if source_index is not None else build_project_source_index(project, {source_id})
    return index.get(normalized)


def _evidence_locator_href(
    project: Path,
    project_id: str,
    source_id: str,
    page: int | None,
    source_index: dict[str, Path | None],
) -> str:
    if source_id:
        local_source = project_source_pdf(project, source_id, source_index=source_index)
        if local_source is not None:
            href = f"/api/project/{project_id}/source?{urlencode({'source_id': source_id})}"
            return f"{href}#page={page}" if page is not None else href
    return ""


def _visible_evidence_ref(
    project: Path,
    project_id: str,
    ref: dict[str, Any],
    source_index: dict[str, Path | None],
) -> dict[str, Any]:
    source_id = visible_text(ref.get("source_id"))
    raw_page = ref.get("page")
    page = raw_page if isinstance(raw_page, int) and not isinstance(raw_page, bool) and raw_page > 0 else None
    return {
        "source_label": visible_text(ref.get("source_label")) or source_id or "Source record",
        "excerpt": visible_text(ref.get("exact_quote")) or visible_text(ref.get("evidence_summary")),
        "page": page,
        "section": visible_text(ref.get("section_or_item")),
        "locator": {
            "href": _evidence_locator_href(project, project_id, source_id, page, source_index)
        },
    }


def _visible_claim_detail(
    project: Path,
    project_id: str,
    claim: dict[str, Any],
    projected: dict[str, Any],
    reviewer: dict[str, Any],
    source_index: dict[str, Path | None],
) -> dict[str, Any]:
    claim_id = visible_text(projected.get("claim_id")) or visible_text(claim.get("claim_id"))
    refs = projected.get("evidence_refs")
    if not isinstance(refs, list):
        refs = claim.get("evidence_refs") if isinstance(claim.get("evidence_refs"), list) else []
    evidence = [
        _visible_evidence_ref(project, project_id, ref, source_index)
        for ref in refs
        if isinstance(ref, dict)
    ]
    raw_findings = reviewer.get("findings")
    finding = next(
        (
            row
            for row in (raw_findings if isinstance(raw_findings, list) else [])
            if isinstance(row, dict)
            and row.get("target_id") == claim_id
        ),
        {},
    )
    use_root_conclusion = not isinstance(raw_findings, list) or not raw_findings
    review_verdict = visible_text(finding.get("verdict")) or (
        visible_text(reviewer.get("verdict")) if use_root_conclusion else ""
    )
    review_summary = (
        visible_text(finding.get("reason"))
        or visible_text(finding.get("summary"))
        or (visible_text(reviewer.get("summary")) if use_root_conclusion else "")
    )
    return {
        "claim_id": claim_id,
        "text": (
            visible_text(projected.get("text"))
            or visible_text(projected.get("original_text"))
            or visible_text(claim.get("claim_text"))
        ),
        "decision": visible_text(projected.get("decision")),
        "risk_level": visible_text(projected.get("risk_level")) or visible_text(claim.get("risk_level")),
        "risk_categories": visible_text_list(projected.get("risk_categories") or claim.get("risk_categories")),
        "evidence": evidence,
        "review_verdict": review_verdict,
        "review_summary": review_summary,
    }


def scientist_locators(
    project: Path,
    project_id: str,
    claims: list[dict[str, Any]],
    source_index: dict[str, Path | None],
) -> list[dict[str, str]]:
    locators: list[dict[str, str]] = []
    seen: set[tuple[str, int | None, str]] = set()
    for claim in claims:
        refs = claim.get("evidence_refs") if isinstance(claim.get("evidence_refs"), list) else []
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            source_id = visible_text(ref.get("source_id"))
            source_label = visible_text(ref.get("source_label")) or source_id or "Source record"
            raw_page = ref.get("page")
            page = raw_page if isinstance(raw_page, int) and not isinstance(raw_page, bool) and raw_page > 0 else None
            section = visible_text(ref.get("section_or_item"))
            identity = (source_id, page, section)
            if identity in seen:
                continue
            seen.add(identity)
            label_parts = [source_label]
            if page is not None:
                label_parts.append(f"p. {page}")
            if section:
                label_parts.append(section)
            locators.append(
                {
                    "label": " · ".join(label_parts),
                    "href": _evidence_locator_href(
                        project,
                        project_id,
                        source_id,
                        page,
                        source_index,
                    ),
                }
            )
    return locators


def _claim_source_ids(claims: list[dict[str, Any]]) -> set[str]:
    return {
        source_id
        for claim in claims
        for ref in (claim.get("evidence_refs") if isinstance(claim.get("evidence_refs"), list) else [])
        if isinstance(ref, dict)
        for source_id in (visible_text(ref.get("source_id")),)
        if source_id
    }


def project_evidence_payload(review_root: Path, project_id: str) -> dict[str, Any]:
    project = project_dir(review_root, project_id)
    canonical_relatives = (
        Path("01_evidence/evidence_cards.jsonl"),
        Path("02_claims/claim_projection.jsonl"),
        Path("01_evidence/exception_queue.json"),
    )
    validate_project_path_components(project, canonical_relatives)
    if not any(os.path.lexists(project / relative) for relative in canonical_relatives):
        return {
            "project_id": project_id,
            "coverage": {"studies": 0, "processable": 0, "blocked": 0, "claims": 0},
            "cards": [],
        }
    metrics = benchmark_metrics(project)
    cards = read_jsonl_if_exists(project / "01_evidence" / "evidence_cards.jsonl")
    projection = read_jsonl_if_exists(project / "02_claims" / "claim_projection.jsonl")
    source_ids = _claim_source_ids(projection)
    for card in cards:
        candidate = card.get("candidate") if isinstance(card.get("candidate"), dict) else {}
        claims = candidate.get("claims") if isinstance(candidate.get("claims"), list) else []
        source_ids.update(_claim_source_ids([claim for claim in claims if isinstance(claim, dict)]))
    source_index = build_project_source_index(project, source_ids)
    projection_by_id = {
        visible_text(row.get("claim_id")): row
        for row in projection
        if visible_text(row.get("claim_id"))
    }
    exception_queue = read_json_if_exists(project / "01_evidence" / "exception_queue.json") or {}
    exceptions = exception_queue.get("exceptions") if isinstance(exception_queue, dict) else None
    if not isinstance(exceptions, list) or not all(isinstance(row, dict) for row in exceptions):
        raise ValueError("project evidence is unavailable")
    blocked_studies = {
        row.get("study_id")
        for row in projection
        if row.get("decision") == "BLOCKED" and isinstance(row.get("study_id"), str)
    }
    exception_studies = {
        row.get("study_id")
        for row in exceptions
        if isinstance(row.get("study_id"), str)
    }
    blocked_exception_overlap = len(blocked_studies & exception_studies)
    visible_cards: list[dict[str, Any]] = []
    for card in cards:
        candidate = card.get("candidate") if isinstance(card.get("candidate"), dict) else {}
        study_id = visible_text(card.get("study_id")) or visible_text(candidate.get("study_id"))
        if not study_id:
            continue
        claims = candidate.get("claims") if isinstance(candidate.get("claims"), list) else []
        claim_rows = [claim for claim in claims if isinstance(claim, dict)]
        reviewer = card.get("reviewer") if isinstance(card.get("reviewer"), dict) else {}
        claim_details = [
            _visible_claim_detail(
                project,
                project_id,
                claim,
                projection_by_id.get(visible_text(claim.get("claim_id")), {}),
                reviewer,
                source_index,
            )
            for claim in claim_rows
            if visible_text(claim.get("claim_id"))
        ]
        claim_texts = [
            text
            for text in (visible_text(claim.get("claim_text")) for claim in claim_rows)
            if text
        ]
        excerpt = visible_text(candidate.get("source_excerpt"))
        if not excerpt:
            excerpt = next(
                (
                    visible_text(ref.get("exact_quote"))
                    for claim in claim_rows
                    for ref in (claim.get("evidence_refs") or [])
                    if isinstance(ref, dict) and visible_text(ref.get("exact_quote"))
                ),
                "",
            )
        visible_cards.append(
            {
                "study_id": study_id,
                "citation": visible_text(candidate.get("citation")),
                "activation_mode": visible_text(candidate.get("activation_mode")),
                "reaction_class": visible_text(candidate.get("reaction_class")),
                "observations": visible_text_list(candidate.get("observations")),
                "limitations": visible_text_list(candidate.get("limitations")),
                "claims": claim_texts,
                "source_excerpt": excerpt,
                "locators": scientist_locators(
                    project,
                    project_id,
                    claim_rows,
                    source_index,
                ),
                "claim_details": claim_details,
            }
        )
    visible_cards.sort(key=lambda card: card["study_id"])
    return {
        "project_id": project_id,
        "coverage": {
            "studies": metrics["registered_study_count"],
            "processable": metrics["approved_claim_count"] + metrics["human_required_claim_count"],
            "blocked": (
                metrics["blocked_claim_count"]
                + metrics["exception_count"]
                - blocked_exception_overlap
            ),
            "claims": metrics["projected_claim_count"],
        },
        "cards": visible_cards,
    }


def _mode_coverage(
    classifications: Any,
    cards: list[dict[str, Any]],
    included_studies: int,
) -> list[dict[str, Any]]:
    rows = classifications
    if isinstance(classifications, dict):
        rows = classifications.get("classifications") or classifications.get("studies")
        if not isinstance(rows, list):
            rows = [
                {"doi": doi, "activation_mode": mode}
                for doi, mode in classifications.items()
                if isinstance(mode, str)
            ]
    if not isinstance(rows, list):
        rows = []

    doi_modes: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        doi = normalize_doi(visible_text(row.get("doi")))
        mode = visible_text(row.get("activation_mode"))
        if doi and mode:
            doi_modes[doi] = mode

    included_by_mode: dict[str, int] = {}
    reviewed_by_mode: dict[str, int] = {}
    reviewed_ids: set[str] = set()
    reviewed_dois: set[str] = set()
    for index, card in enumerate(cards):
        candidate = card.get("candidate") if isinstance(card.get("candidate"), dict) else {}
        doi = normalize_doi(visible_text(candidate.get("doi")))
        reviewed_id = visible_text(card.get("study_id")) or visible_text(candidate.get("study_id"))
        reviewed_id = reviewed_id or doi or f"card-{index}"
        if reviewed_id in reviewed_ids:
            continue
        reviewed_ids.add(reviewed_id)
        if doi:
            reviewed_dois.add(doi)
        mode = doi_modes.get(doi) if doi else ""
        if not mode:
            mode = visible_text(candidate.get("activation_mode"))
        if not mode:
            mode = "Unclassified"
        included_by_mode[mode] = included_by_mode.get(mode, 0) + 1
        reviewed_by_mode[mode] = reviewed_by_mode.get(mode, 0) + 1

    occupied = len(reviewed_ids)
    for doi, mode in sorted(doi_modes.items()):
        if occupied >= included_studies:
            break
        if doi in reviewed_dois:
            continue
        included_by_mode[mode] = included_by_mode.get(mode, 0) + 1
        occupied += 1

    unclassified = included_studies - occupied
    if unclassified > 0:
        included_by_mode["Unclassified"] = (
            included_by_mode.get("Unclassified", 0) + unclassified
        )
    modes = sorted(set(included_by_mode) | set(reviewed_by_mode), key=str.casefold)
    return [
        {
            "activation_mode": mode,
            "included_studies": included_by_mode.get(mode, 0),
            "reviewed_studies": reviewed_by_mode.get(mode, 0),
        }
        for mode in modes
    ]


def _open_scientific_risk_count(packet: Any, decision_payload: Any) -> int:
    targets = packet.get("targets") if isinstance(packet, dict) else None
    if not isinstance(targets, list):
        raw_count = packet.get("target_count") if isinstance(packet, dict) else 0
        return raw_count if isinstance(raw_count, int) and not isinstance(raw_count, bool) and raw_count >= 0 else 0
    decisions = decision_payload.get("decisions") if isinstance(decision_payload, dict) else None
    closed = {
        (visible_text(row.get("claim_id")), visible_text(row.get("review_target_digest")))
        for row in (decisions if isinstance(decisions, list) else [])
        if isinstance(row, dict)
        and visible_text(row.get("action")).upper() in {"APPROVE", "REWORD", "EXCLUDE"}
    }
    return sum(
        isinstance(target, dict)
        and (
            visible_text(target.get("claim_id")),
            visible_text(target.get("review_target_digest")),
        )
        not in closed
        for target in targets
    )


def project_cockpit_payload(review_root: Path, project_id: str) -> dict[str, Any]:
    project = project_dir(review_root, project_id)
    state = read_json_if_exists(project / "00_brief" / "review_state.json") or {}
    screening = read_json_if_exists(project / "00_discovery" / "screening_decisions.json") or {}
    decisions = screening.get("decisions") if isinstance(screening, dict) else None
    included_studies: int | None = None
    if isinstance(decisions, list):
        included_studies = sum(
            isinstance(row, dict) and row.get("disposition") == "INCLUDE_FOR_FULL_TEXT"
            for row in decisions
        )

    acquisition = read_json_if_exists(project / "00_sources" / "acquisition_final_receipt.json") or {}
    acquisition_studies = acquisition.get("studies") if isinstance(acquisition, dict) else None
    if included_studies is None and isinstance(acquisition, dict):
        total = acquisition.get("total_studies")
        if isinstance(total, int) and not isinstance(total, bool) and total >= 0:
            included_studies = total

    cards = read_jsonl_if_exists(project / "01_evidence" / "evidence_cards.jsonl")
    reviewed_ids = {
        visible_text(card.get("study_id"))
        or visible_text(card.get("candidate", {}).get("study_id"))
        for card in cards
        if isinstance(card, dict)
    }
    reviewed_ids.discard("")
    reviewed_studies = len(reviewed_ids) if reviewed_ids else len(cards)
    if included_studies is None:
        included_studies = reviewed_studies

    full_text_main_coverage: int | None = None
    if isinstance(acquisition_studies, list):
        full_text_main_coverage = sum(
            isinstance(row, dict) and bool(row.get("main_pdf"))
            for row in acquisition_studies
        )
    if full_text_main_coverage is None and isinstance(acquisition, dict):
        acquired = acquisition.get("full_text_acquired")
        if isinstance(acquired, int) and not isinstance(acquired, bool) and acquired >= 0:
            full_text_main_coverage = acquired
    if full_text_main_coverage is None:
        sources = project / "00_sources"
        full_text_main_coverage = 0
        if sources.is_dir() and not is_reparse_component(sources):
            full_text_main_coverage = sum(
                any(
                    child.is_file()
                    and not is_reparse_component(child)
                    and child.name.casefold() == "main.pdf"
                    for child in study.iterdir()
                )
                for study in sources.iterdir()
                if study.is_dir() and not is_reparse_component(study)
            )

    risk_packet = read_json_if_exists(project / "03_review" / "risk_packet.json") or {}
    risk_decisions = read_json_if_exists(project / "03_review" / "risk_decisions.json") or {}
    scientific_risks = _open_scientific_risk_count(risk_packet, risk_decisions)

    classifications = read_json_if_exists(project / "01_evidence" / "pilot_mode_classification.json")
    if reviewed_studies < included_studies:
        recommended_next = "继续处理下一批证据"
    elif full_text_main_coverage < included_studies:
        recommended_next = "补齐缺失的全文证据"
    elif scientific_risks:
        recommended_next = "复核集中科学风险"
    elif not project_regular_file_exists(project, Path("04_first_draft/first_draft.md")):
        recommended_next = "开始撰写证据约束的综述正文"
    else:
        recommended_next = "继续完善综述正文"
    return {
        "project_id": project_id,
        "current_stage": visible_text(state.get("current_stage")) or "not_started",
        "metrics": {
            "included_studies": included_studies,
            "full_text_main_coverage": full_text_main_coverage,
            "reviewed_studies": reviewed_studies,
            "scientific_risks": scientific_risks,
        },
        "recommended_next": recommended_next,
        "mode_coverage": _mode_coverage(classifications, cards, included_studies),
    }


def _safe_research_source_url(value: Any) -> str:
    text = visible_text(value)
    parsed = urlparse(text)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        return ""
    return text


def project_source_handoff_payload(review_root: Path, project_id: str) -> dict[str, Any]:
    project = project_dir(review_root, project_id)
    manifest_relative = Path("00_discovery/acquisition_manifest.json")
    receipt_relative = Path("00_sources/acquisition_receipt.json")
    validate_project_path_components(project, (manifest_relative, receipt_relative))
    manifest_path = project / manifest_relative
    receipt_path = project / receipt_relative
    manifest = read_json_if_exists(manifest_path)
    receipt = read_json_if_exists(receipt_path)
    if os.path.lexists(manifest_path) and not isinstance(manifest, dict):
        raise ValueError("project source list is unavailable")
    if os.path.lexists(receipt_path) and not isinstance(receipt, dict):
        raise ValueError("project source list is unavailable")
    manifest = manifest or {}
    receipt = receipt or {}
    downloads = manifest.get("downloads") if isinstance(manifest, dict) else []
    results = receipt.get("results") if isinstance(receipt, dict) else []
    if downloads is not None and not isinstance(downloads, list):
        raise ValueError("project source list is unavailable")
    if results is not None and not isinstance(results, list):
        raise ValueError("project source list is unavailable")
    downloads = downloads or []
    results = results or []
    result_by_id = {
        visible_text(row.get("download_id")): row
        for row in results
        if isinstance(row, dict) and visible_text(row.get("download_id"))
    }
    sources: list[dict[str, Any]] = []
    for index, row in enumerate(item for item in downloads if isinstance(item, dict)):
        download_id = visible_text(row.get("download_id"))
        result = result_by_id.get(download_id, {})
        ready = visible_text(result.get("status")).upper() in SOURCE_ARCHIVE_SUCCESS_STATUSES
        role = visible_text(row.get("document_role")).upper() or "FULL TEXT"
        study_id = visible_text(row.get("study_id"))
        doi = normalize_doi(row.get("doi")) or ""
        citation = doi or study_id or f"研究 {index + 1}"
        landing_url = _safe_research_source_url(row.get("landing_page_url"))
        source_url = _safe_research_source_url(row.get("source_url") or row.get("url"))
        sources.append(
            {
                "study_id": study_id or doi,
                "citation": citation,
                "role": role,
                "status": "已获得" if ready else "需要上传",
                "download_url": landing_url or source_url,
                "message": "全文已就绪" if ready else f"请补充 {role} 文件",
            }
        )
    ready_count = sum(row["status"] == "已获得" for row in sources)
    return {
        "project_id": project_id,
        "counts": {
            "total": len(sources),
            "ready": ready_count,
            "missing": len(sources) - ready_count,
        },
        "upload_required": any(row["status"] == "需要上传" for row in sources),
        "sources": sources,
    }


def project_progress_payload(review_root: Path, project_id: str) -> dict[str, Any]:
    project = project_dir(review_root, project_id)
    state = read_json_if_exists(project / "00_brief/review_state.json") or {}
    source_payload = project_source_handoff_payload(review_root, project_id)
    screening = read_json_if_exists(project / "00_discovery/screening_decisions.json") or {}
    decisions = screening.get("decisions") if isinstance(screening, dict) else []
    decisions = decisions if isinstance(decisions, list) else []
    included_ids = {
        visible_text(row.get("candidate_id") or row.get("study_id"))
        for row in decisions
        if isinstance(row, dict) and row.get("disposition") == "INCLUDE_FOR_FULL_TEXT"
    }
    included_ids.discard("")
    cards = read_jsonl_if_exists(project / "01_evidence/evidence_cards.jsonl")
    reviewed_ids = {
        visible_text(row.get("study_id"))
        or visible_text((row.get("candidate") or {}).get("study_id"))
        for row in cards
        if isinstance(row, dict) and isinstance(row.get("candidate") or {}, dict)
    }
    reviewed_ids.discard("")
    parse_manifest = read_json_if_exists(project / "01_evidence/mineru/manifest.json") or {}
    completed_parse = parse_manifest.get("completed") if isinstance(parse_manifest, dict) else []
    completed_parse = completed_parse if isinstance(completed_parse, list) else []
    risk_packet = read_json_if_exists(project / "03_review/risk_packet.json") or {}
    risk_decisions = read_json_if_exists(project / "03_review/risk_decisions.json") or {}
    risk_targets = risk_packet.get("targets") if isinstance(risk_packet, dict) else []
    risk_targets = risk_targets if isinstance(risk_targets, list) else []
    open_risks = _open_scientific_risk_count(risk_packet, risk_decisions)

    source_total = int(source_payload["counts"]["total"])
    source_ready = int(source_payload["counts"]["ready"])
    sources_complete = source_total > 0 and source_ready == source_total
    parsing_complete = sources_complete and len(completed_parse) >= source_ready
    evidence_complete = bool(included_ids) and included_ids.issubset(reviewed_ids)
    risk_packet_present = os.path.lexists(project / "03_review/risk_packet.json")
    risk_complete = evidence_complete and risk_packet_present and open_risks == 0
    draft_complete = project_regular_file_exists(project, Path("04_first_draft/first_draft.md"))
    final_complete = project_regular_file_exists(project, Path("05_final_audit/final_draft.docx"))

    archive_received = project_regular_file_exists(project, SOURCE_ARCHIVE_RELATIVE)
    if not sources_complete:
        active_stage = "sources"
    elif not parsing_complete:
        active_stage = "parsing"
    elif not evidence_complete:
        active_stage = "evidence"
    elif not risk_complete and not draft_complete:
        active_stage = "risk"
    elif not draft_complete:
        active_stage = "drafting"
    else:
        active_stage = "final"

    stage_definitions = (
        ("sources", "整理文献来源", sources_complete),
        ("parsing", "解析全文与补充信息", parsing_complete),
        ("evidence", "提取并核对逐研究证据", evidence_complete),
        ("risk", "汇总科学风险", risk_complete),
        ("drafting", "撰写证据约束正文", draft_complete),
        ("final", "完成终稿与 DOCX", final_complete),
    )
    active_index = next(
        (index for index, (stage_id, _, _) in enumerate(stage_definitions) if stage_id == active_stage),
        0,
    )
    raw_blockers = state.get("blockers") if isinstance(state, dict) else []
    raw_blockers = raw_blockers if isinstance(raw_blockers, list) else []
    source_invalid = any(
        isinstance(item, str) and item.startswith(("SOURCE_ARCHIVE_", "MANUAL_ARCHIVE_"))
        for item in raw_blockers
    )
    blocker = (
        "上传的压缩包未通过来源核验，请按缺失清单修正后重新上传。"
        if source_invalid
        else "当前阶段需要补充信息，请查看推荐操作。"
        if raw_blockers
        else ""
    )
    stages = []
    for index, (stage_id, label, complete) in enumerate(stage_definitions):
        status = "complete" if complete else "active" if index == active_index else "pending"
        if status == "active" and blocker:
            status = "blocked"
        stages.append({"id": stage_id, "label": label, "status": status})

    source_rows: dict[str, dict[str, Any]] = {}
    for row in source_payload["sources"]:
        study_id = visible_text(row.get("study_id"))
        if not study_id:
            continue
        summary = source_rows.setdefault(
            study_id,
            {"study_id": study_id, "label": visible_text(row.get("citation")) or study_id, "missing": False},
        )
        summary["missing"] = summary["missing"] or row.get("status") != "已获得"
    studies = []
    for study_id, summary in source_rows.items():
        status = (
            "需要补充"
            if summary["missing"]
            else "已完成"
            if study_id in reviewed_ids
            else "正在处理"
        )
        studies.append({"study_id": study_id, "label": summary["label"], "status": status})
    studies.sort(key=lambda row: row["study_id"])

    recommended = {
        "sources": "正在核验您上传的来源" if archive_received else "上传一次 PDF ZIP",
        "parsing": "等待全文解析完成",
        "evidence": "继续处理下一篇研究证据",
        "risk": "检查集中科学风险",
        "drafting": "开始撰写证据约束正文",
        "final": "检查正文并导出 DOCX",
    }[active_stage]
    return {
        "project_id": project_id,
        "active_stage": active_stage,
        "stages": stages,
        "studies": studies,
        "blocker": blocker,
        "recommended_next": recommended,
        "archive_received": archive_received,
    }


def project_risk_payload(review_root: Path, project_id: str) -> dict[str, Any]:
    project = project_dir(review_root, project_id)
    packet_relative = Path("03_review/risk_packet.json")
    decisions_relative = Path("03_review/risk_decisions.json")
    validate_project_path_components(project, (packet_relative, decisions_relative))
    packet_path = project / packet_relative
    decisions_path = project / decisions_relative
    packet_exists = os.path.lexists(packet_path)
    decisions_exists = os.path.lexists(decisions_path)
    if decisions_exists:
        decision_payload = read_json_if_exists(decisions_path)
        raw_decisions = decision_payload.get("decisions") if isinstance(decision_payload, dict) else None
        if not isinstance(raw_decisions, list) or not all(isinstance(row, dict) for row in raw_decisions):
            raise ValueError("project risk review is unavailable")
    else:
        decision_payload = {}
        raw_decisions = []
    if not packet_exists:
        if raw_decisions:
            raise ValueError("project risk review is unavailable")
        return {
            "project_id": project_id,
            "coverage": {"targets": 0, "human_required": 0, "low_risk_audit": 0},
            "targets": [],
        }
    packet = read_json_if_exists(packet_path)
    raw_targets = packet.get("targets") if isinstance(packet, dict) else None
    if not isinstance(raw_targets, list) or not all(isinstance(row, dict) for row in raw_targets):
        raise ValueError("project risk review is unavailable")
    benchmark_metrics(project)
    existing: dict[str, dict[str, Any]] = {}
    for row in raw_decisions:
        claim_id = visible_text(row.get("claim_id"))
        if claim_id:
            existing[claim_id] = row
    targets: list[dict[str, Any]] = []
    target_ids: list[str] = []
    for row in raw_targets:
        target_id = visible_text(row.get("claim_id"))
        decision_token = row.get("review_target_digest")
        if not target_id or not isinstance(decision_token, str) or not decision_token:
            raise ValueError("project risk review is unavailable")
        target_ids.append(target_id)
        refs = row.get("evidence_refs") if isinstance(row.get("evidence_refs"), list) else []
        source = next((ref for ref in refs if isinstance(ref, dict)), {})
        source_label = visible_text(source.get("source_label")) or visible_text(source.get("source_id")) or "Source record"
        raw_page = source.get("page")
        page = raw_page if isinstance(raw_page, int) and not isinstance(raw_page, bool) and raw_page > 0 else None
        section = visible_text(source.get("section_or_item"))
        summary_parts = [source_label]
        if page is not None:
            summary_parts.append(f"p. {page}")
        if section:
            summary_parts.append(section)
        saved = existing.get(target_id, {})
        action = visible_text(saved.get("action")).lower()
        if saved.get("review_target_digest") != decision_token or action not in {"approve", "reword", "exclude", "unresolved"}:
            action = "unresolved"
        approved_text = visible_text(saved.get("approved_text")) if action == "reword" else ""
        proposed_action = (
            "自动证据审查支持；该主张属于高风险类别，需要您确认是否进入正文。"
            if visible_text(row.get("selection_reason")) == "HUMAN_REQUIRED"
            else "自动证据审查支持；该主张被抽样展示，请确认证据与措辞是否一致。"
        )
        targets.append(
            {
                "target_id": target_id,
                "claim_text": visible_text(row.get("original_text")) or visible_text(row.get("text")),
                "risk_categories": visible_text_list(row.get("risk_categories")),
                "evidence_summary": " · ".join(summary_parts),
                "source_excerpt": visible_text(source.get("exact_quote")),
                "source_label": source_label,
                "page": page,
                "proposed_action": proposed_action,
                "existing_decision": action,
                "approved_text": approved_text,
                "decision_token": decision_token,
            }
        )
    if len(target_ids) != len(set(target_ids)):
        raise ValueError("project risk review is unavailable")
    targets.sort(key=lambda target: target["target_id"])
    return {
        "project_id": project_id,
        "coverage": {
            "targets": len(targets),
            "human_required": int(packet.get("human_required_count") or 0),
            "low_risk_audit": int(packet.get("low_risk_sample_count") or 0),
        },
        "targets": targets,
    }


def write_project_risk_decisions(review_root: Path, project_id: str, data: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or not isinstance(data.get("decisions"), list):
        raise ValueError("decisions must contain a list")
    action_map = {
        "approve": "APPROVE",
        "reword": "REWORD",
        "exclude": "EXCLUDE",
        "unresolved": "UNRESOLVED",
    }
    task4_rows: list[dict[str, Any]] = []
    visible_rows: list[dict[str, str]] = []
    for row in data["decisions"]:
        if not isinstance(row, dict):
            raise ValueError("decision rows must be objects")
        target_id = row.get("target_id")
        decision = row.get("decision")
        decision_token = row.get("decision_token")
        if not isinstance(target_id, str) or not target_id.strip():
            raise ValueError("decision target is required")
        if not isinstance(decision, str) or decision not in action_map:
            raise ValueError("decision is invalid")
        if not isinstance(decision_token, str) or not decision_token:
            raise ValueError("decision is no longer current")
        task4_row: dict[str, Any] = {
            "claim_id": target_id,
            "action": action_map[decision],
            "review_target_digest": decision_token,
        }
        if decision == "reword":
            task4_row["approved_text"] = row.get("approved_text")
        task4_rows.append(task4_row)
        visible_rows.append({"target_id": target_id, "decision": decision})
    project = project_dir(review_root, project_id)
    apply_risk_decisions(project, {"decisions": task4_rows})
    visible_rows.sort(key=lambda row: row["target_id"])
    return {"status": "saved", "decisions": visible_rows}


def infer_project_topic(project: Path) -> str:
    review_state = read_json_if_exists(project / "00_brief" / "review_state.json")
    if isinstance(review_state, dict):
        brief = review_state.get("brief")
        if isinstance(brief, dict) and brief.get("topic"):
            return str(brief.get("topic"))
    discovery_candidates = read_json_if_exists(project / "00_discovery" / "discovery_candidates.json")
    if isinstance(discovery_candidates, dict) and discovery_candidates.get("topic"):
        return str(discovery_candidates.get("topic"))
    discovery = read_json_if_exists(project / "00_discovery" / "combined_results_by_keyword.json")
    if isinstance(discovery, dict) and discovery.get("topic"):
        return str(discovery.get("topic"))
    topic_input = project / "00_discovery" / "topic_input.md"
    if topic_input.exists():
        for line in topic_input.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line.startswith("# "):
                return line[2:].strip()
    bundle = read_json_if_exists(project / "04_first_draft" / "draft_bundle.json")
    if isinstance(bundle, dict) and bundle.get("topic"):
        return str(bundle.get("topic"))
    return ""


def is_direct_output_root(review_root: Path) -> bool:
    return (review_root / "checkpoint_log.json").exists() and (review_root / "05_final_audit").exists()


def has_dashboard_data(review_root: Path) -> bool:
    if (review_root / "review-library" / "metadata" / "papers").exists() or is_direct_output_root(review_root):
        return True
    projects = review_root / "review-projects"
    return projects.is_dir() and any((project / "00_brief" / "review_state.json").is_file() for project in projects.iterdir() if project.is_dir())


def direct_project_id(review_root: Path) -> str:
    summary = read_json_if_exists(review_root / "run_summary.json")
    if isinstance(summary, dict) and summary.get("project_id"):
        return str(summary.get("project_id"))
    return review_root.name


def normalized_project_id(project_id: str) -> str:
    if not isinstance(project_id, str):
        raise ValueError("invalid project_id")
    decoded = unquote(project_id)
    if not decoded or decoded in {".", ".."} or "\x00" in decoded or "/" in decoded or "\\" in decoded:
        raise ValueError("invalid project_id")
    return decoded


def project_dir(review_root: Path, project_id: str) -> Path:
    normalized_id = normalized_project_id(project_id)
    root = review_root.resolve()
    projects_path = root / "review-projects"
    if is_reparse_component(projects_path):
        raise ValueError("invalid review-projects boundary")
    nested_root = projects_path.resolve()
    nested = (nested_root / normalized_id).resolve()
    if not is_relative_to(nested, nested_root):
        raise ValueError("invalid project_id")
    if nested.exists():
        return nested
    if is_direct_output_root(root) and normalized_id == normalized_project_id(direct_project_id(root)):
        return root
    return nested


def project_regular_file_exists(project: Path, relative: Path) -> bool:
    try:
        validate_project_file_path(project, relative, "PROJECT_FILE_UNAVAILABLE")
    except ValueError:
        return False
    return True


def project_nonblank_text_file_bytes(project: Path, relative: Path) -> bytes | None:
    try:
        path = validate_project_file_path(project, relative, "PROJECT_FILE_UNAVAILABLE")
        payload = path.read_bytes()
        return payload if payload.decode("utf-8").strip() else None
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def has_review_product_data(project: Path) -> bool:
    regular_artifacts = (
        "00_brief/review_state.json",
        "00_discovery/combined_results_by_keyword.json",
        "00_discovery/discovery_candidates.json",
        "00_discovery/screening_decisions.json",
        "01_evidence/evidence_cards.jsonl",
        "01_matrix_outline/literature_matrix.json",
        "01_matrix_outline/section_blueprint.json",
        "section_blueprint.json",
        "02_claims/claim_projection.jsonl",
        "02_section_drafting/section_drafts.md",
        "02_section_drafting/section_1.md",
        "03_review/risk_packet.json",
        "03_figure_redraw/redrawn_figure_manifest.json",
        "03_figure_redraw/figure_manifest.json",
        "05_final_audit/final_draft.md",
    )
    if any(
        project_regular_file_exists(project, Path(relative))
        for relative in regular_artifacts
    ):
        return True
    return any(
        project_nonblank_text_file_bytes(project, Path(relative)) is not None
        for relative in (
            "04_first_draft/first_draft.md",
            "04_first_draft/final_draft.md",
        )
    )


def list_review_projects(review_root: Path) -> list[dict[str, Any]]:
    if is_direct_output_root(review_root):
        project_id = direct_project_id(review_root)
        return [
            {
                "project_id": project_id,
                "topic": infer_project_topic(review_root),
                "has_discovery": (review_root / "00_discovery" / "discovery_candidates.json").exists(),
                "discovery_status": "approved_mock",
                "has_matrix_outline": (review_root / "01_matrix_outline" / "literature_matrix.json").exists(),
                "has_blueprint": (review_root / "section_blueprint.json").exists()
                or (review_root / "01_matrix_outline" / "section_blueprint.json").exists(),
                "has_section_drafting": (review_root / "02_section_drafting" / "section_1.md").exists(),
                "has_figure_redraw": (review_root / "03_figure_redraw" / "figure_manifest.json").exists(),
                "has_first_draft": project_nonblank_text_file_bytes(
                    review_root,
                    Path("04_first_draft/final_draft.md"),
                ) is not None,
                "has_final_audit": (review_root / "05_final_audit" / "final_draft.md").exists(),
            }
        ]
    base = review_root / "review-projects"
    projects: list[dict[str, Any]] = []
    if not base.exists():
        return projects
    for project in sorted(
        p for p in base.iterdir() if p.is_dir() and has_review_product_data(p)
    ):
        discovery_state = read_json_if_exists(project / "00_discovery" / "human_check_state.json") or {}
        projects.append(
            {
                "project_id": project.name,
                "topic": infer_project_topic(project),
                "has_discovery": (project / "00_discovery" / "combined_results_by_keyword.json").exists(),
                "discovery_status": discovery_state.get("status") or "pending",
                "has_matrix_outline": (project / "01_matrix_outline" / "literature_matrix.json").exists(),
                "has_blueprint": (project / "01_matrix_outline" / "section_blueprint.json").exists(),
                "has_section_drafting": (project / "02_section_drafting" / "section_drafts.md").exists(),
                "has_figure_redraw": (project / "03_figure_redraw" / "redrawn_figure_manifest.json").exists(),
                "has_first_draft": project_nonblank_text_file_bytes(
                    project,
                    Path("04_first_draft/first_draft.md"),
                ) is not None,
                "has_final_audit": (project / "05_final_audit" / "final_draft.md").exists(),
            }
        )
    return projects


def project_summary(review_root: Path, project_id: str) -> dict[str, Any] | None:
    return next((p for p in list_review_projects(review_root) if p["project_id"] == project_id), None)


def review_state_path(review_root: Path, project_id: str) -> Path:
    return project_dir(review_root, project_id) / "00_brief" / "review_state.json"


def select_default_workspace(
    review_state: dict[str, Any],
    *,
    first_draft_exists: bool,
) -> str:
    """Choose a researcher workspace without presenting a stage-only phantom manuscript."""
    stage = review_state.get("current_stage") if isinstance(review_state, dict) else None
    return (
        "manuscript"
        if first_draft_exists and stage in {"drafting", "final_review", "complete"}
        else "cockpit"
    )


def project_review_state_payload(review_root: Path, project_id: str) -> dict[str, Any]:
    project = project_dir(review_root, project_id)
    state = read_json_if_exists(review_state_path(review_root, project_id)) or {}
    if not isinstance(state, dict):
        state = {}
    final_stage = project / "05_final_audit"
    final_draft = final_stage / "final_draft.md"
    counts = state.get("counts") if isinstance(state.get("counts"), dict) else {}
    first_draft_exists = project_nonblank_text_file_bytes(
        project,
        Path("04_first_draft/first_draft.md"),
    ) is not None
    return {
        "project_id": project_id,
        "brief": state.get("brief") if isinstance(state.get("brief"), dict) else {"topic": infer_project_topic(project)},
        "current_stage": state.get("current_stage") or "not_started",
        "status": state.get("status") or "not_started",
        "blockers": state.get("blockers") if isinstance(state.get("blockers"), list) else [],
        "counts": {key: int(counts.get(key) or 0) for key in ("sources", "evidence", "claims")},
        "updated_at": state.get("updated_at"),
        "default_workspace": select_default_workspace(
            state,
            first_draft_exists=first_draft_exists,
        ),
        "draft": {"first_draft_exists": first_draft_exists, "final_draft_exists": final_draft.exists(), "docx_exists": (final_stage / "final_draft.docx").exists()},
        "summary": project_summary(review_root, project_id),
    }


def write_project_review_state(review_root: Path, project_id: str, data: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or data.get("project_id") != project_id:
        raise ValueError("project_id mismatch")
    required = ("brief", "current_stage", "status", "blockers", "counts")
    if any(key not in data for key in required) or not isinstance(data["brief"], dict) or not isinstance(data["blockers"], list) or not isinstance(data["counts"], dict):
        raise ValueError("state requires brief, current_stage, status, blockers, and counts")
    if not all(isinstance(data.get(key), str) and data[key].strip() for key in ("current_stage", "status")):
        raise ValueError("current_stage and status must be nonempty strings")
    existing = read_json_if_exists(review_state_path(review_root, project_id))
    if isinstance(existing, dict):
        if isinstance(existing.get("brief"), dict) and data["brief"] != existing["brief"]:
            raise ValueError("brief fields are immutable after initialization")
        if existing.get("status") == AWAITING_BRIEF_CONFIRMATION and (
            data["status"] != AWAITING_BRIEF_CONFIRMATION
            or data["current_stage"] != "review_brief"
        ):
            raise ValueError("brief confirmation requires the confirm_brief action")
    counts = data["counts"]
    state = {
        "project_id": project_id,
        "brief": data["brief"],
        "current_stage": data["current_stage"],
        "status": data["status"],
        "blockers": [str(item) for item in data["blockers"]],
        "counts": {key: int(counts.get(key) or 0) for key in ("sources", "evidence", "claims")},
        "updated_at": now_utc(),
    }
    path = review_state_path(review_root, project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return state


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
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


def _commit_draft_and_lineage(
    manuscript_path: Path,
    manuscript_payload: bytes,
    lineage_path: Path,
    lineage_payload: bytes,
    previous: dict[Path, bytes],
) -> None:
    try:
        _atomic_write_bytes(manuscript_path, manuscript_payload)
        _atomic_write_bytes(lineage_path, lineage_payload)
    except Exception:
        for path in (manuscript_path, lineage_path):
            _atomic_write_bytes(path, previous[path])
        raise


def _sentences(text: str) -> list[str]:
    return [match.group(0).strip() for match in _SENTENCE_RE.finditer(text) if match.group(0).strip()]


def _citation_signatures(text: str) -> list[tuple[str, ...]]:
    signatures: list[tuple[str, ...]] = []
    for sentence in _sentences(text):
        tokens = sorted(
            [
                (match.start(), match.group(0).casefold().rstrip(".,;"))
                for pattern in (_DOI_RE, _CITATION_RE)
                for match in pattern.finditer(sentence)
            ],
            key=lambda row: row[0],
        )
        if tokens:
            signatures.append(tuple(token for _, token in tokens))
    return signatures


def _scientific_number_signatures(
    text: str,
    lineage_spans: list[str],
) -> list[tuple[str, ...]]:
    signatures: list[tuple[str, ...]] = []
    for sentence in _sentences(text):
        without_citations = _CITATION_RE.sub("", _DOI_RE.sub("", sentence))
        lineage_context = any(span in sentence for span in lineage_spans)
        scientific_context = lineage_context or not _DOCUMENT_META_RE.search(without_citations)
        tokens: list[str] = []
        for match in _NUMBER_RE.finditer(without_citations):
            token = re.sub(r"\s+", "", match.group(0).casefold())
            has_scientific_marker = (
                token.startswith(("-", "+", "−"))
                or "%" in token
                or "percent" in token
                or bool(_SCIENTIFIC_UNIT_RE.match(without_citations[match.end() :]))
            )
            if scientific_context or has_scientific_marker:
                tokens.append(token)
        if tokens:
            signatures.append(tuple(tokens))
    return signatures


def _term_signatures(text: str) -> list[tuple[str, ...]]:
    signatures: list[tuple[str, ...]] = []
    for sentence in _sentences(text):
        token_rows = [
            (match.start(), match.group(0).casefold())
            for pattern in (_CHEMISTRY_TOKEN_RE, _CHEMICAL_STRUCTURE_RE)
            for match in pattern.finditer(sentence)
            if (
                pattern is _CHEMICAL_STRUCTURE_RE
                or any("\u4e00" <= character <= "\u9fff" for character in match.group(0))
                or not _DOCUMENT_META_RE.search(sentence)
            )
        ]
        tokens = tuple(token for _, token in sorted(token_rows))
        if tokens:
            signatures.append(tokens)
    return signatures


def _reviewable_statement_signatures(text: str) -> list[str]:
    return [
        re.sub(r"\s+", " ", sentence).strip().casefold()
        for sentence in _sentences(text)
        if not _DOCUMENT_META_RE.search(sentence) or _SCIENTIFIC_ASSERTION_RE.search(sentence)
    ]


def _scientific_edit_reasons(
    section_id: str,
    verified_body: str,
    candidate_body: str,
    lineage: dict[str, Any],
) -> list[str]:
    """Classify an edit under a deliberately small, general scientific contract.

    Lineage-bound spans, sentence-bound citation/DOI or scientific-number changes,
    and chemistry-token/structural-formula changes are scientific. After those
    rules, any added or rewritten non-meta statement is conservatively scientific.
    Only prose explicitly about document wording, structure, navigation, style, or
    versioning is editorial. This avoids domain vocabulary as a safety boundary.
    """
    reasons: list[str] = []
    lineage_spans: list[str] = []
    verified_claim_order: list[tuple[int, str]] = []
    candidate_claim_order: list[tuple[int, str]] = []
    for entry in manuscript_lineage_entries(lineage):
        if not isinstance(entry, dict):
            continue
        bound_section = entry.get("section_id")
        if bound_section is not None and bound_section != section_id:
            continue
        text_span = entry.get("text_span") or entry.get("manuscript_text") or entry.get("text")
        if isinstance(text_span, str) and text_span:
            verified_count = verified_body.count(text_span)
            candidate_count = candidate_body.count(text_span)
            if verified_count != candidate_count:
                reasons.append("修改了证据绑定主张")
                break
            if verified_count == candidate_count == 1:
                claim_id = visible_text(entry.get("claim_id")) or text_span
                lineage_spans.append(text_span)
                verified_claim_order.append((verified_body.index(text_span), claim_id))
                candidate_claim_order.append((candidate_body.index(text_span), claim_id))
    if not reasons and [row[1] for row in sorted(verified_claim_order)] != [
        row[1] for row in sorted(candidate_claim_order)
    ]:
        reasons.append("修改了证据绑定主张")

    if _scientific_number_signatures(verified_body, lineage_spans) != _scientific_number_signatures(
        candidate_body,
        lineage_spans,
    ):
        reasons.append("改变了数字或百分比")
    if _citation_signatures(verified_body) != _citation_signatures(candidate_body):
        reasons.append("改变了文献引用或 DOI")
    if (
        not reasons
        and _reviewable_statement_signatures(candidate_body)
        != _reviewable_statement_signatures(verified_body)
    ):
        reasons.append("新增了未经验证的科研结论")
    if _term_signatures(verified_body) != _term_signatures(candidate_body):
        reasons.append("改变了结构或机制术语")
    return list(dict.fromkeys(reasons))


def write_project_draft_sections(review_root: Path, project_id: str, data: Any) -> dict[str, Any]:
    with PROJECT_RELEASE_LOCK:
        return _write_project_draft_sections_unlocked(review_root, project_id, data)


def _write_project_draft_sections_unlocked(
    review_root: Path,
    project_id: str,
    data: Any,
) -> dict[str, Any]:
    required = {"section_id", "body", "manuscript_version"}
    if not isinstance(data, dict) or set(data) != required:
        raise ValueError("draft payload requires exactly section_id, body, and manuscript_version")
    section_id = data["section_id"]
    body = data["body"]
    version = data["manuscript_version"]
    if not isinstance(section_id, str) or not section_id or not isinstance(body, str):
        raise ValueError("draft payload requires one target section body")
    if not isinstance(version, str) or len(version) != 64:
        raise ValueError("draft payload manuscript version is invalid")
    project = project_dir(review_root, project_id)
    manuscript_path = validate_project_file_path(
        project, Path("04_first_draft/first_draft.md"), "MANUSCRIPT_INVALID"
    )
    lineage_path = validate_project_file_path(
        project, Path("04_first_draft/manuscript_lineage.json"), "MANUSCRIPT_LINEAGE_INVALID"
    )
    manuscript_bytes = manuscript_path.read_bytes()
    lineage_bytes = lineage_path.read_bytes()
    if hashlib.sha256(manuscript_bytes).hexdigest() != version:
        raise ValueError("stale manuscript version")
    try:
        current_markdown = manuscript_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("authoritative manuscript is not valid UTF-8") from exc
    current_sections = split_manuscript_sections(current_markdown)
    current_order = [(row["id"], row["heading"], row["level"]) for row in current_sections]
    if sum(row["id"] == section_id for row in current_sections) != 1:
        raise ValueError("target section must exist exactly once")
    candidate = replace_manuscript_section_body(current_markdown, section_id, body)
    candidate_sections = split_manuscript_sections(candidate)
    candidate_order = [(row["id"], row["heading"], row["level"]) for row in candidate_sections]
    if candidate_order != current_order:
        raise ValueError("section edit must preserve ordered ids and headings")
    try:
        lineage = json.loads(lineage_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("authoritative manuscript lineage is invalid") from exc
    if not isinstance(lineage, dict):
        raise ValueError("authoritative manuscript lineage is invalid")
    current_section = next(row for row in current_sections if row["id"] == section_id)
    candidate_section = next(row for row in candidate_sections if row["id"] == section_id)
    pending_rows = lineage.get("pending_scientific_edits", [])
    if not isinstance(pending_rows, list):
        raise ValueError("authoritative manuscript lineage is invalid")
    existing_pending = next(
        (
            row
            for row in pending_rows
            if isinstance(row, dict) and row.get("section_id") == section_id
        ),
        None,
    )
    verified_body = (
        existing_pending.get("verified_body")
        if isinstance(existing_pending, dict) and isinstance(existing_pending.get("verified_body"), str)
        else current_section["body"]
    )
    restored = existing_pending is not None and candidate_section["body"] == verified_body
    reasons = [] if restored else _scientific_edit_reasons(
        section_id,
        verified_body,
        candidate_section["body"],
        lineage,
    )
    if existing_pending is not None and not restored:
        existing_reasons = existing_pending.get("reasons")
        if isinstance(existing_reasons, list):
            reasons = list(
                dict.fromkeys(
                    [
                        *[reason for reason in existing_reasons if isinstance(reason, str) and reason],
                        *reasons,
                    ]
                )
            )
    updated_lineage = refreshed_manuscript_lineage(
        project,
        current_markdown,
        candidate,
        section_id=section_id,
        scientific_reasons=reasons,
    )
    candidate_bytes = candidate.encode("utf-8")
    lineage_payload = (
        json.dumps(updated_lineage, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    ).encode("utf-8")
    manuscript_path = validate_project_file_path(
        project, Path("04_first_draft/first_draft.md"), "MANUSCRIPT_INVALID"
    )
    lineage_path = validate_project_file_path(
        project, Path("04_first_draft/manuscript_lineage.json"), "MANUSCRIPT_LINEAGE_INVALID"
    )
    if manuscript_path.read_bytes() != manuscript_bytes or lineage_path.read_bytes() != lineage_bytes:
        raise ValueError("stale manuscript or lineage state")
    _commit_draft_and_lineage(
        manuscript_path,
        candidate_bytes,
        lineage_path,
        lineage_payload,
        {manuscript_path: manuscript_bytes, lineage_path: lineage_bytes},
    )
    return {
        "ok": True,
        "project_id": project_id,
        "section_id": section_id,
        "manuscript_version": hashlib.sha256(candidate_bytes).hexdigest(),
        "edit_classification": "restored" if restored else "scientific" if reasons else "editorial",
        "needs_evidence_review": bool(updated_lineage.get("pending_scientific_edits")),
        "reasons": reasons,
    }


def export_project_docx(review_root: Path, project_id: str) -> dict[str, Any]:
    project = project_dir(review_root, project_id)
    release = build_project_release(project)
    docx_path = Path(release["docx"])
    return {
        "ok": True,
        "filename": docx_path.name,
        "size": docx_path.stat().st_size,
        "release_status": release["status"],
    }


def project_matrix_payload(review_root: Path, project_id: str) -> dict[str, Any]:
    project = project_dir(review_root, project_id)
    stage = project / "01_matrix_outline"
    return {
        "project_id": project_id,
        "topic": infer_project_topic(project),
        "summary": project_summary(review_root, project_id),
        "paper_reading_notes": read_json_if_exists(stage / "paper_reading_notes.json"),
        "literature_matrix": read_json_if_exists(stage / "literature_matrix.json"),
        "literature_matrix_csv": read_text_if_exists(stage / "literature_matrix.csv"),
        "outline_options_md": read_text_if_exists(stage / "outline_options.md") or read_text_if_exists(stage / "outline.md"),
        "selected_outline_md": read_text_if_exists(stage / "selected_outline.md"),
        "matrix_outline_report_md": read_text_if_exists(stage / "matrix_outline_report.md"),
        "paths": {"stage_dir": str(stage)},
    }


def project_blueprint_payload(review_root: Path, project_id: str) -> dict[str, Any]:
    project = project_dir(review_root, project_id)
    stage = project / "01_matrix_outline"
    return {
        "project_id": project_id,
        "topic": infer_project_topic(project),
        "summary": project_summary(review_root, project_id),
        "section_blueprint": read_json_if_exists(stage / "section_blueprint.json")
        or read_json_if_exists(project / "section_blueprint.json"),
        "section_writing_plan_md": read_text_if_exists(stage / "section_writing_plan.md"),
        "selected_outline_md": read_text_if_exists(stage / "selected_outline.md") or read_text_if_exists(stage / "outline.md"),
        "paths": {"stage_dir": str(stage)},
    }


def project_sections_payload(review_root: Path, project_id: str) -> dict[str, Any]:
    project = project_dir(review_root, project_id)
    stage = project / "02_section_drafting"
    section_files = []
    sections_dir = stage / "sections"
    if sections_dir.exists():
        for path in sorted(sections_dir.glob("*.md")):
            section_files.append({"name": path.name, "path": str(path), "content": read_text_if_exists(path)})
    if not section_files:
        for path in sorted(stage.glob("section_*.md")):
            section_files.append({"name": path.name, "path": str(path), "content": read_text_if_exists(path)})
    return {
        "project_id": project_id,
        "topic": infer_project_topic(project),
        "summary": project_summary(review_root, project_id),
        "section_tasks": read_json_if_exists(stage / "section_tasks.json"),
        "section_drafts": read_json_if_exists(stage / "section_drafts.json"),
        "section_drafts_md": read_text_if_exists(stage / "section_drafts.md"),
        "section_files": section_files,
        "paper_figure_candidates": read_json_if_exists(stage / "paper_figure_candidates.json"),
        "figure_candidates": read_json_if_exists(stage / "figure_candidates.json"),
        "section_drafting_report_md": read_text_if_exists(stage / "section_drafting_report.md"),
        "paths": {"stage_dir": str(stage), "sections_dir": str(sections_dir)},
    }


def project_figures_payload(review_root: Path, project_id: str) -> dict[str, Any]:
    project = project_dir(review_root, project_id)
    draft_stage = project / "02_section_drafting"
    stage = project / "03_figure_redraw"
    figure_manifest = read_json_if_exists(stage / "figure_manifest.json")
    return {
        "project_id": project_id,
        "topic": infer_project_topic(project),
        "summary": project_summary(review_root, project_id),
        "figure_candidates": read_json_if_exists(draft_stage / "figure_candidates.json"),
        "figure_manifest": figure_manifest,
        "redrawn_manifest": read_json_if_exists(stage / "redrawn_figure_manifest.json") or figure_manifest,
        "figure_redraw_report_md": read_text_if_exists(stage / "figure_redraw_report.md"),
        "paths": {"stage_dir": str(stage), "draft_stage_dir": str(draft_stage)},
    }


def is_project_release_docx(path: Path, review_root: Path) -> bool:
    candidate = path if path.is_absolute() else review_root / path
    root = review_root.resolve()
    if candidate.name != "final_draft.docx" or candidate.parent.name != "05_final_audit":
        return False
    project = candidate.parent.parent.resolve()
    if project == root:
        return True
    try:
        relative = project.relative_to(root / "review-projects")
    except ValueError:
        return False
    return len(relative.parts) == 1


def _project_release_artifact_state(project: Path) -> dict[str, Any]:
    project_path = Path(project)
    authoritative_relative = Path("04_first_draft/first_draft.md")
    snapshot_relative = Path("05_final_audit/final_draft.md")
    docx_relative = Path("05_final_audit/final_draft.docx")
    quality_relative = Path("05_final_audit/quality_report.json")
    validate_project_path_components(
        project_path,
        (authoritative_relative, snapshot_relative, docx_relative, quality_relative),
    )
    authoritative_path = validate_project_file_path(
        project_path, authoritative_relative, "MANUSCRIPT_INVALID"
    )
    snapshot_path = project_path / snapshot_relative
    docx_path = project_path / docx_relative
    quality_path = project_path / quality_relative
    authoritative_bytes = authoritative_path.read_bytes()
    snapshot_exists = snapshot_path.is_file()
    snapshot_bytes = snapshot_path.read_bytes() if snapshot_exists else b""
    docx_exists = docx_path.is_file()
    docx_bytes = docx_path.read_bytes() if docx_exists else b""
    quality_report = read_json_if_exists(quality_path)
    if not isinstance(quality_report, dict):
        quality_report = {}
    snapshot_matches = snapshot_exists and snapshot_bytes == authoritative_bytes
    integrity_valid = bool(
        snapshot_matches
        and docx_exists
        and quality_report.get("manuscript_sha256") == hashlib.sha256(authoritative_bytes).hexdigest()
        and quality_report.get("docx_sha256") == hashlib.sha256(docx_bytes).hexdigest()
    )
    return {
        "authoritative_path": authoritative_path,
        "snapshot_path": snapshot_path,
        "docx_path": docx_path,
        "quality_report": quality_report,
        "snapshot_exists": snapshot_exists,
        "snapshot_matches": snapshot_matches,
        "integrity_valid": integrity_valid,
    }


def project_release_docx_is_current(docx_path: Path) -> bool:
    candidate = Path(docx_path)
    project = candidate.parent.parent.resolve()
    state = _project_release_artifact_state(project)
    return bool(
        state["integrity_valid"]
        and state["docx_path"].resolve() == candidate.resolve()
    )


def project_final_payload(review_root: Path, project_id: str) -> dict[str, Any]:
    project = project_dir(review_root, project_id)
    stage = project / "05_final_audit"
    project_relative = project.relative_to(Path(review_root).resolve())
    stage_relative = (project_relative / "05_final_audit").as_posix()
    docx_relative = (project_relative / "05_final_audit" / "final_draft.docx").as_posix()
    artifact_state = _project_release_artifact_state(project)
    authoritative_path = artifact_state["authoritative_path"]
    snapshot_path = artifact_state["snapshot_path"]
    quality_report = artifact_state["quality_report"]
    snapshot_exists = artifact_state["snapshot_exists"]
    snapshot_matches = artifact_state["snapshot_matches"]
    integrity_valid = artifact_state["integrity_valid"]
    current_docx_exists = integrity_valid
    use_release_snapshot = integrity_valid
    if snapshot_exists and not integrity_valid:
        release_status = "RELEASE_OUTDATED"
    elif snapshot_exists:
        release_status = quality_report.get("release_status") or quality_report.get("status") or "IN_PROGRESS"
    else:
        release_status = "IN_PROGRESS"
    visible_quality_report = {
        "status": researcher_safe_markdown(str(quality_report.get("status") or "missing")),
    }
    for key in ("errors", "warnings", "llm_judge_tasks", "human_review_tasks"):
        rows = quality_report.get(key)
        visible_quality_report[key] = [
            researcher_safe_markdown(row) if isinstance(row, str) else "Review item"
            for row in (rows if isinstance(rows, list) else [])
        ]
    checkpoint_log = read_json_if_exists(project / "checkpoint_log.json")
    visible_checkpoints: list[dict[str, Any]] = []
    if isinstance(checkpoint_log, dict) and isinstance(checkpoint_log.get("checkpoints"), list):
        for row in checkpoint_log["checkpoints"]:
            if not isinstance(row, dict):
                continue
            visible_row: dict[str, Any] = {}
            for key in ("index", "checkpoint", "name", "status"):
                value = row.get(key)
                if isinstance(value, str):
                    visible_row[key] = researcher_safe_markdown(value)
                elif isinstance(value, (int, float)) and not isinstance(value, bool):
                    visible_row[key] = value
            visible_checkpoints.append(visible_row)
    return {
        "project_id": project_id,
        "topic": infer_project_topic(project),
        "summary": project_summary(review_root, project_id),
        "final_draft_md": read_text_if_exists(snapshot_path) if use_release_snapshot else read_text_if_exists(authoritative_path),
        "manuscript_source": "release_snapshot" if use_release_snapshot else "authoritative_manuscript",
        "release_status": release_status or "IN_PROGRESS",
        "release_snapshot": {
            "exists": snapshot_exists,
            "matches_authoritative": snapshot_matches,
            "integrity_valid": integrity_valid,
            "docx_exists": current_docx_exists,
        },
        "final_audit_report_md": researcher_safe_markdown(read_text_if_exists(stage / "final_audit_report.md")),
        "quality_report_md": researcher_safe_markdown(read_text_if_exists(stage / "quality_report.md")),
        "quality_report": visible_quality_report,
        "checkpoint_log": {"checkpoints": visible_checkpoints},
        "release_report_md": researcher_safe_markdown(read_text_if_exists(stage / "release_report.md")),
        "final_draft_docx_path": docx_relative if current_docx_exists else "",
        "final_draft_docx_exists": current_docx_exists,
        "paths": {"stage_dir": stage_relative},
    }


def _project_claim_detail_index(
    project: Path,
    project_id: str,
    claim_ids: set[str],
) -> dict[str, dict[str, Any]]:
    projection = read_jsonl_if_exists(project / "02_claims" / "claim_projection.jsonl")
    projection_by_id = {
        visible_text(row.get("claim_id")): row
        for row in projection
        if visible_text(row.get("claim_id")) in claim_ids
    }
    card_claims: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    source_ids = _claim_source_ids(list(projection_by_id.values()))
    cards = read_jsonl_if_exists(project / "01_evidence" / "evidence_cards.jsonl")
    for card in cards:
        candidate = card.get("candidate") if isinstance(card.get("candidate"), dict) else {}
        reviewer = card.get("reviewer") if isinstance(card.get("reviewer"), dict) else {}
        claims = candidate.get("claims") if isinstance(candidate.get("claims"), list) else []
        selected = [
            claim
            for claim in claims
            if isinstance(claim, dict) and visible_text(claim.get("claim_id")) in claim_ids
        ]
        if selected:
            card_claims.append((reviewer, selected))
            source_ids.update(_claim_source_ids(selected))
    source_index = build_project_source_index(project, source_ids)
    details: dict[str, dict[str, Any]] = {}
    for reviewer, claims in card_claims:
        for claim in claims:
            claim_id = visible_text(claim.get("claim_id"))
            if claim_id:
                details[claim_id] = _visible_claim_detail(
                    project,
                    project_id,
                    claim,
                    projection_by_id.get(claim_id, {}),
                    reviewer,
                    source_index,
                )
    for claim_id, projected in projection_by_id.items():
        details.setdefault(
            claim_id,
            _visible_claim_detail(project, project_id, {}, projected, {}, source_index),
        )
    return details


def _draft_claim_lineage(
    project: Path,
    project_id: str,
    lineage: dict[str, Any],
) -> list[dict[str, Any]]:
    entries = [entry for entry in manuscript_lineage_entries(lineage) if isinstance(entry, dict)]
    claim_ids = {
        claim_id
        for entry in entries
        for claim_id in (visible_text(entry.get("claim_id")),)
        if claim_id
    }
    details = _project_claim_detail_index(project, project_id, claim_ids)
    rows: list[dict[str, Any]] = []
    for entry in entries:
        claim_id = visible_text(entry.get("claim_id"))
        if not claim_id:
            continue
        detail = details.get(claim_id, {"claim_id": claim_id})
        row = dict(detail)
        row["section_id"] = visible_text(entry.get("section_id"))
        row["text_span"] = visible_text(
            entry.get("text_span") or entry.get("manuscript_text") or entry.get("text")
        )
        rows.append(row)
    return rows


def _draft_revision_status(lineage: dict[str, Any]) -> dict[str, Any]:
    raw_pending = lineage.get("pending_scientific_edits", [])
    pending: list[dict[str, Any]] = []
    if not isinstance(raw_pending, list):
        raise ValueError("pending_scientific_edits must be a list")
    for row in raw_pending:
        if not isinstance(row, dict):
            raise ValueError("pending_scientific_edits rows must be objects")
        section_id = row.get("section_id")
        verified_body = row.get("verified_body")
        raw_reasons = row.get("reasons")
        if (
            not isinstance(section_id, str)
            or not section_id.strip()
            or not isinstance(verified_body, str)
            or not isinstance(raw_reasons, list)
            or not raw_reasons
            or not all(isinstance(reason, str) and reason.strip() for reason in raw_reasons)
        ):
            raise ValueError("pending_scientific_edits row is invalid")
        pending.append(
            {
                "section_id": section_id.strip(),
                "verified_body": verified_body,
                "reasons": [reason.strip() for reason in raw_reasons],
            }
        )
    return {
        "needs_evidence_review": bool(pending),
        "pending_scientific_edits": pending,
    }


def project_draft_payload(review_root: Path, project_id: str) -> dict[str, Any]:
    project = project_dir(review_root, project_id)
    stage_dir = project / "04_first_draft"
    project_relative = project.relative_to(Path(review_root).resolve())
    stage_relative = (project_relative / "04_first_draft").as_posix()
    manuscript_relative = Path("04_first_draft/first_draft.md")
    lineage_relative = Path("04_first_draft/manuscript_lineage.json")
    validate_project_path_components(project, (manuscript_relative, lineage_relative))
    manuscript_bytes = project_nonblank_text_file_bytes(project, manuscript_relative)
    manuscript_available = manuscript_bytes is not None
    manuscript_bytes = manuscript_bytes or b""
    first_draft_md = manuscript_bytes.decode("utf-8") if manuscript_available else ""
    lineage = (
        validated_draft_manuscript_lineage(project, first_draft_md)
        if manuscript_available
        else {}
    )
    figures_manifest = read_json_if_exists(project / "03_figure_redraw" / "redrawn_figure_manifest.json") or {}
    redrawn = []
    for row in (figures_manifest.get("figures") or []):
        if isinstance(row, dict):
            redrawn.append(
                {
                    key: researcher_safe_markdown(str(row[key]))
                    for key in ("figure_id", "title", "caption", "status")
                    if row.get(key) is not None
                }
            )
    return {
        "project_id": project_id,
        "topic": infer_project_topic(project),
        "summary": next((p for p in list_review_projects(review_root) if p["project_id"] == project_id), None),
        "available": manuscript_available,
        "manuscript_version": hashlib.sha256(manuscript_bytes).hexdigest() if manuscript_available else "",
        "sections": split_manuscript_sections(first_draft_md) if first_draft_md else [],
        "claim_lineage": _draft_claim_lineage(project, project_id, lineage) if manuscript_available else [],
        "revision_status": _draft_revision_status(lineage) if manuscript_available else {
            "needs_evidence_review": False,
            "pending_scientific_edits": [],
        },
        "merge_report_md": researcher_safe_markdown(read_text_if_exists(stage_dir / "merge_report.md")),
        "remaining_issues_md": researcher_safe_markdown(read_text_if_exists(stage_dir / "remaining_issues.md")),
        "redrawn_figures": redrawn,
        "paths": {
            "stage_dir": stage_relative,
            "first_draft_base_dir": stage_relative,
        },
    }


def checkpoint_payload(review_root: Path) -> dict[str, Any]:
    if is_direct_output_root(review_root):
        payload = read_json_if_exists(review_root / "checkpoint_log.json") or {}
        return {
            "project_id": direct_project_id(review_root),
            "checkpoints": payload.get("checkpoints", payload if isinstance(payload, list) else []),
            "paths": {"checkpoint_log": str(review_root / "checkpoint_log.json")},
        }
    projects = []
    for project in list_review_projects(review_root):
        project_id = project.get("project_id")
        if not project_id:
            continue
        path = project_dir(review_root, str(project_id)) / "checkpoint_log.json"
        payload = read_json_if_exists(path) or {}
        projects.append(
            {
                "project_id": project_id,
                "checkpoints": payload.get("checkpoints", payload if isinstance(payload, list) else []),
                "path": str(path),
            }
        )
    return {"projects": projects}


def dashboard_assets(view_root: Path) -> tuple[Path, ...]:
    dashboard = view_root / "assets" / "dashboard"
    library_path = dashboard / "library.html"
    discovery_path = dashboard / "discovery.html"
    matrix_path = dashboard / "matrix.html"
    blueprint_path = dashboard / "blueprint.html"
    sections_path = dashboard / "sections.html"
    figures_path = dashboard / "figures.html"
    draft_path = dashboard / "draft.html"
    final_path = dashboard / "final.html"
    review_path = dashboard / "review.html"
    paths = [library_path, discovery_path, matrix_path, blueprint_path, sections_path, figures_path, draft_path, final_path, review_path]
    if any(not path.exists() for path in paths):
        raise FileNotFoundError(f"dashboard assets not found under {view_root / 'assets' / 'dashboard'}")
    return tuple(paths)


def run(args: argparse.Namespace) -> int:
    review_root = Path(args.review_root).resolve()
    view_root = Path(__file__).resolve().parent
    (
        library_app_path,
        discovery_app_path,
        matrix_app_path,
        blueprint_app_path,
        sections_app_path,
        figures_app_path,
        draft_app_path,
        final_app_path,
        review_app_path,
    ) = dashboard_assets(view_root)
    DashboardHandler.review_root = review_root
    DashboardHandler.library_app_path = library_app_path
    DashboardHandler.discovery_app_path = discovery_app_path
    DashboardHandler.matrix_app_path = matrix_app_path
    DashboardHandler.blueprint_app_path = blueprint_app_path
    DashboardHandler.sections_app_path = sections_app_path
    DashboardHandler.figures_app_path = figures_app_path
    DashboardHandler.draft_app_path = draft_app_path
    DashboardHandler.final_app_path = final_app_path
    DashboardHandler.review_app_path = review_app_path
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"Serving dashboard at http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve local review metadata dashboard.")
    parser.add_argument("--review-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
