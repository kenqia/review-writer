from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from review_writer.project.parse_quality import (
    parse_decision_revision,
    write_parse_quality_gate,
)
from review_writer.project.source_truth import write_source_truth_bundle
from view import serve_review_dashboard as dashboard


PROJECT_ID = "qual001-parse-quality"
STUDY_ID = "study-qual001"
SOURCE_ID = "source-qual001-main"
DOWNLOAD_ID = "qual001-main-pdf"
DOI = "10.1000/qual001-synthetic"
SLUG = "qual001-main"
GATE_RELATIVE = f"01_evidence/source_truth/{STUDY_ID}/parse_quality.json"
DERIVED_PREFIXES = (
    "01_evidence/dual_source/",
    "01_evidence/chemical_paper/",
    "01_evidence/parse_reconciliation/",
)
DERIVED_EXACT_PATHS = frozenset({".paper_evidence.lock"})


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _request_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    body = None
    headers: dict[str, str] = {}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        }
    request = Request(
        f"{base_url}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=20) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raw = exc.read()
        try:
            value: Any = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            value = raw.decode("utf-8", errors="replace")
        return exc.code, value


def _start_dashboard(
    review_root: Path,
) -> tuple[dashboard.ThreadingHTTPServer, threading.Thread, str]:
    dashboard.configure_runtime(review_root)
    server = dashboard.ThreadingHTTPServer(("127.0.0.1", 0), dashboard.DashboardHandler)
    thread = threading.Thread(
        target=server.serve_forever,
        name="qual001-dashboard",
        daemon=True,
    )
    thread.start()
    host, port = server.server_address
    return server, thread, f"http://{host}:{port}"


def _stop_dashboard(
    server: dashboard.ThreadingHTTPServer,
    thread: threading.Thread,
) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=10)
    assert not thread.is_alive(), "owned Dashboard server did not stop"


def _snapshot_tree(root: Path) -> dict[str, bytes]:
    snapshot: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            snapshot[path.relative_to(root).as_posix()] = path.read_bytes()
    return snapshot


def _changed_paths(before: dict[str, bytes], after: dict[str, bytes]) -> list[str]:
    return sorted(
        path
        for path in set(before) | set(after)
        if before.get(path) != after.get(path)
    )


def _protected_snapshot(snapshot: dict[str, bytes]) -> dict[str, bytes]:
    return {
        path: value
        for path, value in snapshot.items()
        if path != GATE_RELATIVE
        and path not in DERIVED_EXACT_PATHS
        and not any(path.startswith(prefix) for prefix in DERIVED_PREFIXES)
    }


