#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import mimetypes
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

PDF_RENDER_SEMAPHORE = threading.BoundedSemaphore(2)

from review_writer.project.vertical_review import (  # noqa: E402
    AWAITING_BRIEF_CONFIRMATION,
    VerticalReviewError,
    apply_risk_decisions,
    benchmark_metrics,
    confirm_review_brief,
)
from review_writer.acquisition.manifest_identity import normalize_doi  # noqa: E402
from review_writer.acquisition.manual_archive import (  # noqa: E402
    DEFAULT_MAX_ARCHIVE_BYTES,
    ManualArchiveError,
    SOURCE_TRANSACTION_LOCK,
    import_manual_archive,
)
from review_writer.delivery.project_release import (  # noqa: E402
    PROJECT_RELEASE_LOCK,
    ProjectReleaseError,
    build_project_release,
    is_reparse_component,
    manuscript_lineage_entries,
    new_route_release_docx_is_current,
    project_figure_validation_is_current,
    refreshed_manuscript_lineage,
    replace_manuscript_section_body,
    split_manuscript_sections,
    validate_project_file_path,
    validate_project_path_components,
    validated_draft_manuscript_lineage,
    _validated_image,
)
from review_writer.delivery.figure_policy import FigurePolicyError, _image_binding  # noqa: E402
from review_writer.project.parse_quality import (  # noqa: E402
    HUMAN_ACTIONS,
    ParseQualityError,
    apply_parse_quality_decision,
    parse_decision_revision,
    parse_quality_state,
    project_parse_quality_state,
)
from review_writer.project.workflow_projection import workflow_state  # noqa: E402
from review_writer.project.paper_evidence import (  # noqa: E402
    PaperEvidenceError,
    apply_paper_evidence_decision,
    paper_evidence_state,
)
from review_writer.project.synthesis import (  # noqa: E402
    SynthesisError,
    apply_comparison_protocol_decision,
    apply_synthesis_decision,
    comparison_protocol_state,
    coverage_map_state,
    synthesis_state,
)
from review_writer.project.section_contract import (  # noqa: E402
    SectionContractError,
    apply_section_contract_decision,
    section_contract_state,
)
from review_writer.project.review_figures import (  # noqa: E402
    ReviewFigureError,
    build_source_figure_registry,
    synthesis_figure_placeholders,
)
from review_writer.project.source_truth import (  # noqa: E402
    SOURCE_TRUTH_ROOT,
    SourceTruthError,
    canonical_digest,
    load_source_truth_bundle,
    source_truth_asset,
)


_RESEARCHER_SHA256_RE = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{64}(?![0-9A-Fa-f])")
_DRAFT_CLAIM_MARKER_RE = re.compile(
    r"(?:\[claim:[A-Za-z0-9._:-]+\]|<!--\s*claim(?:_id)?\s*:\s*[A-Za-z0-9._:-]+\s*-->)",
    flags=re.IGNORECASE,
)
_DASHBOARD_IMAGE_RE = re.compile(
    r"!\[[^\]\r\n]*\]\((?:<(?P<angle>[^>\r\n]+)>|(?P<plain>[^\s()<>\"']+))"
    r"(?:\s+[\"'][^\"'\r\n]*[\"'])?\)"
)
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
SOURCE_SUPPLEMENT_MAX_BODY_BYTES = 16 * 1024
SOURCE_SUPPLEMENT_MAX_DOI_CHARS = 512
SOURCE_SUPPLEMENT_MAX_TITLE_CHARS = 2_000


