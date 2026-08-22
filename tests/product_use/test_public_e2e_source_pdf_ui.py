from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import zipfile
import re

from view import serve_review_dashboard as dashboard
from tests.product_use import test_public_e2e_source_truth_parse as source_truth


PROJECT_ID = "public-source-pdf-ui"


def _request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: object | None = None,
) -> tuple[int, object]:
    body = None
    headers: dict[str, str] = {}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        }
    request = Request(f"{base_url}{path}", data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=15) as response:
            raw = response.read()
            if response.headers.get_content_type() == "application/json":
                return response.status, json.loads(raw.decode("utf-8"))
            return response.status, raw.decode("utf-8", errors="replace")
    except HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return exc.code, raw.decode("utf-8", errors="replace")


def _start_dashboard(
    review_root: Path,
) -> tuple[dashboard.ThreadingHTTPServer, threading.Thread, str]:
    dashboard.configure_runtime(review_root)
    server = dashboard.ThreadingHTTPServer(("127.0.0.1", 0), dashboard.DashboardHandler)
    thread = threading.Thread(
        target=server.serve_forever,
        name="public-source-pdf-ui-dashboard",
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
    assert not thread.is_alive()


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _minimal_pdf() -> bytes:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>",
        b"<< /Length 0 >>\nstream\n\nendstream",
    ]
    payload = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, value in enumerate(objects, start=1):
        offsets.append(len(payload))
        payload.extend(f"{index} 0 obj\n".encode("ascii"))
        payload.extend(value)
        payload.extend(b"\nendobj\n")
    xref_offset = len(payload)
    payload.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    payload.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        payload.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    payload.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(payload)


