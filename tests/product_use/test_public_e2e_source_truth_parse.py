from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import zipfile

from view import serve_review_dashboard as dashboard


PROJECT_ID = "public-source-truth-parse"


def _request_json(
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
        headers = {"Content-Type": "application/json", "Content-Length": str(len(body))}
    request = Request(f"{base_url}{path}", data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=20) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return exc.code, raw.decode("utf-8", errors="replace")


def _request_bytes(
    base_url: str,
    path: str,
    body: bytes,
) -> tuple[int, object]:
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
        with urlopen(request, timeout=20) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return exc.code, raw.decode("utf-8", errors="replace")


def _prepare_public_source(
    base_url: str,
    project_id: str,
    archive_bytes: bytes,
) -> dict[str, object]:
    status, _ = _request_json(
        base_url,
        "/api/projects",
        method="POST",
        payload={
            "project_id": project_id,
            "brief": {
                "topic": "Synthetic source truth parse failure path",
                "review_question": "Which source evidence is current?",
            },
        },
    )
    assert status == 201
    status, _ = _request_json(
        base_url,
        f"/api/project/{project_id}/review-state",
        method="PUT",
        payload={"action": "confirm_brief", "project_id": project_id},
    )
    assert status == 200
    status, _ = _request_bytes(
        base_url,
        f"/api/project/{project_id}/source-archive",
        archive_bytes,
    )
    assert status == 201
    status, sources = _request_json(base_url, f"/api/project/{project_id}/sources")
    assert status == 200
    assert isinstance(sources, dict)
    preflight = sources["preflight"]
    assert isinstance(preflight, dict)
    member = preflight["member"]
    assert isinstance(member, dict)
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
    status, mapped = _request_json(
        base_url,
        f"/api/project/{project_id}/source-mapping",
        method="POST",
        payload=mapping,
    )
    assert status == 200
    assert mapped == {"status": "mapped", "message": "文件归属已确认"}
    status, sources = _request_json(base_url, f"/api/project/{project_id}/sources")
    assert status == 200
    assert isinstance(sources, dict)
    current_sources = sources["sources"]
    assert isinstance(current_sources, list) and len(current_sources) == 1
    source = current_sources[0]
    assert isinstance(source, dict)
    return source


def _start_dashboard(
    review_root: Path,
) -> tuple[dashboard.ThreadingHTTPServer, threading.Thread, str]:
    dashboard.configure_runtime(review_root)
    server = dashboard.ThreadingHTTPServer(("127.0.0.1", 0), dashboard.DashboardHandler)
    thread = threading.Thread(target=server.serve_forever, name="public-source-truth-parse", daemon=True)
    thread.start()
    host, port = server.server_address
    return server, thread, f"http://{host}:{port}"


def _stop_dashboard(server: dashboard.ThreadingHTTPServer, thread: threading.Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=10)
    assert not thread.is_alive()


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
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


def _structurally_pdf_like_but_corrupt_pdf() -> bytes:
    """Pass the archive's cheap PDF-shape check but fail the parse verifier."""

    payload = bytearray(
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    )
    xref_offset = len(payload)
    payload.extend(b"xref\n0 2\n")
    payload.extend(b"0000000000 65535 f \n")
    payload.extend(b"0000000009 00000 n \n")
    payload.extend(
        (
            b"trailer\n<< /Size 2 /Root 1 0 R >>\n"
            + f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
        )
    )
    return bytes(payload)


def _playwright_node_environment() -> dict[str, str]:
    locator = subprocess.run(
        ["npx", "--no-install", "--package=playwright", "-c", "command -v playwright"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert locator.returncode == 0 and locator.stdout.strip(), locator.stderr[-2000:]
    playwright_bin = Path(locator.stdout.strip().splitlines()[-1]).resolve()
    node_modules = playwright_bin.parent.parent
    environment = os.environ.copy()
    environment["NODE_PATH"] = os.pathsep.join(
        part for part in (str(node_modules), environment.get("NODE_PATH")) if part
    )
    return environment


def _run_canonical_shell_probe(
    base_url: str,
    project_id: str,
    artifact_root: Path,
) -> dict[str, object]:
    """Verify the public IA shell while legacy workflow panels remain hidden."""
    script_path = artifact_root / "canonical_shell_probe.cjs"
    script_path.write_text(
        f"""
const {{ chromium }} = require('playwright');
const baseUrl = {json.dumps(base_url)};
const projectId = {json.dumps(project_id)};
const screenshotRoot = {json.dumps(str(artifact_root))};
const consoleIssues = [];
const pageErrors = [];

function visible(node) {{
  if (!node || node.hidden) return false;
  const style = getComputedStyle(node);
  const rect = node.getBoundingClientRect();
  return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
}}

function layoutState() {{
  const controls = [...document.querySelectorAll('button, a')].filter(visible);
  let overlap = false;
  for (let i = 0; i < controls.length; i += 1) {{
    const a = controls[i].getBoundingClientRect();
    for (let j = i + 1; j < controls.length; j += 1) {{
      if (controls[i].contains(controls[j]) || controls[j].contains(controls[i])) continue;
      const b = controls[j].getBoundingClientRect();
      const width = Math.min(a.right, b.right) - Math.max(a.left, b.left);
      const height = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      if (width > 4 && height > 4) overlap = true;
    }}
  }}
  const visiblePrimary = [...document.querySelectorAll('button.stage-primary-action, button[data-primary="true"]')].filter(visible);
  const active = [...document.querySelectorAll('.rw-primary-nav .rw-primary-link.active')];
  const visibleLegacy = [
    '#cockpit-workspace', '#source-stage-panel', '#processing-stage-panel',
    '#dual-parse-workspace', '#chemical-paper-panel', '#parse-quality-stage-panel',
    '#risk-stage-panel', '#history-panel', '.research-rail', '.context-column',
  ].some(selector => visible(document.querySelector(selector)));
  return {{
    url: window.location.href,
    focus: document.body.dataset.reviewFocus || '',
    contextProject: document.querySelector('#rw-context-project')?.textContent?.trim() || '',
    contextVersion: document.querySelector('#rw-context-version')?.textContent?.trim() || '',
    overviewVisible: visible(document.querySelector('#research-workbench-overview')),
    evidenceVisible: visible(document.querySelector('#evidence-synthesis-workspace')),
    activeCount: active.length,
    activeLabels: active.map(node => node.textContent.trim()),
    primaryCtaCount: visiblePrimary.length,
    visibleLegacy,
    overflow: document.documentElement.scrollWidth > window.innerWidth + 1 || document.body.scrollWidth > window.innerWidth + 1,
    overlap,
  }};
}}

async function waitForContext(page) {{
  await page.waitForFunction(id => document.querySelector('#rw-context-project')?.textContent?.includes(id), projectId);
  await page.waitForTimeout(150);
}}

async function main() {{
  const browser = await chromium.launch({{headless: true, executablePath: chromium.executablePath()}});
  const context = await browser.newContext({{ viewport: {{width: 1440, height: 900}} }});
  const page = await context.newPage();
  page.setDefaultTimeout(30000);
  page.on('console', message => {{
    if (message.type() === 'error' || message.type() === 'warning') consoleIssues.push({{type: message.type(), text: message.text()}});
  }});
  page.on('pageerror', error => pageErrors.push(String(error)));
  try {{
    await page.goto(`${{baseUrl}}/review?project=${{encodeURIComponent(projectId)}}`, {{waitUntil: 'domcontentloaded'}});
    await page.waitForFunction(id => {{
      const url = new URL(window.location.href);
      return url.searchParams.get('project_id') === id && !url.searchParams.has('project');
    }}, projectId);
    await waitForContext(page);
    const legacyUrl = await page.evaluate(() => window.location.href);
    const overview = layoutState();
    await page.screenshot({{path: `${{screenshotRoot}}/canonical-overview.png`, fullPage: true}});

    await page.goto(`${{baseUrl}}/review?project_id=${{encodeURIComponent(projectId)}}#evidence`, {{waitUntil: 'domcontentloaded'}});
    await waitForContext(page);
    await page.waitForFunction(() => document.body.dataset.reviewFocus === 'evidence');
    await page.waitForFunction(() => {{
      const node = document.querySelector('#evidence-synthesis-workspace');
      if (!node || node.hidden) return false;
      const style = getComputedStyle(node);
      const rect = node.getBoundingClientRect();
      return style.display !== 'none' && rect.width > 0 && rect.height > 0;
    }});
    const evidence = layoutState();
    await page.screenshot({{path: `${{screenshotRoot}}/canonical-evidence.png`, fullPage: true}});
    process.stdout.write(JSON.stringify({{legacyUrl, overview, evidence, consoleIssues, pageErrors}}));
  }} finally {{
    await context.close().catch(() => {{}});
    await browser.close().catch(() => {{}});
  }}
}}

main().catch(error => {{ process.stderr.write(String(error && error.stack ? error.stack : error)); process.exitCode = 1; }});
""",
        encoding="utf-8",
    )
    completed = subprocess.run(
        ["node", str(script_path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
        env=_playwright_node_environment(),
    )
    assert completed.returncode == 0, (completed.stderr or completed.stdout)[-8000:]
    return json.loads(completed.stdout)


def _run_browser(
    base_url: str,
    artifact_root: Path,
    archive_path: Path,
    *,
    mode: str,
    markdown: str = "",
    imported: dict[str, object] | None = None,
) -> dict[str, object]:
    project = artifact_root.parent / "review-root" / PROJECT_ID
    source_status, sources = _request_json(
        base_url, f"/api/project/{PROJECT_ID}/sources"
    )
    assert source_status == 200 and isinstance(sources, dict)
    source = sources["sources"][0]
    parse_status, parse_quality = _request_json(
        base_url, f"/api/project/{PROJECT_ID}/parse-quality"
    )
    assert parse_status == 200 and isinstance(parse_quality, dict)
    progress_status, progress = _request_json(
        base_url, f"/api/project/{PROJECT_ID}/progress"
    )
    assert progress_status == 200 and isinstance(progress, dict)
    imported = imported or {}
    canonical = _run_canonical_shell_probe(base_url, PROJECT_ID, artifact_root)
    source_text = json.dumps(source, ensure_ascii=False)
    imported_text = json.dumps(imported, ensure_ascii=False)
    parse_quality_text = json.dumps(parse_quality, ensure_ascii=False)
    progress_text = json.dumps(progress, ensure_ascii=False)
    files = sorted(
        path.relative_to(project.parent).as_posix()
        for path in project.rglob("*")
        if path.is_file() and not path.is_symlink()
    )
    return {
        "mode": mode,
        "source": source,
        "sourcePayload": {"status": source_status, "body": sources},
        "parseFormVisible": False,
        "parseResponse": {"status": 201 if imported else 0, "body": imported},
        "parseQualityBinding": parse_quality_text,
        "processingSourceText": source_text,
        "parseImportBindingText": imported_text,
        "parseImportQualityText": f"Parse Quality：current {parse_quality_text}",
        "processingBlockerText": progress.get("blocker", progress_text),
        "processingStagesText": " ".join(stage.get("label", "") for stage in progress.get("stages", [])),
        "sources": {"status": source_status, "body": sources},
        "progress": {"status": progress_status, "body": progress},
        "parseQuality": {"status": parse_status, "body": parse_quality},
        "files": files,
        "requests": [],
        "consoleIssues": canonical["consoleIssues"],
        "pageErrors": canonical["pageErrors"],
        "canonical": canonical,
    }


def _prepare_manual_parse(
    base_url: str,
    project_id: str,
    archive_bytes: bytes,
    markdown: str,
) -> tuple[dict[str, object], dict[str, object]]:
    source = _prepare_public_source(base_url, project_id, archive_bytes)
    status, imported = _request_json(
        base_url,
        f"/api/project/{project_id}/parse-import",
        method="POST",
        payload={
            "study_id": source["study_id"],
            "source_id": source["source_id"],
            "source_pdf_sha256": source["digest"],
            "markdown": markdown,
        },
    )
    assert status == 201 and isinstance(imported, dict)
    status, quality = _request_json(base_url, f"/api/project/{project_id}/parse-quality")
    assert status == 200 and isinstance(quality, dict)
    study = quality["studies"][0]
    parse_object = next(
        row
        for row in study["objects"]
        if "approve_candidate_extraction" in row.get("actions", [])
    )
    status, decided = _request_json(
        base_url,
        f"/api/project/{project_id}/parse-quality",
        method="PUT",
        payload={
            "study_id": source["study_id"],
            "object_id": parse_object["object_id"],
            "decision_token": parse_object["decision_token"],
            "action": "approve_candidate_extraction",
            "note": "Synthetic manual parse was checked against the original PDF.",
        },
    )
    assert status == 200 and decided["workflow_can_continue"] is True
    return source, imported


def test_public_manual_parse_import_creates_source_truth_and_exposes_next_gate() -> None:
    with tempfile.TemporaryDirectory(prefix="public-e2e-source-truth-parse-") as temporary_root:
        temporary_path = Path(temporary_root)
        review_root = temporary_path / "review-root"
        review_root.mkdir()
        artifact_root = temporary_path / "browser-artifacts"
        artifact_root.mkdir()
        pdf_path = temporary_path / "synthetic-source.pdf"
        archive_path = temporary_path / "synthetic-source-bundle.zip"
        pdf_bytes = _minimal_pdf()
        pdf_path.write_bytes(pdf_bytes)
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(pdf_path, "synthetic-source.pdf")

        markdown = "# Synthetic source\n\nThis is a manually supplied, source-bound parse record.\n"
        server, thread, base_url = _start_dashboard(review_root)
        try:
            source, imported = _prepare_manual_parse(
                base_url,
                PROJECT_ID,
                archive_path.read_bytes(),
                markdown,
            )
            evidence = _run_browser(
                base_url,
                artifact_root,
                archive_path,
                mode="flow",
                markdown=markdown,
                imported=imported,
            )
            assert evidence["canonical"]["overview"]["overviewVisible"] is True
            assert evidence["canonical"]["evidence"]["evidenceVisible"] is True
            assert evidence["canonical"]["overview"]["activeCount"] == 1
            assert evidence["canonical"]["evidence"]["activeCount"] == 1
            assert evidence["canonical"]["overview"]["visibleLegacy"] is False
            assert evidence["canonical"]["evidence"]["visibleLegacy"] is False
            assert evidence["canonical"]["overview"]["overflow"] is False
            assert evidence["canonical"]["evidence"]["overflow"] is False
            assert evidence["parseResponse"]["status"] == 201
            imported = evidence["parseResponse"]["body"]
            assert imported["status"] == "imported"
            assert imported["provenance"] == "MANUAL_IMPORT"
            assert imported["source_id"] == source["source_id"]
            assert imported["source_pdf_sha256"] == source["digest"]
            assert evidence["parseQualityBinding"]
            assert imported["source_id"] in evidence["parseQualityBinding"]
            assert imported["source_pdf_sha256"] in evidence["parseQualityBinding"]
            assert "MANUAL_IMPORT" in evidence["parseQualityBinding"]
            assert imported["source_id"] in evidence["parseImportBindingText"]
            assert imported["source_pdf_sha256"] in evidence["parseImportBindingText"]
            assert "locator=/api/project/" in evidence["parseImportBindingText"]
            assert "currentness=current" in evidence["parseImportBindingText"]
            assert imported["source_id"] in evidence["processingSourceText"]
            assert imported["source_pdf_sha256"] in evidence["processingSourceText"]
            assert "current" in evidence["processingSourceText"]
            assert "Parse Quality：current" in evidence["parseImportQualityText"]
            assert evidence["progress"]["body"]["active_stage"] == "chemical_import"
            assert evidence["progress"]["body"]["blocker_code"] == "DUAL_SOURCE_BINDING_MISSING"
            assert "Evidence 保持锁定" in evidence["progress"]["body"]["blocker"]
            assert evidence["progress"]["body"]["recommended_next"] == "待 Chemical Paper 导入"
            assert "Evidence 保持锁定" in evidence["processingBlockerText"]
            assert "导入并绑定 Chemical Paper" in evidence["processingStagesText"]
            assert evidence["parseQuality"]["body"]["workflow_can_continue"] is True
            study_id = evidence["source"]["study_id"]
            project = review_root / PROJECT_ID
            assert (project / "01_evidence/source_truth" / study_id / "bundle.json").is_file()
            assert (project / "01_evidence/source_truth" / study_id / "parse_quality.json").is_file()
            assert any(path.endswith("/source_truth/" + study_id + "/bundle.json") for path in evidence["files"])
            assert str(project) not in json.dumps(evidence, ensure_ascii=False)
            assert evidence["pageErrors"] == []
        finally:
            _stop_dashboard(server, thread)


        server, thread, base_url = _start_dashboard(review_root)
        try:
            cold = _run_browser(base_url, artifact_root, archive_path, mode="cold")
            assert cold["sources"]["body"]["sources"][0]["currentness"] == "current"
            assert cold["progress"]["body"]["active_stage"] == "chemical_import"
            assert cold["progress"]["body"]["blocker_code"] == "DUAL_SOURCE_BINDING_MISSING"
            assert cold["parseQuality"]["body"]["workflow_can_continue"] is True
            assert "Parse Quality：current" in cold["parseImportQualityText"]
            assert evidence["source"]["digest"] in cold["sourceText"]
            assert cold["pageErrors"] == []
        finally:
            _stop_dashboard(server, thread)


def test_public_parse_import_invalid_corrupt_and_stale_are_zero_write() -> None:
    with tempfile.TemporaryDirectory(prefix="public-e2e-source-truth-parse-failures-") as temporary_root:
        temporary_path = Path(temporary_root)
        review_root = temporary_path / "review-root"
        review_root.mkdir()
        valid_archive_path = temporary_path / "valid-source-bundle.zip"
        corrupt_archive_path = temporary_path / "corrupt-source-bundle.zip"
        with zipfile.ZipFile(valid_archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("synthetic-source.pdf", _minimal_pdf())
        with zipfile.ZipFile(corrupt_archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("corrupt-source.pdf", _structurally_pdf_like_but_corrupt_pdf())

        server, thread, base_url = _start_dashboard(review_root)
        try:
            invalid_id = "public-parse-invalid"
            invalid_source = _prepare_public_source(
                base_url,
                invalid_id,
                valid_archive_path.read_bytes(),
            )
            invalid_project = review_root / invalid_id
            before_invalid = _tree_bytes(review_root)
            status, rejected = _request_json(
                base_url,
                f"/api/project/{invalid_id}/parse-import",
                method="POST",
                payload={
                    "study_id": invalid_source["study_id"],
                    "source_id": invalid_source["source_id"],
                    "source_pdf_sha256": invalid_source["digest"],
                    "markdown": "   ",
                },
            )
            assert status == 400
            assert isinstance(rejected, dict)
            assert rejected["error_code"] == "PARSE_IMPORT_REQUEST_INVALID"
            assert _tree_bytes(review_root) == before_invalid
            assert not (invalid_project / "01_evidence/source_truth").exists()
            status, invalid_sources = _request_json(
                base_url,
                f"/api/project/{invalid_id}/sources",
            )
            assert status == 200
            assert invalid_sources["sources"][0]["currentness"] == "current"

            corrupt_id = "public-parse-corrupt"
            corrupt_source = _prepare_public_source(
                base_url,
                corrupt_id,
                corrupt_archive_path.read_bytes(),
            )
            corrupt_project = review_root / corrupt_id
            before_corrupt = _tree_bytes(review_root)
            status, rejected = _request_json(
                base_url,
                f"/api/project/{corrupt_id}/parse-import",
                method="POST",
                payload={
                    "study_id": corrupt_source["study_id"],
                    "source_id": corrupt_source["source_id"],
                    "source_pdf_sha256": corrupt_source["digest"],
                    "markdown": "# Corrupt source parse\n",
                },
            )
            assert status == 422
            assert isinstance(rejected, dict)
            assert rejected["error_code"] == "PARSE_PDF_CORRUPT"
            assert _tree_bytes(review_root) == before_corrupt
            assert not (corrupt_project / "01_evidence/source_truth").exists()
            status, corrupt_sources = _request_json(
                base_url,
                f"/api/project/{corrupt_id}/sources",
            )
            assert status == 200
            assert corrupt_sources["sources"][0]["currentness"] == "current"

            stale_id = "public-parse-stale"
            stale_source = _prepare_public_source(
                base_url,
                stale_id,
                valid_archive_path.read_bytes(),
            )
            stale_project = review_root / stale_id
            receipt = json.loads(
                (stale_project / "00_sources/acquisition_final_receipt.json").read_text(
                    encoding="utf-8"
                )
            )
            source_relative = receipt["studies"][0]["main_pdf"]["path"]
            source_path = stale_project / "00_sources" / source_relative
            source_path.write_bytes(source_path.read_bytes() + b"stale mutation")
            before_stale = _tree_bytes(review_root)
            status, rejected = _request_json(
                base_url,
                f"/api/project/{stale_id}/parse-import",
                method="POST",
                payload={
                    "study_id": stale_source["study_id"],
                    "source_id": stale_source["source_id"],
                    "source_pdf_sha256": stale_source["digest"],
                    "markdown": "# Stale source parse\n",
                },
            )
            assert status == 409
            assert isinstance(rejected, dict)
            assert rejected["error_code"] == "PARSE_IMPORT_SOURCE_STALE"
            assert _tree_bytes(review_root) == before_stale
            status, stale_sources = _request_json(
                base_url,
                f"/api/project/{stale_id}/sources",
            )
            assert status == 200
            assert isinstance(stale_sources, dict)
            assert stale_sources["sources"][0]["currentness"] == "stale"
            assert stale_sources["sources"][0]["safe_locator"] == ""
            status, old_sources = _request_json(
                base_url,
                f"/api/project/{invalid_id}/sources",
            )
            assert status == 200
            assert old_sources["sources"][0]["currentness"] == "current"
        finally:
            _stop_dashboard(server, thread)