class WorkspaceStaleError(ValueError):
    """Optimistic-concurrency conflict for the evidence workspace."""


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
        elif parsed.path.startswith("/api/project/") and parsed.path.endswith("/figure"):
            project_id = project_id_from_route(parsed.path, "figure")
            if project_id is None:
                self.send_error(HTTPStatus.NOT_FOUND, "project route not found")
                return
            query = parse_qs(parsed.query, keep_blank_values=True)
            indices = query.get("index", [])
            if set(query) != {"index"} or len(indices) != 1 or not re.fullmatch(r"0|[1-9][0-9]*", indices[0]):
                self.send_error(HTTPStatus.BAD_REQUEST, "figure index is invalid")
                return
            self.handle_project_figure_get(project_id, int(indices[0]))
        elif parsed.path.startswith("/api/project/") and parsed.path.endswith("/source-figure"):
            project_id = project_id_from_route(parsed.path, "source-figure")
            if project_id is None:
                self.send_error(HTTPStatus.NOT_FOUND, "project route not found")
                return
            query = parse_qs(parsed.query, keep_blank_values=True)
            figure_ids = query.get("figure_id", [])
            if set(query) != {"figure_id"} or len(figure_ids) != 1 or not figure_ids[0]:
                self.send_error(HTTPStatus.BAD_REQUEST, "figure_id is invalid")
                return
            self.handle_project_source_figure_get(project_id, figure_ids[0])
        elif parsed.path.startswith("/api/project/") and parsed.path.endswith("/review-state"):
            project_id = project_id_from_route(parsed.path, "review-state")
            if project_id is None:
                self.send_error(HTTPStatus.NOT_FOUND, "project route not found")
                return
            self.handle_project_review_state_get(project_id)
        elif parsed.path.startswith("/api/project/") and parsed.path.endswith("/paper-evidence"):
            project_id = project_id_from_route(parsed.path, "paper-evidence")
            if project_id is None:
                self.send_error(HTTPStatus.NOT_FOUND, "project route not found")
                return
            self.handle_project_workspace_get(project_id, "paper-evidence")
        elif parsed.path.startswith("/api/project/") and parsed.path.endswith("/comparison-protocol"):
            project_id = project_id_from_route(parsed.path, "comparison-protocol")
            if project_id is None:
                self.send_error(HTTPStatus.NOT_FOUND, "project route not found")
                return
            self.handle_project_workspace_get(project_id, "comparison-protocol")
        elif parsed.path.startswith("/api/project/") and parsed.path.endswith("/synthesis"):
            project_id = project_id_from_route(parsed.path, "synthesis")
            if project_id is None:
                self.send_error(HTTPStatus.NOT_FOUND, "project route not found")
                return
            self.handle_project_workspace_get(project_id, "synthesis")
        elif parsed.path.startswith("/api/project/") and parsed.path.endswith("/section-contracts"):
            project_id = project_id_from_route(parsed.path, "section-contracts")
            if project_id is None:
                self.send_error(HTTPStatus.NOT_FOUND, "project route not found")
                return
            self.handle_project_workspace_get(project_id, "section-contracts")
        elif parsed.path.startswith("/api/project/") and parsed.path.endswith("/review-figures"):
            project_id = project_id_from_route(parsed.path, "review-figures")
            if project_id is None:
                self.send_error(HTTPStatus.NOT_FOUND, "project route not found")
                return
            self.handle_project_workspace_get(project_id, "review-figures")
        elif parsed.path.startswith("/api/project/") and parsed.path.endswith("/draft"):
            project_id = project_id_from_route(parsed.path, "draft")
            if project_id is None:
                self.send_error(HTTPStatus.NOT_FOUND, "project route not found")
                return
            self.handle_project_draft_get(project_id)
        elif parsed.path.startswith("/api/project/"):
            parts = parsed.path.strip("/").split("/")
            if len(parts) == 6 and parts[3] == "source" and parts[5] in {"pdf", "pdf-page", "parsed-markdown"}:
                query = parse_qs(parsed.query, keep_blank_values=True)
                page: str | None = None
                if parts[5] == "pdf-page":
                    values = query.get("page", [])
                    if (
                        set(query) != {"page"}
                        or len(values) != 1
                        or not re.fullmatch(r"[1-9][0-9]*", values[0])
                    ):
                        self.send_error(HTTPStatus.BAD_REQUEST, "PDF page is invalid")
                        return
                    page = values[0]
                self.handle_project_parse_asset_get(
                    unquote(parts[2]),
                    unquote(parts[4]),
                    unquote(parts[5]),
                    page=page,
                )
            elif len(parts) == 4:
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
        if parsed.path.startswith("/api/project/") and parsed.path.endswith("/parse-quality"):
            project_id = project_id_from_route(parsed.path, "parse-quality")
            if project_id is None:
                self.send_error(HTTPStatus.NOT_FOUND, "project route not found")
                return
            self.handle_project_parse_quality_put(project_id)
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
        for action in ("paper-evidence", "comparison-protocol", "synthesis", "section-contracts", "review-figures"):
            if parsed.path.startswith("/api/project/") and parsed.path.endswith(f"/{action}"):
                project_id = project_id_from_route(parsed.path, action)
                if project_id is None:
                    self.send_error(HTTPStatus.NOT_FOUND, "project route not found")
                    return
                self.handle_project_workspace_put(project_id, action)
                return
        if parsed.path.startswith("/api/discovery/"):
            project_id = unquote(parsed.path.rsplit("/", 1)[-1])
            query = parse_qs(parsed.query)
            self.handle_discovery_put(project_id, confirm=bool(query.get("confirm")))
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/project/") and parsed.path.endswith("/source-mapping"):
            project_id = project_id_from_route(parsed.path, "source-mapping")
            if project_id is None:
                self.send_error(HTTPStatus.NOT_FOUND, "project route not found")
                return
            self.handle_project_source_mapping_post(project_id)
            return
        if parsed.path.startswith("/api/project/") and parsed.path.endswith("/source-supplement"):
            project_id = project_id_from_route(parsed.path, "source-supplement")
            if project_id is None:
                self.send_error(HTTPStatus.NOT_FOUND, "project route not found")
                return
            self.handle_project_source_supplement_post(project_id)
            return
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

    def handle_project_source_mapping_post(self, project_id: str) -> None:
        try:
            project = project_dir(self.review_root, project_id)
        except ValueError:
            self.send_error(HTTPStatus.BAD_REQUEST, "invalid project")
            return
        if not project.is_dir():
            self.send_error(HTTPStatus.NOT_FOUND, "project not found")
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > 16 * 1024:
                raise ValueError("mapping body size is invalid")
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(data, dict) or set(data) != {"member_id", "download_id"}:
                raise ValueError("mapping body is invalid")
            member_id = data.get("member_id")
            download_id = data.get("download_id")
            if (
                not isinstance(member_id, str)
                or not re.fullmatch(r"MEMBER-\d{4}", member_id)
                or not isinstance(download_id, str)
                or not download_id
            ):
                raise ValueError("mapping identifiers are invalid")

            with SOURCE_TRANSACTION_LOCK:
                manifest_relative = Path("00_discovery/acquisition_manifest.json")
                receipt_relative = Path("00_sources/manual_import_receipt.json")
                validate_project_path_components(
                    project,
                    (manifest_relative, receipt_relative, SOURCE_ARCHIVE_RELATIVE),
                )
                receipt = read_json_if_exists(project / receipt_relative)
                unresolved = receipt.get("unresolved") if isinstance(receipt, dict) else None
                if not isinstance(unresolved, list):
                    raise ValueError("source mapping receipt is invalid")
                matches = [
                    row
                    for row in unresolved
                    if isinstance(row, dict) and row.get("member_id") == member_id
                ]
                if (
                    len(matches) != 1
                    or not isinstance(matches[0].get("download_ids"), list)
                    or download_id not in matches[0]["download_ids"]
                ):
                    raise ValueError("source mapping is not a listed candidate")

                overrides: dict[str, str] = {}
                prior = receipt.get("confirmed_mappings", [])
                if not isinstance(prior, list):
                    raise ValueError("source mapping receipt is invalid")
                for row in prior:
                    if (
                        not isinstance(row, dict)
                        or not re.fullmatch(r"MEMBER-\d{4}", row.get("member_id", ""))
                        or not isinstance(row.get("download_id"), str)
                        or not row["download_id"]
                    ):
                        raise ValueError("source mapping receipt is invalid")
                    overrides[row["member_id"]] = row["download_id"]
                overrides[member_id] = download_id
                import_manual_archive(
                    project / manifest_relative,
                    project / SOURCE_ARCHIVE_RELATIVE,
                    project / "00_sources",
                    member_overrides=overrides,
                )
        except (json.JSONDecodeError, UnicodeError, OSError, ValueError, ManualArchiveError):
            self.send_error(HTTPStatus.BAD_REQUEST, "source mapping is invalid")
            return
        self.send_json({"status": "mapped", "message": "文件归属已确认"})

    def handle_project_source_supplement_post(self, project_id: str) -> None:
        try:
            project = project_dir(self.review_root, project_id)
        except ValueError:
            self.send_error(HTTPStatus.BAD_REQUEST, "invalid project")
            return
        if not project.is_dir():
            self.send_error(HTTPStatus.NOT_FOUND, "project not found")
            return
        raw_length = self.headers.get("Content-Length")
        if not isinstance(raw_length, str) or re.fullmatch(r"[0-9]+", raw_length) is None:
            self.send_error(HTTPStatus.BAD_REQUEST, "source supplement length is invalid")
            return
        normalized_length = raw_length.lstrip("0") or "0"
        maximum_length = str(SOURCE_SUPPLEMENT_MAX_BODY_BYTES)
        if len(normalized_length) > len(maximum_length) or (
            len(normalized_length) == len(maximum_length)
            and normalized_length > maximum_length
        ):
            self.send_error(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "source supplement exceeds the size limit",
            )
            return
        length = int(normalized_length)
        if length <= 0:
            self.send_error(HTTPStatus.BAD_REQUEST, "source supplement body is empty")
            return
        if length > SOURCE_SUPPLEMENT_MAX_BODY_BYTES:
            self.send_error(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "source supplement exceeds the size limit",
            )
            return
        try:
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError("source supplement body is incomplete")
            data = json.loads(body.decode("utf-8"))
            result = add_project_source_supplement(project, data)
        except (json.JSONDecodeError, OSError, ValueError):
            self.send_error(HTTPStatus.BAD_REQUEST, "source supplement is invalid")
            return
        self.send_json(result, status=HTTPStatus.CREATED)

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
        with SOURCE_TRANSACTION_LOCK:
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
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length or 0)
        except ValueError:
            length = -1
        release_level: str | None = None
        new_contract = length != 0
        if new_contract:
            try:
                if (
                    length < 1
                    or length > 4096
                    or self.headers.get_content_type() != "application/json"
                ):
                    raise ValueError
                request = json.loads(self.rfile.read(length).decode("utf-8"))
                if (
                    not isinstance(request, dict)
                    or set(request) != {"release_level"}
                    or request.get("release_level")
                    not in {"SELF_REVIEWED_DRAFT", "EXPERT_REVIEWED_RELEASE"}
                ):
                    raise ValueError
                release_level = request["release_level"]
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                self.send_json(
                    {
                        "ok": False,
                        "error_code": "RELEASE_REQUEST_INVALID",
                        "message": (
                            "release request must contain exactly one supported release_level"
                        ),
                    },
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
        try:
            result = (
                export_project_docx(
                    self.review_root, project_id, release_level=release_level
                )
                if new_contract
                else export_project_docx(self.review_root, project_id)
            )
        except ProjectReleaseError as exc:
            if not new_contract:
                self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            status = (
                HTTPStatus.INTERNAL_SERVER_ERROR
                if exc.code in {"DOCX_CONVERTER_MISSING", "DOCX_EXPORT_FAILED"}
                else HTTPStatus.CONFLICT
            )
            self.send_json(
                {
                    "ok": False,
                    "error_code": exc.code,
                    "message": str(exc).split(": ", 1)[-1],
                },
                status=status,
            )
            return
        except ValueError as exc:
            if new_contract:
                self.send_json(
                    {
                        "ok": False,
                        "error_code": "PROJECT_INVALID",
                        "message": str(exc),
                    },
                    status=HTTPStatus.BAD_REQUEST,
                )
            else:
                self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        except Exception:
            if not new_contract:
                raise
            self.send_json(
                {
                    "ok": False,
                    "error_code": "RELEASE_INTERNAL_ERROR",
                    "message": "release service failed",
                },
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
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
        try:
            publication = _validated_discovery_publication(path.parents[1])
        except ValueError:
            self.send_error(HTTPStatus.CONFLICT, "discovery selection is inconsistent")
            return
        if publication is None:
            self.send_error(HTTPStatus.NOT_FOUND, "discovery data not found")
            return
        self.send_json(publication[0])

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
        with SOURCE_TRANSACTION_LOCK:
            selected = selected_from_combined(data.get("results", []), project_id)
            selected["human_confirmed"] = bool(confirm)
            selection_digest = _canonical_selection_digest(selected)
            data["selection_digest"] = selection_digest
            selected["selection_digest"] = selection_digest
            human_state = {
                "project_id": project_id,
                "status": "confirmed" if confirm else "pending",
                "confirmed_at": now_utc() if confirm else None,
                "selection_digest": selection_digest,
            }
            _replace_json_pair(
                [
                    (path, data),
                    (path.parent / "selected_discovery_results.json", selected),
                    (path.parent / "human_check_state.json", human_state),
                ]
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

    def handle_project_parse_asset_get(
        self,
        project_id: str,
        source_id: str,
        kind: str,
        *,
        page: str | None = None,
    ) -> None:
        try:
            project = project_dir(self.review_root, project_id)
            path = project_parse_source_asset(
                project,
                source_id,
                "pdf" if kind == "pdf-page" else kind,
            )
        except (OSError, ParseQualityError, SourceTruthError, ValueError):
            self.send_error(HTTPStatus.NOT_FOUND, "source asset is unavailable")
            return
        if kind == "pdf-page":
            try:
                page_count = project_parse_source_page_count(project, source_id)
            except SourceTruthError:
                self.send_error(HTTPStatus.NOT_FOUND, "source asset is unavailable")
                return
            page_limit = str(page_count)
            if page is None or len(page) > len(page_limit) or (
                len(page) == len(page_limit) and page > page_limit
            ):
                self.send_error(HTTPStatus.BAD_REQUEST, "PDF page is invalid")
                return
            page_number = int(page)
            try:
                payload = render_pdf_page(path, page_number)
            except (OSError, RuntimeError, subprocess.SubprocessError, ValueError):
                self.send_error(HTTPStatus.UNPROCESSABLE_ENTITY, "PDF page preview is unavailable")
                return
            self.send_bytes(
                payload,
                "image/png",
                extra_headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
            )
            return
        content_type = "application/pdf" if kind == "pdf" else "text/markdown; charset=utf-8"
        self.send_file(
            path,
            content_type,
            extra_headers={
                "Content-Disposition": f"inline; filename*=UTF-8''{quote(path.name, safe='')}",
                "X-Content-Type-Options": "nosniff",
            },
        )

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

    def handle_project_parse_quality_put(self, project_id: str) -> None:
        try:
            project = project_dir(self.review_root, project_id)
        except ValueError:
            self.send_json({"error": "项目不可用"}, status=HTTPStatus.BAD_REQUEST)
            return
        if not project.is_dir():
            self.send_json({"error": "项目不存在"}, status=HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > 16 * 1024:
                raise ValueError("invalid body size")
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            result = write_project_parse_quality_decision(self.review_root, project_id, data)
        except (json.JSONDecodeError, UnicodeError):
            self.send_json({"error": "决定内容无法读取"}, status=HTTPStatus.BAD_REQUEST)
            return
        except ParseQualityError as exc:
            if exc.code in {
                "PARSE_QUALITY_MISSING",
                "PARSE_QUALITY_STALE",
                "SOURCE_TRUTH_MISSING",
            }:
                self.send_json(
                    {"error": "解析内容已更新，请重新核对"},
                    status=HTTPStatus.CONFLICT,
                )
            else:
                self.send_json({"error": "决定未保存，请检查后重试"}, status=HTTPStatus.BAD_REQUEST)
            return
        except (SourceTruthError, ValueError):
            self.send_json({"error": "决定未保存，请检查后重试"}, status=HTTPStatus.BAD_REQUEST)
            return
        self.send_json(result)

    def handle_project_workspace_get(self, project_id: str, kind: str) -> None:
        try:
            project = project_dir(self.review_root, project_id)
            if not project.is_dir():
                raise ValueError("project not found")
            payload = project_workspace_payload(self.review_root, project_id, kind)
        except (ValueError, PaperEvidenceError, SynthesisError, SectionContractError, ReviewFigureError, SourceTruthError):
            self.send_json({"error": "工作台数据暂不可用"}, status=HTTPStatus.NOT_FOUND)
            return
        self.send_json(payload)

    def handle_project_workspace_put(self, project_id: str, kind: str) -> None:
        try:
            project = project_dir(self.review_root, project_id)
            if not project.is_dir():
                raise ValueError("project not found")
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > 64 * 1024:
                raise ValueError("invalid body size")
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            result = write_project_workspace_decision(self.review_root, project_id, kind, data)
        except WorkspaceStaleError:
            self.send_json({"error": "内容已更新，请刷新后重新核对"}, status=HTTPStatus.CONFLICT)
            return
        except (PaperEvidenceError, SynthesisError, SectionContractError, ReviewFigureError) as exc:
            code = getattr(exc, "code", "WORKSPACE_INVALID")
            status = HTTPStatus.CONFLICT if code.endswith("STALE") or code == "WORKSPACE_STALE" else HTTPStatus.BAD_REQUEST
            self.send_json({"error": "内容已更新，请刷新后重新核对" if status == HTTPStatus.CONFLICT else "决定未保存，请检查后重试"}, status=status)
            return
        except (json.JSONDecodeError, UnicodeError, ValueError):
            self.send_json({"error": "决定内容无法读取"}, status=HTTPStatus.BAD_REQUEST)
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
            "parse-quality": project_parse_quality_payload,
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

    def handle_project_figure_get(self, project_id: str, index: int) -> None:
        try:
            project = project_dir(self.review_root, project_id)
            path, content_type = project_figure_image(project, index)
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND, "figure is unavailable")
            return
        self.send_file(path, content_type)

    def handle_project_source_figure_get(self, project_id: str, figure_id: str) -> None:
        try:
            project = project_dir(self.review_root, project_id)
            registry = read_json_if_exists(project / "03_figures/source_figure_registry.json")
            rows = registry.get("figures", []) if isinstance(registry, dict) else []
            row = next((item for item in rows if isinstance(item, dict) and item.get("figure_id") == figure_id), None)
            if not isinstance(row, dict) or not isinstance(row.get("asset_path"), str):
                raise ValueError("figure not found")
            image_path = validate_project_file_path(project, Path(row["asset_path"]), "FIGURE_ASSET_INVALID")
            if hashlib.sha256(image_path.read_bytes()).hexdigest() != row.get("asset_sha256"):
                raise ValueError("figure hash mismatch")
            content_type = mimetypes.guess_type(image_path.name)[0]
            if not content_type or not content_type.startswith("image/"):
                raise ValueError("figure type invalid")
        except (OSError, ProjectReleaseError, ValueError):
            self.send_error(HTTPStatus.NOT_FOUND, "source figure is unavailable")
            return
        self.send_file(image_path, content_type, extra_headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

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
        if is_project_release_docx(path, self.review_root):
            try:
                current = project_release_docx_is_current(path)
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

    def send_bytes(
        self,
        payload: bytes,
        content_type: str,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(payload)
        except BrokenPipeError:
            pass

    def send_file(
        self,
        path: Path,
        content_type: str,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        try:
            size = path.stat().st_size
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(size))
            for key, value in (extra_headers or {}).items():
                self.send_header(key, value)
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


def _canonical_selection_digest(selected: dict[str, Any]) -> str:
    keywords = selected.get("keywords")
    local_papers = selected.get("local_papers")
    web_papers = selected.get("web_papers")
    if (
        not isinstance(keywords, list)
        or not all(isinstance(row, dict) for row in keywords)
        or not isinstance(local_papers, list)
        or not all(isinstance(row, dict) for row in local_papers)
        or not isinstance(web_papers, list)
        or not all(isinstance(row, dict) for row in web_papers)
    ):
        raise ValueError("discovery selection is invalid")
    canonical = {
        "human_confirmed": selected.get("human_confirmed") is True,
        "keywords": sorted(
            (
                {
                    "category": visible_text(row.get("category")),
                    "keyword": visible_text(row.get("keyword")),
                }
                for row in keywords
            ),
            key=lambda row: (row["keyword"], row["category"]),
        ),
        "local_papers": sorted(
            (
                {
                    "matched_keywords": sorted(
                        visible_text(value)
                        for value in row.get("matched_keywords", [])
                        if visible_text(value)
                    ),
                    "paper_id": visible_text(row.get("paper_id")),
                    "role": visible_text(row.get("role")),
                }
                for row in local_papers
            ),
            key=lambda row: (row["paper_id"], row["role"], row["matched_keywords"]),
        ),
        "project_id": visible_text(selected.get("project_id")),
        "web_papers": sorted(
            (
                {
                    "doi": visible_text(row.get("doi")),
                    "matched_keyword": visible_text(row.get("matched_keyword")),
                    "paper_id": visible_text(row.get("paper_id")),
                    "role": visible_text(row.get("role")),
                    "title": visible_text(row.get("title")),
                    "url": visible_text(row.get("url")),
                }
                for row in web_papers
            ),
            key=lambda row: (
                row["paper_id"],
                row["doi"],
                row["url"],
                row["title"],
                row["matched_keyword"],
                row["role"],
            ),
        ),
    }
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validated_discovery_publication(
    project: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    discovery = project / "00_discovery"
    paths = (
        discovery / "combined_results_by_keyword.json",
        discovery / "selected_discovery_results.json",
        discovery / "human_check_state.json",
    )
    with SOURCE_TRANSACTION_LOCK:
        exists = tuple(path.is_file() for path in paths)
        if not any(exists):
            return None
        if not all(exists):
            raise ValueError("discovery publication is incomplete")
        payloads = tuple(read_json_if_exists(path) for path in paths)
        if not all(isinstance(payload, dict) for payload in payloads):
            raise ValueError("discovery publication is invalid")
        combined, selected, human_state = payloads
        raw_digests = tuple(payload.get("selection_digest") for payload in payloads)
        if not all(isinstance(digest, str) for digest in raw_digests) or len(
            set(raw_digests)
        ) != 1:
            raise ValueError("discovery publication versions differ")
        selection_digest = raw_digests[0]
        if re.fullmatch(r"[0-9a-f]{64}", selection_digest) is None:
            raise ValueError("discovery publication digest is invalid")
        status = human_state.get("status")
        if (
            selected.get("project_id") != project.name
            or human_state.get("project_id") != project.name
            or status not in {"confirmed", "pending"}
            or selected.get("human_confirmed") != (status == "confirmed")
        ):
            raise ValueError("discovery publication identity is invalid")
        groups = combined.get("results")
        if not isinstance(groups, list) or not all(isinstance(group, dict) for group in groups):
            raise ValueError("discovery publication results are invalid")
        try:
            expected_selected = selected_from_combined(groups, project.name)
            expected_selected["human_confirmed"] = status == "confirmed"
            expected_digest = _canonical_selection_digest(expected_selected)
            selected_digest = _canonical_selection_digest(selected)
        except (TypeError, ValueError) as exc:
            raise ValueError("discovery publication selection is invalid") from exc
        if selection_digest != expected_digest or selection_digest != selected_digest:
            raise ValueError("discovery publication selection differs")
        return combined, selected, human_state


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


def _canonical_source_identifier(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("canonical source identifiers must be nonempty strings")
    return value.strip()


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


def _researcher_disposition_label(value: Any) -> str:
    return {
        "INCLUDE_FOR_FULL_TEXT": "用户要求纳入",
        "EXCLUDE": "用户要求排除",
    }.get(visible_text(value).upper(), "等待用户决定")


def _system_recommendation_label(value: Any) -> str:
    return {
        "RESEARCHER_SUPPLIED": "待系统简要复核",
        "INCLUDE": "系统建议纳入",
        "EXCLUDE": "系统建议排除",
    }.get(visible_text(value).upper(), "系统尚未给出建议")


def _stage_json(path: Path, payload: dict[str, Any]) -> Path:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        json.dump(payload, handle, ensure_ascii=False, allow_nan=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return temporary


def _replace_json_pair(updates: list[tuple[Path, dict[str, Any]]]) -> None:
    staged: dict[Path, Path] = {}
    backups: dict[Path, Path | None] = {}
    replaced: list[Path] = []
    try:
        for path, payload in updates:
            path.parent.mkdir(parents=True, exist_ok=True)
            staged[path] = _stage_json(path, payload)
            if path.exists():
                descriptor, backup_name = tempfile.mkstemp(
                    dir=path.parent,
                    prefix=f".{path.name}.",
                    suffix=".backup",
                )
                os.close(descriptor)
                backup = Path(backup_name)
                backup.unlink()
                os.link(path, backup)
                backups[path] = backup
            else:
                backups[path] = None
        try:
            for path, _ in updates:
                os.replace(staged[path], path)
                staged.pop(path)
                replaced.append(path)
        except BaseException as publication_error:
            rollback_error: BaseException | None = None
            for path in reversed(replaced):
                backup = backups[path]
                try:
                    if backup is None:
                        path.unlink(missing_ok=True)
                    else:
                        os.replace(backup, path)
                        backups[path] = None
                except BaseException as exc:
                    rollback_error = rollback_error or exc
            if rollback_error is not None:
                raise OSError("source supplement rollback failed") from publication_error
            raise
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)
        for backup in backups.values():
            if backup is not None:
                backup.unlink(missing_ok=True)


def add_project_source_supplement(project: Path, data: Any) -> dict[str, Any]:
    with SOURCE_TRANSACTION_LOCK:
        return _add_project_source_supplement_unlocked(project, data)


def _add_project_source_supplement_unlocked(project: Path, data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("source supplement must be an object")
    doi_value = data.get("doi", "")
    title_value = data.get("title", "")
    if (
        not isinstance(doi_value, str)
        or len(doi_value) > SOURCE_SUPPLEMENT_MAX_DOI_CHARS
        or not isinstance(title_value, str)
        or len(title_value) > SOURCE_SUPPLEMENT_MAX_TITLE_CHARS
    ):
        raise ValueError("source supplement identity is too large")
    doi_raw = doi_value.strip()
    doi = normalize_doi(doi_raw) or ""
    title = title_value.strip()
    if doi_raw and not doi:
        raise ValueError("DOI is invalid")
    if not doi and not title:
        raise ValueError("a DOI or title is required")
    disposition = visible_text(data.get("disposition")).casefold()
    dispositions = {"include": "INCLUDE_FOR_FULL_TEXT", "exclude": "EXCLUDE"}
    if disposition not in dispositions:
        raise ValueError("unknown disposition")
    pool_relative = Path("00_discovery/candidate_pool.json")
    decisions_relative = Path("00_discovery/screening_decisions.json")
    validate_project_path_components(project, (pool_relative, decisions_relative))
    pool_path = project / pool_relative
    decisions_path = project / decisions_relative
    pool_payload = read_json_if_exists(pool_path) or {"candidates": []}
    decisions_payload = read_json_if_exists(decisions_path) or {"decisions": []}
    if not isinstance(pool_payload, dict) or not isinstance(decisions_payload, dict):
        raise ValueError("source candidates are unavailable")
    candidates = pool_payload.get("candidates", [])
    decisions = decisions_payload.get("decisions", [])
    if not isinstance(candidates, list) or not all(isinstance(row, dict) for row in candidates):
        raise ValueError("source candidates are unavailable")
    if not isinstance(decisions, list) or not all(isinstance(row, dict) for row in decisions):
        raise ValueError("screening decisions are unavailable")
    identity = doi or title.casefold()
    if any(
        normalize_doi(row.get("doi")) == doi if doi else visible_text(row.get("title")).casefold() == identity
        for row in [*candidates, *decisions]
    ):
        raise ValueError("source supplement already exists")
    candidate_id = "RESEARCHER-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12].upper()
    candidates.append(
        {
            "candidate_id": candidate_id,
            "doi": doi,
            "title": title,
            "source_origin": "RESEARCHER_SUPPLIED",
        }
    )
    decisions.append(
        {
            "candidate_id": candidate_id,
            "doi": doi,
            "title": title,
            "system_recommendation": "RESEARCHER_SUPPLIED",
            "disposition": dispositions[disposition],
        }
    )
    pool_payload["candidates"] = candidates
    decisions_payload["decisions"] = decisions
    _replace_json_pair(
        [(pool_path, pool_payload), (decisions_path, decisions_payload)]
    )
    return {
        "status": "received",
        "message": "已加入来源候选",
        "study_id": candidate_id,
    }


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
    if not all(isinstance(row, dict) for row in downloads) or not all(
        isinstance(row, dict) for row in results
    ):
        raise ValueError("project source list is unavailable")
    download_ids = [_canonical_source_identifier(row.get("download_id")) for row in downloads]
    result_ids = [_canonical_source_identifier(row.get("download_id")) for row in results]
    study_ids = [_canonical_source_identifier(row.get("study_id")) for row in downloads]
    if (
        any(not download_id for download_id in download_ids)
        or len(download_ids) != len(set(download_ids))
        or any(not download_id for download_id in result_ids)
        or len(result_ids) != len(set(result_ids))
    ):
        raise ValueError("project source list is unavailable")
    declared_download_ids = set(download_ids)
    if not set(result_ids).issubset(declared_download_ids):
        raise ValueError("project source list is unavailable")
    result_by_id = dict(zip(result_ids, results, strict=True))
    sources: list[dict[str, Any]] = []
    for index, (row, download_id, study_id) in enumerate(
        zip(downloads, download_ids, study_ids, strict=True)
    ):
        result = result_by_id.get(download_id, {})
        ready = visible_text(result.get("status")).upper() in SOURCE_ARCHIVE_SUCCESS_STATUSES
        role = visible_text(row.get("document_role")).upper() or "FULL TEXT"
        doi = normalize_doi(row.get("doi")) or ""
        citation = doi or study_id or f"研究 {index + 1}"
        landing_url = _safe_research_source_url(row.get("landing_page_url"))
        source_url = _safe_research_source_url(row.get("source_url") or row.get("url"))
        sources.append(
            {
                "download_id": download_id,
                "study_id": study_id or doi,
                "citation": citation,
                "role": role,
                "status": "已获得" if ready else "需要上传",
                "download_url": landing_url or source_url,
                "message": "全文已就绪" if ready else f"请补充 {role} 文件",
            }
        )
    ready_count = sum(row["status"] == "已获得" for row in sources)
    screening_path = project / "00_discovery/screening_decisions.json"
    screening = read_json_if_exists(screening_path) or {}
    if os.path.lexists(screening_path) and not isinstance(screening, dict):
        raise ValueError("project source list is unavailable")
    decisions = screening.get("decisions") if isinstance(screening, dict) else []
    if decisions is not None and (
        not isinstance(decisions, list) or not all(isinstance(row, dict) for row in decisions)
    ):
        raise ValueError("project source list is unavailable")
    decision_ids = [_canonical_source_identifier(row.get("candidate_id")) for row in decisions or []]
    if any(not candidate_id for candidate_id in decision_ids) or len(decision_ids) != len(
        set(decision_ids)
    ):
        raise ValueError("project source list is unavailable")
    supplements = [
        {
            "study_id": candidate_id,
            "citation": visible_text(row.get("title")) or normalize_doi(row.get("doi")) or "用户补充研究",
            "doi": normalize_doi(row.get("doi")) or "",
            "system_recommendation": _system_recommendation_label(row.get("system_recommendation")),
            "researcher_disposition": _researcher_disposition_label(row.get("disposition")),
        }
        for row, candidate_id in zip(decisions or [], decision_ids, strict=True)
        if isinstance(row, dict) and visible_text(row.get("system_recommendation")).upper() == "RESEARCHER_SUPPLIED"
    ]
    manual_receipt = read_json_if_exists(project / "00_sources/manual_import_receipt.json") or {}
    raw_unresolved = manual_receipt.get("unresolved") if isinstance(manual_receipt, dict) else []
    if raw_unresolved is not None and not isinstance(raw_unresolved, list):
        raise ValueError("project source mapping is unavailable")
    unresolved: list[dict[str, Any]] = []
    seen_member_ids: set[str] = set()
    for row in raw_unresolved or []:
        if not isinstance(row, dict):
            raise ValueError("project source mapping is unavailable")
        member_id = visible_text(row.get("member_id"))
        display_name = visible_text(row.get("member_display_name"))
        reason = visible_text(row.get("reason"))
        download_ids = row.get("download_ids")
        if (
            not re.fullmatch(r"MEMBER-\d{4}", member_id)
            or member_id in seen_member_ids
            or not display_name
            or len(display_name) > 255
            or display_name in {".", ".."}
            or "/" in display_name
            or "\\" in display_name
            or any(ord(character) < 32 for character in display_name)
            or not reason
            or len(reason) > 100
            or not isinstance(download_ids, list)
        ):
            raise ValueError("project source mapping is unavailable")
        seen_member_ids.add(member_id)
        safe_download_ids = [_canonical_source_identifier(download_id) for download_id in download_ids]
        if (
            any(not download_id for download_id in safe_download_ids)
            or len(safe_download_ids) != len(set(safe_download_ids))
            or not set(safe_download_ids).issubset(declared_download_ids)
        ):
            raise ValueError("project source mapping is unavailable")
        safe_download_ids.sort()
        unresolved.append(
            {
                "reason": reason,
                "member_id": member_id,
                "member_display_name": display_name,
                "download_ids": safe_download_ids,
            }
        )
    return {
        "project_id": project_id,
        "counts": {
            "total": len(sources),
            "ready": ready_count,
            "missing": len(sources) - ready_count,
        },
        "upload_required": any(row["status"] == "需要上传" for row in sources),
        "sources": sources,
        "supplements": supplements,
        "unresolved": unresolved,
    }


def _researcher_batch_blocker(reason_code: str, last_completed_stage: str) -> dict[str, str]:
    reason = visible_text(reason_code).upper()
    if reason == "RESUME_BINDING_INVALID":
        return {
            "message": "当前研究输入完整性异常，现有结果不会继续使用。",
            "action": "在 QoderWork 中创建一个新项目重新开始",
        }
    if reason.startswith(("REVIEWER_",)):
        return {
            "message": "科学复核结果不完整或与当前证据不一致，请重新运行该研究的科学复核。",
            "action": "在 QoderWork 中重新运行该研究的科学复核",
        }
    if reason.startswith(("R0_",)):
        return {
            "message": "证据定位或原文支撑未通过校验，请核对该研究的全文解析与证据选择后重新处理。",
            "action": "核对该研究的全文解析与证据选择后重新处理",
        }
    if reason.startswith(
        (
            "EVIDENCE_CARDS_",
            "EXCEPTION_QUEUE_",
            "PROJECT_SNAPSHOT_",
            "PROJECT_STATE_",
            "PROJECTION_",
            "REGISTRATION_",
        )
    ):
        return {
            "message": "研究证据尚未安全写入项目，请恢复项目处理状态后重试该研究。",
            "action": "在 QoderWork 中恢复项目处理状态后重试该研究",
        }
    if reason.startswith(("SEMANTIC_", "JOB_BINDING_", "BLOCKED_CLAIM_")):
        return {
            "message": "证据提取结果未通过完整性校验，请重新运行该研究的证据提取。",
            "action": "在 QoderWork 中重新运行该研究的证据提取",
        }
    if reason.startswith(
        (
            "ACQUISITION_",
            "ATOM_",
            "CATALOG_",
            "MINERU_",
            "PREPARE_",
            "REUSABLE_",
            "SOURCE_",
            "STUDY_",
        )
    ):
        return {
            "message": "研究来源或解析材料尚未就绪，请补齐该研究所需全文并完成解析后再继续。",
            "action": "补齐该研究所需全文并完成解析后继续证据处理",
        }
    return {
        "message": "该研究未通过当前科学处理阶段，请在 QoderWork 中重新处理后继续。",
        "action": "在 QoderWork 中重新处理该研究",
    }


_PARSE_OBJECT_LABELS = {
    "body_order": "正文阅读顺序",
    "section_boundaries": "章节边界",
    "figure_caption_links": "图与图注对应",
    "table_structure": "表格结构",
    "formula_chemistry": "公式与化学符号",
    "reference_boundary": "参考文献边界",
    "supplement_completeness": "补充信息完整性",
}


def _parse_decision_token(
    project_id: str,
    study_id: str,
    object_id: str,
    gate_digest: str,
    object_digest: str,
    decision_revision: str,
) -> str:
    material = "\0".join(
        (project_id, study_id, object_id, gate_digest, object_digest, decision_revision)
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _parse_object_actions(status: str) -> list[str]:
    if status == "usable_with_review":
        return sorted(HUMAN_ACTIONS)
    if status in {"incomplete", "failed"}:
        return ["pdf_locator_only", "reparse_required"]
    return []


def project_parse_quality_payload(review_root: Path, project_id: str) -> dict[str, Any]:
    project = project_dir(review_root, project_id)
    state = project_parse_quality_state(project)
    studies: list[dict[str, Any]] = []
    object_count = 0
    needs_review = 0
    approved = 0
    pdf_locator_only = 0
    reparse_required = 0
    for gate in state.get("studies", []):
        if not isinstance(gate, dict):
            continue
        study_id = visible_text(gate.get("study_id"))
        gate_digest = visible_text(gate.get("gate_digest"))
        if not study_id or not gate_digest:
            continue
        bundle = load_source_truth_bundle(project, study_id)
        identity = bundle.get("study_identity")
        identity = identity if isinstance(identity, dict) else {}
        label = visible_text(identity.get("title")) or visible_text(identity.get("doi")) or study_id
        sources = bundle.get("sources") if isinstance(bundle.get("sources"), list) else []
        primary = next(
            (row for row in sources if isinstance(row, dict) and row.get("document_role") == "MAIN"),
            next((row for row in sources if isinstance(row, dict)), None),
        )
        if not isinstance(primary, dict) or not visible_text(primary.get("source_id")):
            raise SourceTruthError("SOURCE_ID_NOT_FOUND")
        source_id = visible_text(primary["source_id"])
        page_count = primary.get("page_count")
        if not isinstance(page_count, int) or isinstance(page_count, bool) or page_count < 1:
            raise SourceTruthError("SOURCE_PAGE_COUNT_INVALID")
        base_href = (
            f"/api/project/{quote(project_id, safe='')}/source/"
            f"{quote(source_id, safe='')}"
        )
        objects: list[dict[str, Any]] = []
        for row in gate.get("objects", []):
            if not isinstance(row, dict):
                continue
            object_id = visible_text(row.get("object_id"))
            object_digest = visible_text(row.get("object_digest"))
            kind = visible_text(row.get("kind"))
            automatic_status = visible_text(row.get("status"))
            actions = _parse_object_actions(automatic_status)
            raw_decision = row.get("decision")
            decision = None
            if isinstance(raw_decision, dict):
                action = visible_text(raw_decision.get("action"))
                note = visible_text(raw_decision.get("note"))
                decision = {"action": action, "note": note}
                approved += action == "approve_candidate_extraction"
                pdf_locator_only += action == "pdf_locator_only"
                reparse_required += action == "reparse_required"
            elif actions:
                needs_review += 1
            issues = [
                {
                    "severity": visible_text(issue.get("severity")),
                    "message": visible_text(issue.get("message")),
                    "page": issue.get("page") if isinstance(issue.get("page"), int) else None,
                }
                for issue in row.get("issues", [])
                if isinstance(issue, dict) and visible_text(issue.get("message"))
            ]
            objects.append(
                {
                    "object_id": object_id,
                    "kind": kind,
                    "label": _PARSE_OBJECT_LABELS.get(kind, "解析对象"),
                    "automatic_status": automatic_status,
                    "issues": issues,
                    "decision": decision,
                    "actions": actions,
                    "note_required": bool(actions),
                    "decision_token": _parse_decision_token(
                        project_id,
                        study_id,
                        object_id,
                        gate_digest,
                        object_digest,
                        parse_decision_revision(raw_decision),
                    ),
                }
            )
        object_count += len(objects)
        studies.append(
            {
                "study_id": study_id,
                "label": label,
                "pdf_href": f"{base_href}/pdf",
                "pdf_page_href": f"{base_href}/pdf-page",
                "pdf_page_count": page_count,
                "markdown_href": f"{base_href}/parsed-markdown",
                "objects": objects,
            }
        )
    status = visible_text(state.get("status")) or "needs_review"
    return {
        "project_id": project_id,
        "status": status,
        "workflow_can_continue": bool(state.get("workflow_can_continue")),
        "summary": {
            "studies": len(studies),
            "objects": object_count,
            "needs_review": needs_review,
            "approved": approved,
            "pdf_locator_only": pdf_locator_only,
            "reparse_required": reparse_required,
        },
        "studies": studies,
    }


def write_project_parse_quality_decision(
    review_root: Path,
    project_id: str,
    data: Any,
) -> dict[str, Any]:
    if not isinstance(data, dict) or set(data) != {
        "study_id",
        "object_id",
        "decision_token",
        "action",
        "note",
    }:
        raise ParseQualityError("DECISION_INVALID")
    study_id = visible_text(data.get("study_id"))
    object_id = visible_text(data.get("object_id"))
    decision_token = visible_text(data.get("decision_token"))
    action = visible_text(data.get("action"))
    note = visible_text(data.get("note"))
    if not all(isinstance(data.get(key), str) for key in data) or not all(
        (study_id, object_id, decision_token, action, note)
    ):
        raise ParseQualityError("DECISION_INVALID")
    project = project_dir(review_root, project_id)
    gate = parse_quality_state(project, study_id)
    gate_digest = visible_text(gate.get("gate_digest"))
    objects = [
        row
        for row in gate.get("objects", [])
        if isinstance(row, dict) and row.get("object_id") == object_id
    ]
    if len(objects) != 1:
        raise ParseQualityError("PARSE_OBJECT_NOT_FOUND")
    object_digest = visible_text(objects[0].get("object_digest"))
    decision_revision = parse_decision_revision(objects[0].get("decision"))
    expected = _parse_decision_token(
        project_id,
        study_id,
        object_id,
        gate_digest,
        object_digest,
        decision_revision,
    )
    if decision_token != expected:
        raise ParseQualityError("PARSE_QUALITY_STALE")
    apply_parse_quality_decision(
        project,
        study_id,
        {
            "object_id": object_id,
            "gate_digest": gate_digest,
            "object_digest": object_digest,
            "decision_revision": decision_revision,
            "action": action,
            "note": note,
            "actor_type": "simulated_researcher_agent",
            "actor_label": "dashboard-playwright-reviewer",
        },
    )
    return project_parse_quality_payload(review_root, project_id)


def project_parse_source_asset(project: Path, source_id: str, kind: str) -> Path:
    if not source_id or kind not in {"pdf", "parsed-markdown"}:
        raise SourceTruthError("SOURCE_ASSET_KIND_INVALID")
    root = project / SOURCE_TRUTH_ROOT
    matches: list[str] = []
    if root.is_dir() and not root.is_symlink():
        for study_dir in sorted(root.iterdir()):
            if not study_dir.is_dir() or study_dir.is_symlink():
                continue
            bundle = load_source_truth_bundle(project, study_dir.name)
            if any(
                isinstance(row, dict) and row.get("source_id") == source_id
                for row in bundle.get("sources", [])
            ):
                matches.append(study_dir.name)
    if len(matches) != 1:
        raise SourceTruthError("SOURCE_ID_NOT_FOUND")
    return source_truth_asset(project, matches[0], source_id, kind)


def project_parse_source_page_count(project: Path, source_id: str) -> int:
    root = project / SOURCE_TRUTH_ROOT
    matches: list[int] = []
    if root.is_dir() and not root.is_symlink():
        for study_dir in sorted(root.iterdir()):
            if not study_dir.is_dir() or study_dir.is_symlink():
                continue
            bundle = load_source_truth_bundle(project, study_dir.name)
            for row in bundle.get("sources", []):
                if isinstance(row, dict) and row.get("source_id") == source_id:
                    page_count = row.get("page_count")
                    if not isinstance(page_count, int) or isinstance(page_count, bool) or page_count < 1:
                        raise SourceTruthError("SOURCE_PAGE_COUNT_INVALID")
                    matches.append(page_count)
    if len(matches) != 1:
        raise SourceTruthError("SOURCE_ID_NOT_FOUND")
    return matches[0]


def render_pdf_page(path: Path, page: int) -> bytes:
    if page < 1:
        raise ValueError("PDF page is invalid")
    executable = shutil.which("pdftoppm")
    if executable is None:
        raise RuntimeError("pdftoppm is unavailable")
    if not PDF_RENDER_SEMAPHORE.acquire(timeout=5):
        raise RuntimeError("PDF renderer is busy")
    try:
        with tempfile.TemporaryDirectory(prefix="review-writer-pdf-page-") as temp_dir:
            output = Path(temp_dir) / "page"
            completed = subprocess.run(
                [
                    executable,
                    "-f",
                    str(page),
                    "-l",
                    str(page),
                    "-singlefile",
                    "-png",
                    "-scale-to",
                    "1600",
                    str(path),
                    str(output),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=False,
            )
            rendered = output.with_suffix(".png")
            if completed.returncode != 0 or not rendered.is_file():
                raise ValueError("PDF page could not be rendered")
            size = rendered.stat().st_size
            if size < 8 or size > 25 * 1024 * 1024:
                raise ValueError("PDF page renderer returned invalid output")
            payload = rendered.read_bytes()
    finally:
        PDF_RENDER_SEMAPHORE.release()
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("PDF page renderer returned invalid output")
    return payload


def _workspace_token(kind: str, identifier: str, value: object) -> str:
    """Opaque optimistic-concurrency token; never expose the bound digest itself."""
    material = json.dumps({"kind": kind, "id": identifier, "value": value}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(hashlib.sha256(material).digest()).decode("ascii").rstrip("=")


def _safe_decision(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    action = value.get("action")
    reason = value.get("reason")
    if not isinstance(action, str):
        return None
    result = {"action": action}
    if isinstance(reason, str):
        result["reason"] = reason
    if isinstance(value.get("decided_at"), str):
        result["decided_at"] = value["decided_at"]
    return result


def _safe_evidence_row(project_id: str, row: dict[str, Any]) -> dict[str, Any]:
    locator = row.get("locator") if isinstance(row.get("locator"), dict) else {}
    safe_locator = {
        key: locator.get(key)
        for key in ("source_mode", "page", "section_or_item", "figure_or_table", "exact_quote")
        if locator.get(key) is not None
    }
    result = {
        "evidence_id": row.get("evidence_id"),
        "study_id": row.get("study_id"),
        "source_id": row.get("source_id"),
        "epistemic_type": row.get("epistemic_type"),
        "statement": row.get("statement"),
        "locator": safe_locator,
        "reported_conditions": row.get("reported_conditions", []),
        "quantitative_results": row.get("quantitative_results", []),
        "limitations": row.get("limitations", []),
        "mechanism_grade": row.get("mechanism_grade"),
        "risk_classes": row.get("risk_classes", []),
        "status": row.get("status", "needs_review"),
        "reason_code": row.get("reason_code"),
        "decision": _safe_decision(row.get("decision")),
    }
    evidence_id = str(result["evidence_id"])
    result["version_token"] = _workspace_token("paper-evidence", evidence_id, row.get("candidate_digest"))
    result["pdf_page_url"] = f"/api/project/{quote(project_id, safe='')}/source/{quote(str(row.get('source_id')), safe='')}/pdf-page?page={int(locator.get('page') or 1)}"
    result["parsed_text_url"] = f"/api/project/{quote(project_id, safe='')}/source/{quote(str(row.get('source_id')), safe='')}/parsed-markdown"
    return result


def project_paper_evidence_payload(review_root: Path, project_id: str) -> dict[str, Any]:
    project = project_dir(review_root, project_id)
    workflow = workflow_state(project)
    if workflow.get("route") != "evidence-to-release.v1":
        return {"route": workflow.get("route", "legacy"), "status": "legacy", "items": [], "workflow_can_continue": False}
    state = paper_evidence_state(project)
    items = [_safe_evidence_row(project_id, row) for row in state.get("rows", []) if isinstance(row, dict)]
    return {
        "route": "evidence-to-release.v1",
        "status": state.get("status", "needs_review"),
        "reason": state.get("reason_code"),
        "workflow_can_continue": bool(state.get("workflow_can_continue")),
        "summary": {key: state.get(key, 0) for key in ("study_count", "total_count", "approved_count", "needs_review_count", "stale_count", "rejected_count")},
        "items": items,
    }


def project_comparison_protocol_payload(review_root: Path, project_id: str) -> dict[str, Any]:
    project = project_dir(review_root, project_id); workflow = workflow_state(project)
    if workflow.get("route") != "evidence-to-release.v1":
        return {"route": workflow.get("route", "legacy"), "status": "legacy", "available": False}
    state = comparison_protocol_state(project); value = state.get("value") if isinstance(state.get("value"), dict) else {}
    visible = {key: value.get(key) for key in ("comparison_id", "comparison_objects", "axes", "normalization_rules", "missing_value_policy", "incomparability_rules", "counterevidence_rules", "claim_strength") if key in value}
    visible["decision"] = _safe_decision(value.get("decision"))
    visible["version_token"] = _workspace_token("comparison-protocol", str(value.get("comparison_id") or "protocol"), value.get("protocol_digest"))
    return {"route": "evidence-to-release.v1", "status": state.get("status", "needs_review"), "reason": state.get("reason_code"), "workflow_can_continue": bool(state.get("workflow_can_continue")), "evidence_ready": bool(workflow.get("paper_evidence_ready")), "protocol": visible}


def project_synthesis_payload(review_root: Path, project_id: str) -> dict[str, Any]:
    project = project_dir(review_root, project_id); workflow = workflow_state(project)
    if workflow.get("route") != "evidence-to-release.v1":
        return {"route": workflow.get("route", "legacy"), "status": "legacy", "items": []}
    state = synthesis_state(project); coverage = coverage_map_state(project); items = []
    for row in state.get("rows", []):
        if not isinstance(row, dict): continue
        item = {key: row.get(key) for key in ("synthesis_id", "proposition", "comparison_axis", "supporting_evidence_ids", "counter_evidence_ids", "applicability_boundary", "mechanism_evidence_grade", "uncertainty", "risk_class", "single_study", "status", "reason_code")}
        item["decision"] = _safe_decision(row.get("decision")); item["version_token"] = _workspace_token("synthesis", str(row.get("synthesis_id")), row.get("synthesis_digest")); items.append(item)
    coverage_value = coverage.get("value") if isinstance(coverage.get("value"), dict) else {}
    safe_coverage = {key: coverage_value.get(key) for key in ("comparison_id", "corpus_kind", "axes", "known_omissions") if key in coverage_value}
    safe_coverage.update({"status": coverage.get("status"), "reason": coverage.get("reason_code")})
    return {"route": "evidence-to-release.v1", "status": state.get("status", "needs_review"), "reason": state.get("reason_code"), "workflow_can_continue": bool(state.get("workflow_can_continue")), "protocol_ready": bool(comparison_protocol_state(project).get("workflow_can_continue")), "items": items, "coverage": safe_coverage}


def project_section_contracts_payload(review_root: Path, project_id: str) -> dict[str, Any]:
    project = project_dir(review_root, project_id); workflow = workflow_state(project)
    if workflow.get("route") != "evidence-to-release.v1":
        return {"route": workflow.get("route", "legacy"), "status": "legacy", "items": []}
    state = section_contract_state(project); items = []
    for row in state.get("rows", []):
        if not isinstance(row, dict): continue
        item = {key: row.get(key) for key in ("section_id", "research_question", "comparison_axes", "expected_synthesis", "counterevidence_and_limitations", "evidence_budget", "synthesis_budget", "figure_plan", "allowed_wording_strength", "status", "reason_code")}
        item["decision"] = _safe_decision(row.get("decision")); item["version_token"] = _workspace_token("section-contract", str(row.get("section_id")), row.get("contract_digest")); items.append(item)
    return {"route": "evidence-to-release.v1", "status": state.get("status", "needs_review"), "reason": state.get("reason_code"), "workflow_can_continue": bool(state.get("workflow_can_continue")), "synthesis_ready": bool(synthesis_state(project).get("workflow_can_continue")), "items": items}


def project_review_figures_workspace_payload(review_root: Path, project_id: str) -> dict[str, Any]:
    project = project_dir(review_root, project_id); workflow = workflow_state(project)
    if workflow.get("route") != "evidence-to-release.v1":
        return {"route": workflow.get("route", "legacy"), "status": "legacy", "source_figures": [], "placeholders": []}
    registry_path = project / "03_figures/source_figure_registry.json"
    registry = read_json_if_exists(registry_path)
    if not isinstance(registry, dict):
        registry = build_source_figure_registry(project)
    source_figures = []
    for row in registry.get("figures", []):
        if not isinstance(row, dict): continue
        item = {key: row.get(key) for key in ("figure_id", "study_id", "source_id", "page", "figure_label", "caption", "evidence_ids", "selection_status")}
        item["version_token"] = _workspace_token("review-figure", str(row.get("figure_id")), row.get("asset_sha256"))
        item["image_url"] = f"/api/project/{quote(project_id, safe='')}/source-figure?figure_id={quote(str(row.get('figure_id')), safe='')}"
        item["pdf_page_url"] = f"/api/project/{quote(project_id, safe='')}/source/{quote(str(row.get('source_id')), safe='')}/pdf-page?page={int(row.get('page') or 1)}"
        source_figures.append(item)
    placeholders = []
    for row in synthesis_figure_placeholders(project):
        item = {key: row.get(key) for key in ("placeholder_id", "scientific_question", "reader_takeaway", "panels", "comparison_axis", "required_labels_units", "counter_evidence", "forbidden_overclaims", "unresolved_uncertainties", "caption_draft", "target_size", "status")}
        item["version_token"] = _workspace_token("review-placeholder", str(row.get("placeholder_id")), row)
        placeholders.append(item)
    return {"route": "evidence-to-release.v1", "figure_policy": "source_figures_or_synthesis_placeholders_only", "source_figures": source_figures, "placeholders": placeholders, "summary": {"source_count": len(source_figures), "placeholder_count": len(placeholders)}}


def project_workspace_payload(review_root: Path, project_id: str, kind: str) -> dict[str, Any]:
    return {
        "paper-evidence": project_paper_evidence_payload,
        "comparison-protocol": project_comparison_protocol_payload,
        "synthesis": project_synthesis_payload,
        "section-contracts": project_section_contracts_payload,
        "review-figures": project_review_figures_workspace_payload,
    }[kind](review_root, project_id)


def _require_workspace_token(kind: str, identifier: str, value: object, payload: dict[str, Any]) -> None:
    token = payload.get("version_token", payload.get("token"))
    if not isinstance(token, str) or token != _workspace_token(kind, identifier, value):
        raise WorkspaceStaleError("WORKSPACE_STALE")


def write_project_workspace_decision(review_root: Path, project_id: str, kind: str, payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict): raise ValueError("invalid workspace payload")
    project = project_dir(review_root, project_id)
    if kind == "paper-evidence":
        state = paper_evidence_state(project); eid = payload.get("evidence_id"); row = next((r for r in state.get("rows", []) if r.get("evidence_id") == eid), None)
        if not isinstance(row, dict): raise PaperEvidenceError("EVIDENCE_ID_NOT_FOUND")
        _require_workspace_token(kind, str(eid), row.get("candidate_digest"), payload)
        internal = {"evidence_id": eid, "candidate_digest": row.get("candidate_digest"), "bound_parse_object_digests": row.get("bound_parse_object_digests", []), "source_pdf_sha256": row.get("source_pdf_sha256"), "action": payload.get("action"), "reason": payload.get("reason"), "actor_type": payload.get("actor_type", "human_researcher"), "actor_label": payload.get("actor_label", "local-researcher")}
        if "replacement_statement" in payload: internal["replacement_statement"] = payload["replacement_statement"]
        apply_paper_evidence_decision(project, internal)
        return project_paper_evidence_payload(review_root, project_id)
    if kind == "comparison-protocol":
        state = comparison_protocol_state(project); value = state.get("value") if isinstance(state.get("value"), dict) else {}; identifier = str(value.get("comparison_id") or "protocol")
        _require_workspace_token(kind, identifier, value.get("protocol_digest"), payload)
        apply_comparison_protocol_decision(project, {"action": payload.get("action"), "reason": payload.get("reason"), "actor_type": payload.get("actor_type", "human_researcher"), "actor_label": payload.get("actor_label", "local-researcher")})
        return project_comparison_protocol_payload(review_root, project_id)
    if kind == "synthesis":
        state = synthesis_state(project); sid = payload.get("synthesis_id"); row = next((r for r in state.get("rows", []) if r.get("synthesis_id") == sid), None)
        if not isinstance(row, dict): raise SynthesisError("SYNTHESIS_ID_NOT_FOUND")
        _require_workspace_token(kind, str(sid), row.get("synthesis_digest"), payload)
        apply_synthesis_decision(project, {"synthesis_id": sid, "action": payload.get("action"), "reason": payload.get("reason"), "actor_type": payload.get("actor_type", "human_researcher"), "actor_label": payload.get("actor_label", "local-researcher")})
        return project_synthesis_payload(review_root, project_id)
    if kind == "section-contracts":
        state = section_contract_state(project); sid = payload.get("section_id"); row = next((r for r in state.get("rows", []) if r.get("section_id") == sid), None)
        if not isinstance(row, dict): raise SectionContractError("SECTION_ID_NOT_FOUND")
        _require_workspace_token(kind, str(sid), row.get("contract_digest"), payload)
        apply_section_contract_decision(project, {"section_id": sid, "action": payload.get("action"), "reason": payload.get("reason"), "actor_type": payload.get("actor_type", "human_researcher"), "actor_label": payload.get("actor_label", "local-researcher")})
        return project_section_contracts_payload(review_root, project_id)
    if kind == "review-figures":
        figure_id = payload.get("figure_id")
        registry = read_json_if_exists(project / "03_figures/source_figure_registry.json")
        if not isinstance(registry, dict): raise ReviewFigureError("FIGURE_STATE_INVALID")
        rows = registry.get("figures", []); row = next((r for r in rows if isinstance(r, dict) and r.get("figure_id") == figure_id), None)
        if not isinstance(row, dict): raise ReviewFigureError("FIGURE_NOT_FOUND")
        _require_workspace_token(kind, str(figure_id), row.get("asset_sha256"), payload)
        status = payload.get("selection_status")
        if status not in {"selected", "available", "rejected"}: raise ReviewFigureError("FIGURE_SELECTION_INVALID")
        row["selection_status"] = status
        registry["registry_digest"] = canonical_digest(registry.get("figures", []))
        target = project / "03_figures/source_figure_registry.json"
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise ReviewFigureError("FIGURE_STATE_INVALID")
        fd, temporary = tempfile.mkstemp(prefix=".source_figure_registry.", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(registry, handle, ensure_ascii=False, sort_keys=True, indent=2)
                handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
        return project_review_figures_workspace_payload(review_root, project_id)
    raise ValueError("unknown workspace")


def project_progress_payload(review_root: Path, project_id: str) -> dict[str, Any]:
    project = project_dir(review_root, project_id)
    authoritative_workflow = workflow_state(project)
    new_route = authoritative_workflow.get("route") == "evidence-to-release.v1"
    source_truth_root = project / SOURCE_TRUTH_ROOT
    source_truth_managed = source_truth_root.is_dir() and any(
        path.is_file() and not path.parent.is_symlink()
        for path in source_truth_root.glob("*/bundle.json")
    )
    parse_projection = project_parse_quality_state(project) if source_truth_managed else None
    parse_reason = (
        visible_text(parse_projection.get("reason_code"))
        if isinstance(parse_projection, dict)
        else ""
    )
    parse_needs_attention = bool(
        isinstance(parse_projection, dict)
        and parse_projection.get("status") == "needs_attention"
        and parse_reason != "PARSE_QUALITY_MISSING"
    )
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
    batch_progress_path = project / "01_evidence/batch_progress.json"
    batch_progress = read_json_if_exists(batch_progress_path) or {}
    if os.path.lexists(batch_progress_path) and not isinstance(batch_progress, dict):
        raise ValueError("project processing status is unavailable")
    batch_studies = batch_progress.get("studies") if isinstance(batch_progress, dict) else []
    if batch_studies is not None and not isinstance(batch_studies, list):
        raise ValueError("project processing status is unavailable")
    batch_by_study = {
        visible_text(row.get("study_id")): row
        for row in batch_studies or []
        if isinstance(row, dict) and visible_text(row.get("study_id"))
    }
    raw_credits = batch_progress.get("credits") if isinstance(batch_progress, dict) else {}
    raw_credits = raw_credits if isinstance(raw_credits, dict) else {}
    measured = raw_credits.get("measured")
    forecast = raw_credits.get("forecast")
    measured_credits = measured.get("consumed") if isinstance(measured, dict) else None
    forecast_credits = forecast.get("estimated_credits") if isinstance(forecast, dict) else None
    if (
        isinstance(measured_credits, bool)
        or not isinstance(measured_credits, (int, float))
        or not math.isfinite(measured_credits)
        or measured_credits < 0
    ):
        measured_credits = None
    if (
        isinstance(forecast_credits, bool)
        or not isinstance(forecast_credits, (int, float))
        or not math.isfinite(forecast_credits)
        or forecast_credits < 0
    ):
        forecast_credits = None

    reuse_audit = read_json_if_exists(project / "00_sources/reusable_library_audit.json") or {}
    reuse_results = reuse_audit.get("results") if isinstance(reuse_audit, dict) else []
    reuse_by_study = {
        visible_text(row.get("study_id")): visible_text(row.get("status")).upper()
        for row in reuse_results or []
        if isinstance(row, dict) and visible_text(row.get("study_id"))
    }
    coverage = read_json_if_exists(project / "00_sources/source_coverage.json") or {}
    coverage_rows = coverage.get("studies") if isinstance(coverage, dict) else []
    if isinstance(coverage, dict) and visible_text(coverage.get("study_id")):
        coverage_rows = [coverage]
    coverage_by_study = {
        visible_text(row.get("study_id")): row
        for row in coverage_rows or []
        if isinstance(row, dict) and visible_text(row.get("study_id"))
    }
    manual_receipt = read_json_if_exists(project / "00_sources/manual_import_receipt.json") or {}
    unresolved = manual_receipt.get("unresolved") if isinstance(manual_receipt, dict) else []
    unresolved_download_ids = {
        visible_text(download_id)
        for row in unresolved or []
        if isinstance(row, dict) and isinstance(row.get("download_ids"), list)
        for download_id in row["download_ids"]
        if visible_text(download_id)
    }

    source_total = int(source_payload["counts"]["total"])
    source_ready = int(source_payload["counts"]["ready"])
    main_sources = [row for row in source_payload["sources"] if visible_text(row.get("role")).upper() == "MAIN"]
    sources_complete = bool(main_sources) and all(row.get("status") == "已获得" for row in main_sources)
    parsing_complete = sources_complete and len(completed_parse) >= source_ready
    if source_truth_managed:
        sources_complete = True
        parsing_complete = bool(parse_projection and parse_projection.get("workflow_can_continue"))
    if new_route:
        # The evidence-to-release route has its own hash-bound registry. Legacy
        # evidence_cards.jsonl is intentionally not an authority for this path.
        evidence_complete = bool(authoritative_workflow.get("paper_evidence_ready"))
    else:
        evidence_complete = bool(included_ids) and included_ids.issubset(reviewed_ids)
    risk_packet_present = os.path.lexists(project / "03_review/risk_packet.json")
    risk_complete = evidence_complete and risk_packet_present and open_risks == 0
    draft_complete = project_regular_file_exists(project, Path("04_first_draft/first_draft.md"))
    final_complete = project_regular_file_exists(project, Path("05_final_audit/final_draft.docx"))

    archive_received = project_regular_file_exists(project, SOURCE_ARCHIVE_RELATIVE)
    if (
        new_route
        and evidence_complete
        and (
            not authoritative_workflow.get("synthesis_ready")
            or not authoritative_workflow.get("section_contracts_ready")
        )
    ):
        active_stage = "synthesis"
    elif (
        new_route
        and authoritative_workflow.get("synthesis_ready")
        and authoritative_workflow.get("section_contracts_ready")
        and not authoritative_workflow.get("manuscript_ready")
    ):
        active_stage = "drafting"
    elif not sources_complete:
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

    stage_definitions = [
        ("sources", "整理文献来源", sources_complete),
        ("parsing", "解析全文与补充信息", parsing_complete),
        ("evidence", "提取并核对逐研究证据", evidence_complete),
    ]
    if new_route:
        stage_definitions.append(
            ("synthesis", "完成比较协议与综合判断", bool(authoritative_workflow.get("synthesis_ready")))
        )
    else:
        stage_definitions.append(("risk", "汇总科学风险", risk_complete))
    stage_definitions.extend(
        [
            ("drafting", "撰写证据约束正文", draft_complete),
            ("final", "完成终稿与 DOCX", final_complete),
        ]
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
    legacy_manifest_present = any(
        os.path.lexists(project / relative)
        for relative in (
            "00_sources/acquisition_manifest.json",
            "00_sources/acquisition_manifest_v2.json",
        )
    )
    downstream_present = any(
        os.path.lexists(project / relative)
        for relative in (
            "01_evidence/evidence_cards.jsonl",
            "03_review/risk_packet.json",
            "04_first_draft/first_draft.md",
        )
    ) and bool(cards or risk_targets or draft_complete)
    pipeline_state_inconsistent = source_total == 0 and (
        legacy_manifest_present or downstream_present
    )
    batch_recoveries = [
        _researcher_batch_blocker(
            visible_text(row.get("reason_code")),
            visible_text(row.get("last_completed_stage")),
        )
        for row in batch_studies or []
        if isinstance(row, dict) and visible_text(row.get("stage")).upper() == "BLOCKED"
    ]
    batch_recovery = batch_recoveries[0] if batch_recoveries else None
    blocker = (
        "解析质量记录不可读取，请重新生成后再核对原始 PDF。"
        if parse_needs_attention
        else "上传的压缩包未通过来源核验，请按缺失清单修正后重新上传。"
        if source_invalid
        else "项目来源清单与后续证据状态不一致，请在 QoderWork 中恢复后继续。"
        if pipeline_state_inconsistent
        else batch_recovery["message"]
        if batch_recovery
        else "当前阶段需要补充信息，请查看推荐操作。"
        if raw_blockers
        else ""
    )
    stages = []
    for index, (stage_id, label, complete) in enumerate(stage_definitions):
        status = (
            "complete"
            if index < active_index or (index == active_index and complete)
            else "active"
            if index == active_index
            else "pending"
        )
        if status == "active" and blocker:
            status = "blocked"
        stages.append({"id": stage_id, "label": label, "status": status})

    source_rows: dict[str, dict[str, Any]] = {}
    manifest_downloads = (
        (read_json_if_exists(project / "00_discovery/acquisition_manifest.json") or {}).get("downloads")
        or []
    )
    for row_index, row in enumerate(source_payload["sources"]):
        study_id = visible_text(row.get("study_id"))
        if not study_id:
            continue
        summary = source_rows.setdefault(
            study_id,
            {
                "study_id": study_id,
                "label": visible_text(row.get("citation")) or study_id,
                "missing": False,
                "roles": {},
                "download_ids": set(),
            },
        )
        summary["missing"] = summary["missing"] or row.get("status") != "已获得"
        role = visible_text(row.get("role")).upper()
        if role:
            summary["roles"][role] = visible_text(row.get("status")) or "需要上传"
        if row_index < len(manifest_downloads) and isinstance(manifest_downloads[row_index], dict):
            download_id = visible_text(manifest_downloads[row_index].get("download_id"))
            if download_id:
                summary["download_ids"].add(download_id)
    studies = []
    for study_id in sorted(set(source_rows) | set(batch_by_study)):
        has_source = study_id in source_rows
        summary = source_rows.get(
            study_id,
            {
                "study_id": study_id,
                "label": f"研究 {study_id}",
                "missing": False,
                "roles": {},
                "download_ids": set(),
            },
        )
        batch = batch_by_study.get(study_id, {})
        stage = visible_text(batch.get("stage")).upper()
        reason = visible_text(batch.get("reason_code")).upper()
        main_missing = has_source and summary["roles"].get("MAIN") != "已获得"
        if main_missing:
            status = "需要补充"
        elif stage == "REGISTERED" or study_id in reviewed_ids:
            status = "已完成"
        elif stage == "WAITING_FOR_PROVIDER" and reason == "SEMANTIC_OUTPUT_MISSING":
            status = "等待证据提取"
        elif stage == "WAITING_FOR_PROVIDER" and reason == "REVIEWER_OUTPUT_MISSING":
            status = "等待科学复核"
        elif stage == "BLOCKED":
            status = "需要处理"
        else:
            status = "正在处理"
        reuse_status = {
            "REUSABLE": "已复用全文与解析结果",
            "PDF_ONLY": "已复用全文；需要重新解析",
            "UNRESOLVED": "复用来源待确认",
            "NOT_REUSABLE": "使用本次来源",
        }.get(reuse_by_study.get(study_id), "尚未检查复用")
        coverage_row = coverage_by_study.get(study_id, {})
        si_policy = {
            "REQUIRED": "必须补充",
            "RECOMMENDED": "建议补充",
            "NOT_REQUIRED": "不需要",
        }.get(visible_text(coverage_row.get("si_policy")).upper(), "尚未判断")
        has_unresolved = bool(summary["download_ids"] & unresolved_download_ids)
        roles = summary["roles"]
        recovery = (
            _researcher_batch_blocker(reason, visible_text(batch.get("last_completed_stage")))
            if stage == "BLOCKED"
            else None
        )
        studies.append(
            {
                "study_id": study_id,
                "label": summary["label"],
                "status": status,
                "reuse_status": reuse_status,
                "main_status": roles.get(
                    "MAIN", "需要上传" if has_source else "尚无来源记录"
                ),
                "si_status": "匹配待确认" if has_unresolved and "SI" in roles else roles.get("SI", "未要求"),
                "si_policy": si_policy,
                "match_status": (
                    "需要确认一个文件归属"
                    if has_unresolved
                    else "文件归属已确认"
                    if has_source
                    else "尚无来源记录"
                ),
                "next_action": recovery["action"] if recovery else "",
            }
        )
    studies.sort(key=lambda row: row["study_id"])

    recommended = {
        "sources": "正在核验您上传的来源" if archive_received else "上传一次 PDF ZIP",
        "parsing": "等待全文解析完成",
        "evidence": "继续处理下一篇研究证据",
        "synthesis": "核对比较协议与综合判断",
        "risk": "检查集中科学风险",
        "drafting": "开始撰写证据约束正文",
        "final": "检查正文并导出 DOCX",
    }[active_stage]
    parse_pdf_locator_only = bool(
        parse_projection
        and any(
            isinstance(row, dict)
            and any(
                isinstance(obj, dict)
                and isinstance(obj.get("decision"), dict)
                and obj["decision"].get("action") == "pdf_locator_only"
                for obj in row.get("objects", [])
            )
            for row in parse_projection.get("studies", [])
        )
    )
    if parse_needs_attention:
        recommended = "重新生成解析质量记录"
    elif source_truth_managed and active_stage == "parsing":
        recommended = (
            "生成并核对解析质量"
            if parse_reason == "PARSE_QUALITY_MISSING"
            else "核对解析质量后继续"
        )
    elif parse_pdf_locator_only and active_stage == "evidence":
        recommended = "从原始 PDF 人工定位证据"
    elif pipeline_state_inconsistent:
        recommended = "在 QoderWork 中恢复项目来源状态"
    elif batch_recovery:
        recommended = batch_recovery["action"]
    return {
        "project_id": project_id,
        "route": authoritative_workflow.get("route", "legacy"),
        "status": "needs_attention" if parse_needs_attention else "in_progress",
        "active_stage": active_stage,
        "stages": stages,
        "studies": studies,
        "blocker": blocker,
        "blocker_code": (
            "PARSING_RECORD_INVALID"
            if parse_needs_attention
            else "SOURCE_ARCHIVE_INVALID"
            if source_invalid
            else "PIPELINE_STATE_INCONSISTENT"
            if pipeline_state_inconsistent
            else "PROJECT_BLOCKED"
            if raw_blockers
            else ""
        ),
        "recommended_next": recommended,
        "archive_received": archive_received,
        "credits": {"measured": measured_credits, "forecast": forecast_credits},
        "release_capabilities": {
            "internal_draft_export_ready": bool(
                authoritative_workflow["internal_draft_export_ready"]
            ),
            "verified_release_ready": bool(
                authoritative_workflow["verified_release_ready"]
            ),
        },
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
    source_ids = {
        visible_text(ref.get("source_id"))
        for row in raw_targets
        for ref in (row.get("evidence_refs") if isinstance(row.get("evidence_refs"), list) else [])
        if isinstance(ref, dict) and visible_text(ref.get("source_id"))
    }
    source_index = build_project_source_index(project, source_ids)
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
        source_id = visible_text(source.get("source_id"))
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
                "locator": {
                    "label": " · ".join(
                        [source_label, f"第 {page} 页" if page is not None else ""]
                    ).strip(" ·"),
                    "href": _evidence_locator_href(
                        project,
                        project_id,
                        source_id,
                        page,
                        source_index,
                    ),
                },
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
    packet = read_json_if_exists(project / "03_review" / "risk_packet.json")
    packet_digest = packet.get("packet_digest") if isinstance(packet, dict) else None
    if not isinstance(packet_digest, str) or not packet_digest:
        raise ValueError("project risk review is unavailable")
    apply_risk_decisions(
        project,
        {"packet_digest": packet_digest, "decisions": task4_rows},
    )
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
    try:
        discovery_publication = _validated_discovery_publication(project)
    except ValueError:
        discovery_publication = None
    if discovery_publication is not None and discovery_publication[0].get("topic"):
        return str(discovery_publication[0]["topic"])
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
        try:
            discovery_publication = _validated_discovery_publication(project)
            discovery_invalid = False
        except ValueError:
            discovery_publication = None
            discovery_invalid = True
        discovery_state = discovery_publication[2] if discovery_publication is not None else {}
        projects.append(
            {
                "project_id": project.name,
                "topic": infer_project_topic(project),
                "has_discovery": discovery_publication is not None,
                "discovery_status": (
                    "invalid"
                    if discovery_invalid
                    else discovery_state.get("status") or "pending"
                ),
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
    try:
        lineage = json.loads(lineage_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("authoritative manuscript lineage is invalid") from exc
    if not isinstance(lineage, dict):
        raise ValueError("authoritative manuscript lineage is invalid")
    current_section = next(row for row in current_sections if row["id"] == section_id)
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
    verified_raw_body = (
        existing_pending.get("verified_body")
        if isinstance(existing_pending, dict) and isinstance(existing_pending.get("verified_body"), str)
        else current_section["body"]
    )
    verified_body = _without_draft_claim_markers(verified_raw_body)
    restored = existing_pending is not None and body == verified_body
    candidate_raw_body = (
        verified_raw_body
        if restored
        else _body_with_preserved_claim_markers(body, current_section["body"])
    )
    candidate = replace_manuscript_section_body(current_markdown, section_id, candidate_raw_body)
    candidate_sections = split_manuscript_sections(candidate)
    candidate_order = [(row["id"], row["heading"], row["level"]) for row in candidate_sections]
    if candidate_order != current_order:
        raise ValueError("section edit must preserve ordered ids and headings")
    reasons = [] if restored else _scientific_edit_reasons(
        section_id,
        verified_body,
        body,
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


def export_project_docx(
    review_root: Path,
    project_id: str,
    *,
    release_level: str | None = None,
) -> dict[str, Any]:
    project = project_dir(review_root, project_id)
    release = (
        build_project_release(project, release_level=release_level)
        if release_level is not None
        else build_project_release(project)
    )
    docx_path = Path(release["docx"])
    result = {
        "ok": True,
        "filename": docx_path.name,
        "size": docx_path.stat().st_size,
        "release_status": release["status"],
    }
    if release_level is not None:
        result["release_level"] = release.get("release_level", release_level)
    return result


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


def _project_figure_rows(project: Path) -> list[dict[str, Any]]:
    stage = project / "03_figure_redraw"
    raw_figures: list[Any] = []
    for name in ("redrawn_figure_manifest.json", "figure_manifest.json"):
        manifest = read_json_if_exists(stage / name)
        rows = manifest.get("figures") if isinstance(manifest, dict) else None
        if isinstance(rows, list):
            raw_figures.extend(rows)
    figures: list[dict[str, Any]] = []
    seen_figure_ids: set[str] = set()
    seen_markdown_paths: set[str] = set()
    state_labels = {
        "ORIGINAL_GENERATED": "原创生成图",
        "LICENSED_SOURCE": "许可来源图",
        "FIGURE_BRIEF_PLACEHOLDER": "图片说明占位符",
    }
    for index, row in enumerate(raw_figures, start=1):
        if not isinstance(row, dict):
            continue
        state = state_labels.get(
            visible_text(row.get("figure_type")) or visible_text(row.get("license"))
        )
        if state is None:
            continue
        figure_id = visible_text(row.get("figure_id"))
        markdown_path = visible_text(row.get("markdown_path"))
        if (figure_id and figure_id in seen_figure_ids) or (
            markdown_path and markdown_path in seen_markdown_paths
        ):
            continue
        if figure_id:
            seen_figure_ids.add(figure_id)
        if markdown_path:
            seen_markdown_paths.add(markdown_path)
        figures.append(row)
    return figures


def project_figure_image(project: Path, index: int) -> tuple[Path, str]:
    rows = _project_figure_rows(project)
    if index < 0 or index >= len(rows):
        raise ValueError("figure index is unavailable")
    row = rows[index]
    figure_type = visible_text(row.get("figure_type")) or visible_text(row.get("license"))
    if figure_type == "FIGURE_BRIEF_PLACEHOLDER":
        raise ValueError("figure placeholder has no image")
    markdown_path = visible_text(row.get("markdown_path"))
    if not markdown_path:
        raise ValueError("figure image is unavailable")
    try:
        image_path = _validated_image(project, markdown_path)
        binding = _image_binding(image_path, markdown_path)
    except (OSError, FigurePolicyError, ProjectReleaseError):
        raise ValueError("figure image is unavailable") from None
    content_types = {
        "BMP": "image/bmp",
        "GIF": "image/gif",
        "JPEG": "image/jpeg",
        "PNG": "image/png",
        "TIFF": "image/tiff",
        "WEBP": "image/webp",
    }
    content_type = content_types.get(binding.get("image_format"))
    if content_type is None:
        raise ValueError("figure image is unavailable")
    return image_path, content_type


def _project_figure_image_is_available(project: Path, row: dict[str, Any]) -> bool:
    """Check dashboard availability without decoding an image during polling."""
    markdown_path = visible_text(row.get("markdown_path"))
    expected_signatures = {
        ".bmp": lambda header: header.startswith(b"BM"),
        ".gif": lambda header: header.startswith((b"GIF87a", b"GIF89a")),
        ".jpeg": lambda header: header.startswith(b"\xff\xd8\xff"),
        ".jpg": lambda header: header.startswith(b"\xff\xd8\xff"),
        ".png": lambda header: header.startswith(b"\x89PNG\r\n\x1a\n"),
        ".tif": lambda header: header.startswith((b"II*\x00", b"MM\x00*")),
        ".tiff": lambda header: header.startswith((b"II*\x00", b"MM\x00*")),
        ".webp": lambda header: header.startswith(b"RIFF") and header[8:12] == b"WEBP",
    }
    signature_matches = expected_signatures.get(Path(markdown_path).suffix.casefold())
    if not markdown_path or signature_matches is None:
        return False
    try:
        image_path = _validated_image(project, markdown_path)
        size = image_path.stat().st_size
        if size <= 0 or size > 32 * 1024 * 1024:
            return False
        with image_path.open("rb") as handle:
            return bool(signature_matches(handle.read(16)))
    except (OSError, ProjectReleaseError):
        return False


def project_figures_payload(review_root: Path, project_id: str) -> dict[str, Any]:
    project = project_dir(review_root, project_id)
    rows = _project_figure_rows(project)
    figures: list[dict[str, str]] = []
    safe_figure_by_markdown_path: dict[str, dict[str, str]] = {}
    state_labels = {
        "ORIGINAL_GENERATED": "原创生成图",
        "LICENSED_SOURCE": "许可来源图",
        "FIGURE_BRIEF_PLACEHOLDER": "图片说明占位符",
    }
    for index, row in enumerate(rows):
        state = state_labels.get(
            visible_text(row.get("figure_type")) or visible_text(row.get("license"))
        )
        if state is None:
            continue
        description = visible_text(
            row.get("brief")
            if state == "图片说明占位符"
            else row.get("caption") or row.get("description")
        )
        figure = {
            "state": state,
            "title": researcher_safe_markdown(visible_text(row.get("title")) or f"图件 {index}"),
            "description": researcher_safe_markdown(description or "说明待科研团队完善。"),
        }
        if state == "许可来源图":
            figure["license"] = researcher_safe_markdown(visible_text(row.get("license")))
            figure["attribution"] = researcher_safe_markdown(visible_text(row.get("attribution")))
        if state != "图片说明占位符" and _project_figure_image_is_available(project, row):
            figure["image_url"] = f"/api/project/{quote(project_id, safe='')}/figure?index={index}"
        figures.append(figure)
        markdown_path = visible_text(row.get("markdown_path"))
        if markdown_path:
            safe_figure_by_markdown_path[markdown_path] = figure
    manuscript = read_text_if_exists(project / "04_first_draft" / "first_draft.md")
    reading_figures = []
    for match in _DASHBOARD_IMAGE_RE.finditer(manuscript):
        markdown_path = match.group("angle") or match.group("plain") or ""
        figure = safe_figure_by_markdown_path.get(markdown_path)
        reading_figures.append(
            dict(figure)
            if figure is not None
            else {
                "state": "图件状态待核对",
                "title": "图件暂不可显示",
                "description": "正文图件与图件清单尚未完成绑定。",
            }
        )
    return {
        "project_id": project_id,
        "topic": infer_project_topic(project),
        "figures": figures,
        "reading_figures": reading_figures,
        "summary": {
            "total": len(figures),
            "placeholders": sum(row["state"] == "图片说明占位符" for row in figures),
        },
    }


def is_project_release_docx(path: Path, review_root: Path) -> bool:
    candidate = path if path.is_absolute() else review_root / path
    root = review_root.resolve()
    legacy = candidate.name == "final_draft.docx" and candidate.parent.name == "05_final_audit"
    new_route = (
        candidate.name in {"self_reviewed_draft.docx", "expert_reviewed_release.docx"}
        and candidate.parent.name == "05_release"
    )
    if not legacy and not new_route:
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
    if os.path.lexists(project_path / SOURCE_TRUTH_ROOT):
        authoritative_relative = Path("04_manuscript/manuscript.md")
        metadata_relative = Path("05_release/release_snapshot.json")
        validate_project_path_components(
            project_path, (authoritative_relative, metadata_relative)
        )
        authoritative_path = validate_project_file_path(
            project_path, authoritative_relative, "MANUSCRIPT_INVALID"
        )
        metadata_path = project_path / metadata_relative
        metadata_exists = metadata_path.is_file() and not metadata_path.is_symlink()
        metadata = read_json_if_exists(metadata_path) if metadata_exists else {}
        if not isinstance(metadata, dict):
            metadata = {}
        release_level = metadata.get("release_level")
        base = {
            "SELF_REVIEWED_DRAFT": "self_reviewed_draft",
            "EXPERT_REVIEWED_RELEASE": "expert_reviewed_release",
        }.get(release_level, "self_reviewed_draft")
        snapshot_relative = Path(f"05_release/{base}.md")
        docx_relative = Path(f"05_release/{base}.docx")
        quality_relative = Path("05_release/quality_report.json")
        validate_project_path_components(
            project_path,
            (snapshot_relative, docx_relative, quality_relative),
        )
        snapshot_path = project_path / snapshot_relative
        docx_path = project_path / docx_relative
        quality_path = project_path / quality_relative
        authoritative_bytes = authoritative_path.read_bytes()
        markdown_exists = snapshot_path.is_file() and not snapshot_path.is_symlink()
        snapshot_matches = bool(
            metadata_exists
            and markdown_exists
            and snapshot_path.read_bytes() == authoritative_bytes
            and metadata.get("markdown_path") == snapshot_relative.as_posix()
            and metadata.get("docx_path") == docx_relative.as_posix()
        )
        quality_report = read_json_if_exists(quality_path)
        if not isinstance(quality_report, dict):
            quality_report = {}
        integrity_valid = bool(
            snapshot_matches
            and docx_path.is_file()
            and not docx_path.is_symlink()
            and new_route_release_docx_is_current(docx_path)
        )
        return {
            "authoritative_path": authoritative_path,
            "snapshot_path": snapshot_path,
            "docx_path": docx_path,
            "stage_path": project_path / "05_release",
            "quality_report": quality_report,
            "snapshot_exists": metadata_exists,
            "snapshot_matches": snapshot_matches,
            "integrity_valid": integrity_valid,
        }

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
        and project_figure_validation_is_current(
            project_path,
            quality_report.get("figure_validation"),
            manuscript_sha256=hashlib.sha256(authoritative_bytes).hexdigest(),
        )
    )
    return {
        "authoritative_path": authoritative_path,
        "snapshot_path": snapshot_path,
        "docx_path": docx_path,
        "stage_path": project_path / "05_final_audit",
        "quality_report": quality_report,
        "snapshot_exists": snapshot_exists,
        "snapshot_matches": snapshot_matches,
        "integrity_valid": integrity_valid,
    }


def project_release_docx_is_current(docx_path: Path) -> bool:
    candidate = Path(docx_path)
    if candidate.parent.name == "05_release":
        return new_route_release_docx_is_current(candidate)
    project = candidate.parent.parent.resolve()
    state = _project_release_artifact_state(project)
    return bool(
        state["integrity_valid"]
        and state["docx_path"].resolve() == candidate.resolve()
    )


def project_final_payload(review_root: Path, project_id: str) -> dict[str, Any]:
    project = project_dir(review_root, project_id)
    artifact_state = _project_release_artifact_state(project)
    stage = artifact_state["stage_path"]
    stage_relative = stage.relative_to(Path(review_root).resolve()).as_posix()
    docx_relative = artifact_state["docx_path"].relative_to(
        Path(review_root).resolve()
    ).as_posix()
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
                "verified_body": _without_draft_claim_markers(verified_body),
                "reasons": [reason.strip() for reason in raw_reasons],
            }
        )
    return {
        "needs_evidence_review": bool(pending),
        "pending_scientific_edits": pending,
    }


def _without_draft_claim_markers(text: str) -> str:
    return _DRAFT_CLAIM_MARKER_RE.sub("", text)


def _body_with_preserved_claim_markers(visible_body: str, current_raw_body: str) -> str:
    if visible_body == _without_draft_claim_markers(current_raw_body):
        return current_raw_body
    markers = [match.group(0) for match in _DRAFT_CLAIM_MARKER_RE.finditer(current_raw_body)]
    if not markers:
        return visible_body
    return f"{visible_body.rstrip()}\n\n{' '.join(markers)}"


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
        "sections": [
            {**section, "body": _without_draft_claim_markers(section["body"])}
            for section in (split_manuscript_sections(first_draft_md) if first_draft_md else [])
        ],
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