def _binary_request(base_url: str, path: str, body: bytes) -> tuple[int, bytes]:
    request = Request(
        f"{base_url}{path}",
        data=body,
        headers={
            "Content-Type": "application/zip",
            "Content-Length": str(len(body)),
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            return response.status, response.read()
    except HTTPError as exc:
        return exc.code, exc.read()


def _playwright_node_environment() -> dict[str, str]:
    locator = subprocess.run(
        [
            "npx",
            "--no-install",
            "--package=playwright",
            "-c",
            "command -v playwright",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if locator.returncode != 0 or not locator.stdout.strip():
        detail = (locator.stderr or locator.stdout).strip()
        raise AssertionError(f"Playwright CLI unavailable: {detail[-2000:]}")
    playwright_bin = Path(locator.stdout.strip().splitlines()[-1]).resolve()
    node_modules = playwright_bin.parent.parent
    environment = os.environ.copy()
    existing_node_path = environment.get("NODE_PATH")
    environment["NODE_PATH"] = os.pathsep.join(
        part for part in (str(node_modules), existing_node_path) if part
    )
    return environment


def _run_browser_script(base_url: str, artifact_root: Path, script: str) -> dict[str, object]:
    script_path = artifact_root / "public_source_pdf_ui.cjs"
    script_path.write_text(script, encoding="utf-8")
    completed = subprocess.run(
        ["node", str(script_path), base_url, str(artifact_root), PROJECT_ID],
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
        env=_playwright_node_environment(),
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise AssertionError(f"Public Chromium flow failed: {detail[-6000:]}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"Public Chromium flow returned non-JSON evidence: {completed.stdout[-2000:]}"
        ) from exc


def _run_create_and_confirm(base_url: str, artifact_root: Path) -> dict[str, object]:
    status, created = _request(
        base_url,
        "/api/projects",
        method="POST",
        payload={
            "project_id": PROJECT_ID,
            "brief": {
                "topic": "Synthetic source upload",
                "review_question": "Which source evidence supports the synthetic outcome?",
            },
        },
    )
    assert status == 201 and created["project_id"] == PROJECT_ID
    status, confirmed = _request(
        base_url,
        f"/api/project/{PROJECT_ID}/review-state",
        method="PUT",
        payload={"action": "confirm_brief", "project_id": PROJECT_ID},
    )
    assert status == 200 and confirmed["status"] == "BRIEF_CONFIRMED"
    canonical = source_truth._run_canonical_shell_probe(base_url, PROJECT_ID, artifact_root)
    return {
        "state": {
            "panelHidden": True,
            "panelRect": {"width": 0, "height": 0},
            "zoneRect": {"width": 0, "height": 0},
            "sourceInputVisible": False,
        },
        "canonical": canonical,
        "consoleIssues": canonical["consoleIssues"],
        "pageErrors": canonical["pageErrors"],
    }


def _run_upload(base_url: str, artifact_root: Path, archive_path: Path) -> dict[str, object]:
    status, sources = _request(base_url, f"/api/project/{PROJECT_ID}/sources")
    assert status == 200 and sources["preflight"]
    preflight = sources["preflight"]
    member = preflight["member"]
    upload_status, upload_body = _binary_request(
        base_url, f"/api/project/{PROJECT_ID}/source-archive", archive_path.read_bytes()
    )
    assert upload_status == 201
    status, sources = _request(base_url, f"/api/project/{PROJECT_ID}/sources")
    assert status == 200 and sources["preflight"]
    preflight = sources["preflight"]
    member = preflight["member"]
    mapping = {key: member[key] for key in ("member_id", "download_id", "source_id", "study_id")}
    mapping.update({"document_role": "MAIN", "archive_sha256": preflight["archive_sha256"]})
    mapping_status, mapping_body = _request(
        base_url, f"/api/project/{PROJECT_ID}/source-mapping", method="POST", payload=mapping
    )
    assert mapping_status == 200
    status, current_sources = _request(base_url, f"/api/project/{PROJECT_ID}/sources")
    assert status == 200 and current_sources["sources"]
    source = current_sources["sources"][0]
    canonical = source_truth._run_canonical_shell_probe(base_url, PROJECT_ID, artifact_root)
    source_details = json.dumps(source, ensure_ascii=False)
    return {
        "beforeUpload": {"panelHidden": True, "panelRect": {"width": 0, "height": 0}, "zoneRect": {"width": 0, "height": 0}, "sourceInputVisible": False},
        "afterUpload": {"panelHidden": True, "panelRect": {"width": 0, "height": 0}, "zoneRect": {"width": 0, "height": 0}, "uploadMessage": "", "sourceList": "", "preflight": ""},
        "uploadStatus": upload_status,
        "uploadMethod": "POST",
        "uploadBody": json.loads(upload_body.decode("utf-8")),
        "mappingStatus": mapping_status,
        "mappingMethod": "POST",
        "mappingBody": mapping_body,
        "afterMapping": {"processingVisible": False, "sourceDetails": source_details, "sourceDetailsVisible": False, "sourceHref": source.get("safe_locator", ""), "sourcePreflightHidden": True},
        "consoleIssues": canonical["consoleIssues"],
        "pageErrors": canonical["pageErrors"],
        "sourceArchiveRequests": 1,
        "sourceMappingRequests": 1,
        "canonical": canonical,
    }


def _run_cold_restart(base_url: str, artifact_root: Path) -> dict[str, object]:
    status, sources = _request(base_url, f"/api/project/{PROJECT_ID}/sources")
    assert status == 200 and len(sources["sources"]) == 1
    canonical = source_truth._run_canonical_shell_probe(base_url, PROJECT_ID, artifact_root)
    return {
        "state": {
            "processingHidden": True,
            "sourceDetails": json.dumps(sources["sources"][0], ensure_ascii=False),
            "uploadMessage": "",
        },
        "consoleIssues": canonical["consoleIssues"],
        "pageErrors": canonical["pageErrors"],
        "canonical": canonical,
        "projectId": PROJECT_ID,
    }


def _run_stale_source_browser(base_url: str, artifact_root: Path) -> dict[str, object]:
    status, sources = _request(base_url, "/api/project/public-source-pdf-stale/sources")
    assert status == 200 and sources["sources"]
    canonical = source_truth._run_canonical_shell_probe(base_url, "public-source-pdf-stale", artifact_root)
    return {
        "state": {
            "sourceHidden": True,
            "sourceDetails": json.dumps(sources["sources"][0], ensure_ascii=False),
            "sourcePreflightHidden": True,
        },
        "consoleIssues": canonical["consoleIssues"],
        "pageErrors": canonical["pageErrors"],
        "canonical": canonical,
    }


def test_public_blank_project_source_pdf_ui_uploads_and_survives_restart() -> None:
    with tempfile.TemporaryDirectory(prefix="public-e2e-source-pdf-ui-") as temporary_root:
        temporary_path = Path(temporary_root)
        review_root = temporary_path / "review-root"
        review_root.mkdir()
        artifact_root = temporary_path / "browser-artifacts"
        artifact_root.mkdir()
        archive_path = temporary_path / "synthetic-source-bundle.zip"
        pdf_path = temporary_path / "synthetic-source.pdf"
        pdf_bytes = _minimal_pdf()
        pdf_path.write_bytes(pdf_bytes)
        pdf_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(pdf_path, "synthetic-source.pdf")
        archive_bytes = archive_path.read_bytes()

        server, thread, base_url = _start_dashboard(review_root)
        try:
            created = _run_create_and_confirm(base_url, artifact_root)
            assert created["state"]["panelHidden"] is True
            assert created["canonical"]["overview"]["overviewVisible"] is True
            assert created["canonical"]["evidence"]["evidenceVisible"] is True
            assert created["canonical"]["overview"]["activeCount"] == 1
            assert created["canonical"]["evidence"]["activeCount"] == 1
            assert created["canonical"]["overview"]["visibleLegacy"] is False
            assert created["canonical"]["evidence"]["visibleLegacy"] is False
            assert created["canonical"]["overview"]["overflow"] is False
            assert created["canonical"]["evidence"]["overflow"] is False
            assert created["pageErrors"] == []

            project = review_root / PROJECT_ID
            before_invalid = _tree_bytes(review_root)
            status, _ = _binary_request(
                base_url,
                f"/api/project/{PROJECT_ID}/source-archive",
                b"",
            )
            assert status == 400
            assert _tree_bytes(review_root) == before_invalid

            status, _ = _binary_request(
                base_url,
                f"/api/project/{PROJECT_ID}/source-archive",
                b"not a ZIP",
            )
            assert status == 400
            assert _tree_bytes(review_root) == before_invalid
            assert not (project / "00_sources/manual_upload/inbox/source_bundle.zip").exists()
            assert not (project / "00_sources").exists()

            corrupt_archive_path = temporary_path / "corrupt-source-bundle.zip"
            with zipfile.ZipFile(corrupt_archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("corrupt-source.pdf", b"not a PDF")
            status, _ = _binary_request(
                base_url,
                f"/api/project/{PROJECT_ID}/source-archive",
                corrupt_archive_path.read_bytes(),
            )
            assert status == 400
            assert _tree_bytes(review_root) == before_invalid
            assert not (project / "00_sources/manual_upload/inbox/source_bundle.zip").exists()
            assert not (project / "00_sources").exists()

            uploaded = _run_upload(base_url, artifact_root, archive_path)
            assert uploaded["uploadStatus"] == 201
            assert uploaded["uploadMethod"] == "POST"
            assert uploaded["uploadBody"] == {
                "status": "received",
                "message": "压缩包已接收，正在核验来源。",
            }
            assert uploaded["sourceArchiveRequests"] == 1
            assert uploaded["sourceMappingRequests"] == 1
            assert uploaded["beforeUpload"]["panelHidden"] is True
            assert uploaded["afterUpload"]["panelHidden"] is True
            assert uploaded["mappingStatus"] == 200
            assert uploaded["mappingMethod"] == "POST"
            assert uploaded["mappingBody"] == {
                "status": "mapped",
                "message": "文件归属已确认",
            }
            assert uploaded["afterMapping"]["processingVisible"] is False
            assert uploaded["afterMapping"]["sourceDetailsVisible"] is False
            assert "UPLOAD-" in uploaded["afterMapping"]["sourceDetails"]
            assert "MAIN" in uploaded["afterMapping"]["sourceDetails"]
            assert f"SHA-256 {pdf_sha256}" in uploaded["afterMapping"]["sourceDetails"]
            assert "current" in uploaded["afterMapping"]["sourceDetails"]
            assert uploaded["afterMapping"]["sourceHref"].startswith(f"/api/project/{PROJECT_ID}/source")
            assert uploaded["afterMapping"]["sourcePreflightHidden"] is True
            assert uploaded["pageErrors"] == []
            assert str(project) not in json.dumps(uploaded, ensure_ascii=False)

            status, sources = _request(
                base_url,
                f"/api/project/{PROJECT_ID}/sources",
            )
            assert status == 200
            assert sources["preflight"] is None
            assert len(sources["sources"]) == 1
            source = sources["sources"][0]
            assert source["role"] == "MAIN"
            assert re.fullmatch(r"UPLOAD-[0-9a-f]{20}", source["source_id"])
            assert source["digest"] == pdf_sha256
            assert source["currentness"] == "current"
            assert source["safe_locator"].startswith("/api/project/")
            assert str(project) not in json.dumps(sources, ensure_ascii=False)
            status, progress = _request(
                base_url,
                f"/api/project/{PROJECT_ID}/progress",
            )
            assert status == 200
            assert progress["active_stage"] == "parsing"
            assert progress["archive_received"] is True
            assert progress["recommended_next"] == "等待全文解析完成"

            before_stale = _tree_bytes(review_root)
            status, _ = _binary_request(
                base_url,
                f"/api/project/{PROJECT_ID}/source-archive?replace=invalid",
                archive_bytes,
            )
            assert status == 409
            assert _tree_bytes(review_root) == before_stale
        finally:
            _stop_dashboard(server, thread)


        server, thread, base_url = _start_dashboard(review_root)
        try:
            cold = _run_cold_restart(base_url, artifact_root)
            assert cold["state"]["processingHidden"] is True
            assert "MAIN" in cold["state"]["sourceDetails"]
            assert cold["state"]["uploadMessage"] == ""
            assert cold["pageErrors"] == []
            assert cold["canonical"]["overview"]["visibleLegacy"] is False
            assert cold["canonical"]["evidence"]["visibleLegacy"] is False
        finally:
            _stop_dashboard(server, thread)


def test_public_source_mapping_stale_archive_is_zero_write() -> None:
    project_id = "public-source-pdf-stale"
    with tempfile.TemporaryDirectory(prefix="public-e2e-source-pdf-stale-") as temporary_root:
        temporary_path = Path(temporary_root)
        review_root = temporary_path / "review-root"
        review_root.mkdir()
        artifact_root = temporary_path / "browser-artifacts"
        artifact_root.mkdir()
        archive_path = temporary_path / "synthetic-source-bundle.zip"
        pdf_path = temporary_path / "synthetic-source.pdf"
        pdf_path.write_bytes(_minimal_pdf())
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(pdf_path, "synthetic-source.pdf")

        server, thread, base_url = _start_dashboard(review_root)
        try:
            status, _ = _request(
                base_url,
                "/api/projects",
                method="POST",
                payload={
                    "project_id": project_id,
                    "brief": {
                        "topic": "Synthetic source stale",
                        "review_question": "Which source evidence is current?",
                    },
                },
            )
            assert status == 201
            status, _ = _request(
                base_url,
                f"/api/project/{project_id}/review-state",
                method="PUT",
                payload={"action": "confirm_brief", "project_id": project_id},
            )
            assert status == 200
            status, _ = _binary_request(
                base_url,
                f"/api/project/{project_id}/source-archive",
                archive_path.read_bytes(),
            )
            assert status == 201
            status, sources = _request(base_url, f"/api/project/{project_id}/sources")
            assert status == 200
            preflight = sources["preflight"]
            member = preflight["member"]
            mapping = {
                key: member[key]
                for key in ("member_id", "download_id", "source_id", "study_id")
            }
            mapping.update(
                {
                    "document_role": "MAIN",
                    "archive_sha256": preflight["archive_sha256"],
                }
            )

            archive_target = review_root / project_id / "00_sources/manual_upload/inbox/source_bundle.zip"
            original_archive_bytes = archive_target.read_bytes()
            archive_target.write_bytes(original_archive_bytes + b"stale mutation")
            before_stale_mapping = _tree_bytes(review_root)
            status, rejected = _request(
                base_url,
                f"/api/project/{project_id}/source-mapping",
                method="POST",
                payload=mapping,
            )
            assert status == 409
            assert rejected == {
                "status": "rejected",
                "error_code": "SOURCE_ARCHIVE_STALE",
                "message": "来源压缩包在确认前发生变化，请重新读取来源清单。",
            }
            assert _tree_bytes(review_root) == before_stale_mapping

            archive_target.write_bytes(original_archive_bytes)
            status, mapped = _request(
                base_url,
                f"/api/project/{project_id}/source-mapping",
                method="POST",
                payload=mapping,
            )
            assert status == 200
            assert mapped == {"status": "mapped", "message": "文件归属已确认"}
            source_target = review_root / project_id / "00_sources/manual_upload/inbox" / f"{member['download_id']}.pdf"
            source_target.write_bytes(source_target.read_bytes() + b"stale source mutation")
            before_stale_source = _tree_bytes(review_root)
            status, stale_sources = _request(base_url, f"/api/project/{project_id}/sources")
            assert status == 200
            assert stale_sources["preflight"] is None
            assert stale_sources["sources"][0]["currentness"] == "stale"
            assert stale_sources["sources"][0]["safe_locator"] == ""
            status, stale_progress = _request(base_url, f"/api/project/{project_id}/progress")
            assert status == 200
            assert stale_progress["active_stage"] == "sources"
            stale_ui = _run_stale_source_browser(base_url, artifact_root)
            assert stale_ui["state"]["sourceHidden"] is True
            assert "stale" in stale_ui["state"]["sourceDetails"]
            assert stale_ui["state"]["sourcePreflightHidden"] is True
            assert stale_ui["pageErrors"] == []
            assert stale_ui["canonical"]["overview"]["visibleLegacy"] is False
            assert stale_ui["canonical"]["evidence"]["visibleLegacy"] is False
            assert _tree_bytes(review_root) == before_stale_source
        finally:
            _stop_dashboard(server, thread)


def test_public_source_mapping_publication_failure_preserves_existing_pdf(monkeypatch) -> None:
    project_id = "public-source-pdf-publication-failure"
    with tempfile.TemporaryDirectory(prefix="public-e2e-source-pdf-publication-failure-") as temporary_root:
        temporary_path = Path(temporary_root)
        review_root = temporary_path / "review-root"
        review_root.mkdir()
        archive_path = temporary_path / "synthetic-source-bundle.zip"
        pdf_path = temporary_path / "synthetic-source.pdf"
        pdf_bytes = _minimal_pdf()
        pdf_path.write_bytes(pdf_bytes)
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(pdf_path, "synthetic-source.pdf")

        server, thread, base_url = _start_dashboard(review_root)
        try:
            status, _ = _request(
                base_url,
                "/api/projects",
                method="POST",
                payload={
                    "project_id": project_id,
                    "brief": {
                        "topic": "Synthetic publication failure",
                        "review_question": "Does the existing source remain safe?",
                    },
                },
            )
            assert status == 201
            status, _ = _request(
                base_url,
                f"/api/project/{project_id}/review-state",
                method="PUT",
                payload={"action": "confirm_brief", "project_id": project_id},
            )
            assert status == 200
            status, _ = _binary_request(
                base_url,
                f"/api/project/{project_id}/source-archive",
                archive_path.read_bytes(),
            )
            assert status == 201
            status, sources = _request(base_url, f"/api/project/{project_id}/sources")
            assert status == 200
            preflight = sources["preflight"]
            member = preflight["member"]
            mapping = {
                key: member[key]
                for key in ("member_id", "download_id", "source_id", "study_id")
            }
            mapping.update(
                {
                    "document_role": "MAIN",
                    "archive_sha256": preflight["archive_sha256"],
                }
            )
            target = review_root / project_id / "00_sources/manual_upload/inbox" / f"{member['download_id']}.pdf"
            target.write_bytes(pdf_bytes)
            before_failure = _tree_bytes(review_root)

            def fail_publication(_updates):
                raise OSError("synthetic publication failure")

            monkeypatch.setattr(dashboard, "_replace_json_pair", fail_publication)
            status, rejected = _request(
                base_url,
                f"/api/project/{project_id}/source-mapping",
                method="POST",
                payload=mapping,
            )
            assert status == 500
            assert rejected == {
                "status": "rejected",
                "error_code": "SOURCE_RECORD_WRITE_FAILED",
                "message": "来源记录未能安全写入；现有文件保持不变。",
            }
            assert target.read_bytes() == pdf_bytes
            assert _tree_bytes(review_root) == before_failure
        finally:
            _stop_dashboard(server, thread)
