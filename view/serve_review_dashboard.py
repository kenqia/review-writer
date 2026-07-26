#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import posixpath
import shutil
import sys
import tempfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urlparse


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.project.vertical_review import (  # noqa: E402
    VerticalReviewError,
    apply_risk_decisions,
    benchmark_metrics,
)
from review_writer.delivery.project_release import (  # noqa: E402
    build_project_release,
    is_reparse_component,
    refreshed_manuscript_lineage,
    replace_manuscript_section_body,
    split_manuscript_sections,
    validate_project_file_path,
    validate_project_path_components,
)


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
        if parsed.path.startswith("/api/project/") and parsed.path.endswith("/export-docx"):
            project_id = project_id_from_route(parsed.path, "export-docx")
            if project_id is None:
                self.send_error(HTTPStatus.NOT_FOUND, "project route not found")
                return
            self.handle_project_export_docx(project_id)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

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
            state = write_project_review_state(self.review_root, project_id, data)
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, f"invalid review state: {exc}")
            return
        self.send_json({"ok": True, "project_id": project_id, "current_stage": state["current_stage"]})

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
            write_project_draft_sections(self.review_root, project_id, data)
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, f"invalid draft payload: {exc}")
            return
        self.send_json({"ok": True, "project_id": project_id})

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
        requested_path = Path(posixpath.normpath(unquote(raw_path))).expanduser()
        release_candidate = requested_path if requested_path.is_absolute() else self.review_root / requested_path
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

    def send_json(self, data: object) -> None:
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(HTTPStatus.OK)
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


def scientist_locators(claims: list[dict[str, Any]]) -> list[dict[str, str]]:
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
            query: dict[str, str | int] = {}
            if source_id:
                query["paper_id"] = source_id
            if page is not None:
                query["page"] = page
            locators.append(
                {
                    "label": " · ".join(label_parts),
                    "href": f"/library?{urlencode(query)}" if query else "/library",
                }
            )
    return locators


def project_evidence_payload(review_root: Path, project_id: str) -> dict[str, Any]:
    project = project_dir(review_root, project_id)
    metrics = benchmark_metrics(project)
    cards = read_jsonl_if_exists(project / "01_evidence" / "evidence_cards.jsonl")
    visible_cards: list[dict[str, Any]] = []
    for card in cards:
        candidate = card.get("candidate") if isinstance(card.get("candidate"), dict) else {}
        study_id = visible_text(card.get("study_id")) or visible_text(candidate.get("study_id"))
        if not study_id:
            continue
        claims = candidate.get("claims") if isinstance(candidate.get("claims"), list) else []
        claim_rows = [claim for claim in claims if isinstance(claim, dict)]
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
                "locators": scientist_locators(claim_rows),
            }
        )
    visible_cards.sort(key=lambda card: card["study_id"])
    return {
        "project_id": project_id,
        "coverage": {
            "studies": metrics["registered_study_count"],
            "processable": metrics["approved_claim_count"] + metrics["human_required_claim_count"],
            "blocked": metrics["blocked_claim_count"] + metrics["exception_count"],
            "claims": metrics["projected_claim_count"],
        },
        "cards": visible_cards,
    }


def project_risk_payload(review_root: Path, project_id: str) -> dict[str, Any]:
    project = project_dir(review_root, project_id)
    benchmark_metrics(project)
    packet = read_json_if_exists(project / "03_review" / "risk_packet.json") or {}
    decision_payload = read_json_if_exists(project / "03_review" / "risk_decisions.json") or {}
    raw_targets = packet.get("targets") if isinstance(packet, dict) else []
    raw_decisions = decision_payload.get("decisions") if isinstance(decision_payload, dict) else []
    if not isinstance(raw_targets, list) or not all(isinstance(row, dict) for row in raw_targets):
        raise ValueError("project risk review is unavailable")
    if not isinstance(raw_decisions, list) or not all(isinstance(row, dict) for row in raw_decisions):
        raise ValueError("project risk review is unavailable")
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
        targets.append(
            {
                "target_id": target_id,
                "claim_text": visible_text(row.get("original_text")) or visible_text(row.get("text")),
                "risk_categories": visible_text_list(row.get("risk_categories")),
                "evidence_summary": " · ".join(summary_parts),
                "source_excerpt": visible_text(source.get("exact_quote")),
                "source_label": source_label,
                "page": page,
                "proposed_action": "Review the evidence fit and choose approve, reword, exclude, or unresolved.",
                "existing_decision": action,
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
                "has_first_draft": (review_root / "04_first_draft" / "final_draft.md").exists(),
                "has_final_audit": (review_root / "05_final_audit" / "final_draft.md").exists(),
            }
        ]
    base = review_root / "review-projects"
    projects: list[dict[str, Any]] = []
    if not base.exists():
        return projects
    for project in sorted(p for p in base.iterdir() if p.is_dir()):
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
                "has_first_draft": (project / "04_first_draft" / "first_draft.md").exists(),
                "has_final_audit": (project / "05_final_audit" / "final_draft.md").exists(),
            }
        )
    return projects


def project_summary(review_root: Path, project_id: str) -> dict[str, Any] | None:
    return next((p for p in list_review_projects(review_root) if p["project_id"] == project_id), None)


def review_state_path(review_root: Path, project_id: str) -> Path:
    return project_dir(review_root, project_id) / "00_brief" / "review_state.json"