def _build_fixture(review_root: Path) -> Path:
    project = review_root / PROJECT_ID
    project.mkdir(parents=True, exist_ok=True)

    pdf = b"%PDF-1.4\n% synthetic QUAL-001 non-sensitive source\n"
    pdf_path = project / f"00_sources/manual_upload/inbox/{SLUG}.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(pdf)
    pdf_sha256 = _sha256_bytes(pdf)

    manifest = {
        "schema_version": "public-corpus-acquisition.v1",
        "downloads": [
            {
                "download_id": DOWNLOAD_ID,
                "study_id": STUDY_ID,
                "doi": DOI,
                "document_role": "MAIN",
                "url": "https://example.org/qual001/main.pdf",
                "landing_page_url": "https://example.org/qual001",
                "target_path": f"manual_upload/inbox/{SLUG}.pdf",
                "source_class": "primary_study",
                "expected_format": "PDF",
            }
        ],
    }
    manifest_path = project / "00_discovery/acquisition_manifest.json"
    _write_json(manifest_path, manifest)
    manifest_sha256 = _sha256_bytes(manifest_path.read_bytes())
    _write_json(
        project / "00_sources/acquisition_receipt.json",
        {
            "schema_version": "public-corpus-acquisition-receipt.v1",
            "created_at": "2026-08-16T00:00:00+08:00",
            "manifest_path": manifest_path.name,
            "manifest_sha256": manifest_sha256,
            "results": [
                {
                    "download_id": DOWNLOAD_ID,
                    "save_as": f"{DOWNLOAD_ID}.pdf",
                    "study_id": STUDY_ID,
                    "doi": DOI,
                    "document_role": "MAIN",
                    "expected_format": "PDF",
                    "target_path": f"manual_upload/inbox/{SLUG}.pdf",
                    "source_url": "https://example.org/qual001/main.pdf",
                    "landing_page_url": "https://example.org/qual001",
                    "source_class": "primary_study",
                    "status": "VERIFIED_EXISTING",
                    "reason": "Synthetic fixture bytes are already present.",
                    "sha256": pdf_sha256,
                    "size_bytes": len(pdf),
                    "http_status": None,
                }
            ],
            "counts": {"VERIFIED_EXISTING": 1},
            "manual_queue_count": 0,
            "policy": {
                "public_direct_only": True,
                "network_enabled": False,
                "robots_respected": True,
                "credentials_or_sessions_used": False,
                "bounded_retries": 0,
                "max_bytes": 1024 * 1024,
            },
        },
    )
    _write_json(
        project / "00_sources/acquisition_final_receipt.json",
        {
            "schema_version": "acquisition-final-receipt.v1",
            "studies": [
                {
                    "study_id": STUDY_ID,
                    "download_id": DOWNLOAD_ID,
                    "doi": DOI,
                    "title": "Synthetic QUAL-001 source",
                    "main_pdf": {
                        "download_id": DOWNLOAD_ID,
                        "path": f"manual_upload/inbox/{SLUG}.pdf",
                        "sha256": pdf_sha256,
                        "size_bytes": len(pdf),
                    },
                }
            ],
        },
    )
    _write_json(
        project / "00_discovery/candidate_pool.json",
        {
            "candidates": [
                {
                    "candidate_id": STUDY_ID,
                    "study_id": STUDY_ID,
                    "doi": DOI,
                    "title": "Synthetic QUAL-001 source",
                    "tier": "background",
                }
            ]
        },
    )
    _write_json(
        project / "00_sources/source_coverage.json",
        {"studies": [{"study_id": STUDY_ID, "si_policy": "NOT_REQUIRED"}]},
    )
    _write_json(
        project / "00_sources/source_identity_audit.json",
        {
            "results": [
                {
                    "candidate_id": STUDY_ID,
                    "doi": DOI,
                    "title": "Synthetic QUAL-001 source",
                }
            ]
        },
    )
    _write_json(
        project / "00_brief/review_state.json",
        {"project_id": PROJECT_ID, "topic": "Synthetic parse quality product use"},
    )

    markdown = (
        "# Abstract\n\n"
        "This synthetic source exists only to exercise the parse quality route.\n\n"
        "# Results\n\n"
        "The source reports a bounded result with unresolved comparison limits.\n\n"
        "# References\n\n"
        "[1] Synthetic source record.\n"
    )
    markdown_path = project / f"01_evidence/mineru/markdown/{SLUG}.md"
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(markdown, encoding="utf-8")
    extracted = project / f"01_evidence/parses/extracted/{SLUG}"
    extracted.mkdir(parents=True, exist_ok=True)
    (extracted / "full.md").write_text(markdown, encoding="utf-8")
    content = [
        {
            "type": "text",
            "page_idx": 0,
            "bbox": [0, 0, 100, 20],
            "text": "The source reports a bounded result.",
        },
        {
            "type": "table",
            "page_idx": 0,
            "bbox": [0, 25, 100, 80],
            "table_body": "field | value",
        },
    ]
    _write_json(extracted / f"{SLUG}_content_list.json", content)
    _write_json(extracted / f"{SLUG}_content_list_v2.json", [content])
    _write_json(extracted / "layout.json", {"pages": [{"page": 1}]})
    _write_json(
        project / "01_evidence/mineru/manifest.json",
        {
            "completed": [
                {
                    "relative_pdf_path": f"manual_upload/inbox/{SLUG}.pdf",
                    "slug": SLUG,
                    "state": "done",
                }
            ]
        },
    )

    reading = b"Synthetic reading layer for QUAL-001.\n"
    layout = b"Synthetic layout layer for QUAL-001.\n"
    text_layers = project / "01_evidence/text_layers"
    text_layers.mkdir(parents=True, exist_ok=True)
    reading_path = text_layers / f"{SLUG}-reading.txt"
    layout_path = text_layers / f"{SLUG}-layout.json"
    reading_path.write_bytes(reading)
    layout_path.write_bytes(layout)
    _write_json(
        text_layers / "text_layers.manifest.json",
        {
            "sources": [
                {
                    "source_id": SOURCE_ID,
                    "pdf_sha256": pdf_sha256,
                    "page_count": 1,
                    "reading_order_path": reading_path.name,
                    "reading_order_sha256": _sha256_bytes(reading),
                    "layout_path": layout_path.name,
                    "layout_sha256": _sha256_bytes(layout),
                }
            ]
        },
    )

    write_source_truth_bundle(project, STUDY_ID)
    write_parse_quality_gate(project, STUDY_ID)
    return project