def project_review_state_payload(review_root: Path, project_id: str) -> dict[str, Any]:
    project = project_dir(review_root, project_id)
    state = read_json_if_exists(review_state_path(review_root, project_id)) or {}
    if not isinstance(state, dict):
        state = {}
    final_stage = project / "05_final_audit"
    first_draft = project / "04_first_draft" / "first_draft.md"
    final_draft = final_stage / "final_draft.md"
    counts = state.get("counts") if isinstance(state.get("counts"), dict) else {}
    return {
        "project_id": project_id,
        "brief": state.get("brief") if isinstance(state.get("brief"), dict) else {"topic": infer_project_topic(project)},
        "current_stage": state.get("current_stage") or "not_started",
        "status": state.get("status") or "not_started",
        "blockers": state.get("blockers") if isinstance(state.get("blockers"), list) else [],
        "counts": {key: int(counts.get(key) or 0) for key in ("sources", "evidence", "claims")},
        "updated_at": state.get("updated_at"),
        "draft": {"first_draft_exists": first_draft.exists(), "final_draft_exists": final_draft.exists(), "docx_exists": (final_stage / "final_draft.docx").exists()},
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


def write_project_draft_sections(review_root: Path, project_id: str, data: Any) -> dict[str, Any]:
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
    updated_lineage = refreshed_manuscript_lineage(project, current_markdown, candidate)
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
    artifact_state = _project_release_artifact_state(project)
    authoritative_path = artifact_state["authoritative_path"]
    snapshot_path = artifact_state["snapshot_path"]
    docx_path = artifact_state["docx_path"]
    quality_report = artifact_state["quality_report"]
    snapshot_exists = artifact_state["snapshot_exists"]
    snapshot_matches = artifact_state["snapshot_matches"]
    integrity_valid = artifact_state["integrity_valid"]
    current_docx_exists = integrity_valid
    if snapshot_exists and not integrity_valid:
        release_status = "RELEASE_OUTDATED"
    elif snapshot_exists:
        release_status = quality_report.get("release_status") or quality_report.get("status") or "IN_PROGRESS"
    else:
        release_status = "IN_PROGRESS"
    return {
        "project_id": project_id,
        "topic": infer_project_topic(project),
        "summary": project_summary(review_root, project_id),
        "final_draft_md": read_text_if_exists(snapshot_path) if snapshot_exists else read_text_if_exists(authoritative_path),
        "manuscript_source": "release_snapshot" if snapshot_exists else "authoritative_manuscript",
        "release_status": release_status or "IN_PROGRESS",
        "release_snapshot": {
            "exists": snapshot_exists,
            "matches_authoritative": snapshot_matches,
            "integrity_valid": integrity_valid,
            "docx_exists": current_docx_exists,
        },
        "final_audit_report_md": read_text_if_exists(stage / "final_audit_report.md"),
        "quality_report_md": read_text_if_exists(stage / "quality_report.md"),
        "quality_report": quality_report,
        "clean_3paper_review_pack": read_text_if_exists(stage / "clean_3paper_review_pack.md"),
        "checkpoint_log": read_json_if_exists(project / "checkpoint_log.json"),
        "final_audit_report": read_json_if_exists(stage / "final_audit_report.json"),
        "release_report_md": read_text_if_exists(stage / "release_report.md"),
        "final_draft_docx_path": str(docx_path) if current_docx_exists else "",
        "final_draft_docx_exists": current_docx_exists,
        "paths": {"stage_dir": str(stage)},
    }


def project_draft_payload(review_root: Path, project_id: str) -> dict[str, Any]:
    project = project_dir(review_root, project_id)
    stage_dir = project / "04_first_draft"
    manuscript_path = validate_project_file_path(
        project, Path("04_first_draft/first_draft.md"), "MANUSCRIPT_INVALID"
    )
    manuscript_bytes = manuscript_path.read_bytes()
    first_draft_md = manuscript_bytes.decode("utf-8")
    figures_manifest = read_json_if_exists(project / "03_figure_redraw" / "redrawn_figure_manifest.json") or {}
    draft_bundle = read_json_if_exists(stage_dir / "draft_bundle.json")
    section_drafts = read_json_if_exists(project / "02_section_drafting" / "section_drafts.json")
    redrawn = []
    for row in (figures_manifest.get("figures") or []):
        if isinstance(row, dict):
            redrawn.append(row)
    return {
        "project_id": project_id,
        "topic": infer_project_topic(project),
        "summary": next((p for p in list_review_projects(review_root) if p["project_id"] == project_id), None),
        "draft_bundle": draft_bundle,
        "manuscript_version": hashlib.sha256(manuscript_bytes).hexdigest(),
        "sections": split_manuscript_sections(first_draft_md) if first_draft_md else [],
        "first_draft_md": first_draft_md,
        "merge_report_md": read_text_if_exists(stage_dir / "merge_report.md"),
        "remaining_issues_md": read_text_if_exists(stage_dir / "remaining_issues.md"),
        "section_drafts": section_drafts,
        "redrawn_figures": redrawn,
        "paths": {
            "stage_dir": str(stage_dir),
            "first_draft_base_dir": str(stage_dir),
            "first_draft": str(stage_dir / "first_draft.md"),
            "merge_report": str(stage_dir / "merge_report.md"),
            "remaining_issues": str(stage_dir / "remaining_issues.md"),
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
    if not has_dashboard_data(review_root):
        print("ERROR: no review project state or review-library metadata found.", file=sys.stderr)
        return 2
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