def _parse_route_row(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    studies = payload.get("studies")
    assert isinstance(studies, list) and len(studies) == 1
    study = studies[0]
    assert isinstance(study, dict)
    objects = study.get("objects")
    assert isinstance(objects, list)
    row = next(
        (
            value
            for value in objects
            if isinstance(value, dict) and value.get("kind") == "table_structure"
        ),
        None,
    )
    assert isinstance(row, dict), "synthetic table object was not projected"
    return study, row


def _decision_token(
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


def test_qual001_parse_quality_product_use_is_source_bound_and_restart_stable() -> None:
    temp_dir = os.environ.get("TMPDIR")
    with tempfile.TemporaryDirectory(
        prefix="qual001-parse-quality-",
        dir=temp_dir if temp_dir and Path(temp_dir).is_dir() else "/tmp",
    ) as temporary_root:
        review_root = Path(temporary_root)
        project = _build_fixture(review_root)
        gate_path = project / GATE_RELATIVE
        assert not (project / "05_release").exists()
        assert not (project / "state/current.json").exists()

        server: dashboard.ThreadingHTTPServer | None = None
        thread: threading.Thread | None = None
        try:
            server, thread, base_url = _start_dashboard(review_root)
            project_route = quote(PROJECT_ID, safe="")
            source_path = f"/api/project/{project_route}/sources"
            parse_path = f"/api/project/{project_route}/parse-quality"

            status, projects = _request_json(base_url, "/api/projects")
            assert status == 200
            assert any(
                isinstance(row, dict) and row.get("project_id") == PROJECT_ID
                for row in projects
            )

            status, source_payload = _request_json(base_url, source_path)
            assert status == 200
            source_rows = source_payload["sources"]
            assert len(source_rows) == 1
            assert source_rows[0]["download_id"] == DOWNLOAD_ID
            assert source_rows[0]["study_id"] == STUDY_ID

            status, initial_payload = _request_json(base_url, parse_path)
            assert status == 200
            assert initial_payload["project_id"] == PROJECT_ID
            assert initial_payload["status"] == "needs_review"
            assert initial_payload["workflow_can_continue"] is False
            initial_study, initial_object = _parse_route_row(initial_payload)
            assert initial_study["study_id"] == STUDY_ID
            assert initial_object["actions"] == [
                "approve_candidate_extraction",
                "pdf_locator_only",
                "reparse_required",
            ]
            assert "gate_digest" not in initial_payload
            assert "object_digest" not in initial_payload
            current_token = initial_object["decision_token"]
            assert re.fullmatch(r"[0-9a-f]{64}", current_token)

            gate_before = json.loads(gate_path.read_text(encoding="utf-8"))
            gate_object_before = next(
                row
                for row in gate_before["objects"]
                if row["object_id"] == initial_object["object_id"]
            )
            assert gate_before["status"] == "needs_review"
            assert gate_before["gate_digest"]
            assert gate_object_before["object_digest"]
            assert current_token == _decision_token(
                PROJECT_ID,
                STUDY_ID,
                initial_object["object_id"],
                gate_before["gate_digest"],
                gate_object_before["object_digest"],
                parse_decision_revision(gate_object_before["decision"]),
            )

            rejected_before = _snapshot_tree(project)
            decision_base = {
                "study_id": STUDY_ID,
                "object_id": initial_object["object_id"],
                "decision_token": current_token,
                "action": "approve_candidate_extraction",
            }
            status, blank_body = _request_json(
                base_url,
                parse_path,
                method="PUT",
                payload={**decision_base, "note": ""},
            )
            assert status == 400
            assert isinstance(blank_body, dict)
            assert _snapshot_tree(project) == rejected_before

            status, stale_body = _request_json(
                base_url,
                parse_path,
                method="PUT",
                payload={
                    **decision_base,
                    "decision_token": "stale-" + current_token,
                    "note": "Stale token must fail closed.",
                },
            )
            assert status == 409
            assert isinstance(stale_body, dict)
            assert _snapshot_tree(project) == rejected_before

            valid_before = _snapshot_tree(project)
            status, valid_payload = _request_json(
                base_url,
                parse_path,
                method="PUT",
                payload={
                    **decision_base,
                    "note": (
                        "Reviewed the synthetic parse object; retain AI_PROVISIONAL, "
                        "GAP, and NON_COMPARABLE risk boundaries."
                    ),
                },
            )
            assert status == 200
            valid_study, valid_object = _parse_route_row(valid_payload)
            assert valid_study["study_id"] == STUDY_ID
            assert valid_payload["workflow_can_continue"] is True
            assert valid_payload["status"] == "approved"
            assert valid_object["decision"]["action"] == "approve_candidate_extraction"
            assert valid_object["decision"]["note"].startswith("Reviewed the synthetic")
            assert valid_object["decision_token"] != current_token

            gate_after = json.loads(gate_path.read_text(encoding="utf-8"))
            gate_object_after = next(
                row
                for row in gate_after["objects"]
                if row["object_id"] == initial_object["object_id"]
            )
            assert gate_after["status"] == "approved"
            assert gate_after["gate_digest"] == gate_before["gate_digest"]
            assert gate_after["bundle_digest"] == gate_before["bundle_digest"]
            assert gate_object_after["object_digest"] == gate_object_before["object_digest"]
            assert gate_object_after["review_state"] == "decided"
            assert valid_object["decision_token"] == _decision_token(
                PROJECT_ID,
                STUDY_ID,
                initial_object["object_id"],
                gate_after["gate_digest"],
                gate_object_after["object_digest"],
                parse_decision_revision(gate_object_after["decision"]),
            )

            changed = _changed_paths(valid_before, _snapshot_tree(project))
            assert GATE_RELATIVE in changed
            assert all(
                path == GATE_RELATIVE
                or path in DERIVED_EXACT_PATHS
                or any(path.startswith(prefix) for prefix in DERIVED_PREFIXES)
                for path in changed
            ), changed
            assert _protected_snapshot(valid_before) == _protected_snapshot(
                _snapshot_tree(project)
            )
            assert not any(
                path.startswith("05_release/")
                or path in {"state/current.json", "versions/current.json"}
                for path in changed
            )

            _stop_dashboard(server, thread)
            server = None
            thread = None
            server, thread, cold_base_url = _start_dashboard(review_root)
            status, cold_payload = _request_json(cold_base_url, parse_path)
            assert status == 200
            assert cold_payload == valid_payload
            cold_study, cold_object = _parse_route_row(cold_payload)
            assert cold_study["study_id"] == STUDY_ID
            assert cold_object["decision_token"] == valid_object["decision_token"]
            cold_gate = json.loads(gate_path.read_text(encoding="utf-8"))
            cold_gate_object = next(
                row
                for row in cold_gate["objects"]
                if row["object_id"] == initial_object["object_id"]
            )
            assert cold_gate["status"] == gate_after["status"]
            assert cold_gate["gate_digest"] == gate_after["gate_digest"]
            assert cold_gate_object["object_digest"] == gate_object_after["object_digest"]
            assert _protected_snapshot(valid_before) == _protected_snapshot(
                _snapshot_tree(project)
            )
        finally:
            if server is not None and thread is not None:
                _stop_dashboard(server, thread)
