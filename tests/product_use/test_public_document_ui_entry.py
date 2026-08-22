from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from tests.product_use.test_prod006_source_to_release import (
    PROJECT_ID,
    _build_project,
    _post_release,
    _start_dashboard,
    _stop_dashboard,
)
from review_writer.project.manuscript_v2 import merge_authoritative_manuscript
from review_writer.project.source_truth import canonical_digest


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _playwright_node_environment() -> dict[str, str]:
    """Reuse the already cached Playwright CLI without installing a dependency."""
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
        raise AssertionError(
            "Playwright tooling first failure while locating cached CLI: "
            f"{detail[-2000:]}"
        )

    playwright_bin = Path(locator.stdout.strip().splitlines()[-1]).resolve()
    node_modules = playwright_bin.parent.parent
    node_environment = os.environ.copy()
    existing_node_path = node_environment.get("NODE_PATH")
    node_environment["NODE_PATH"] = os.pathsep.join(
        part for part in (str(node_modules), existing_node_path) if part
    )
    return node_environment


def _run_real_browser_flow(base_url: str, browser_artifact_root: Path) -> dict[str, object]:
    """Drive the public Final failure path with a real DOM click."""
    browser_script = f"""
const {{ chromium }} = require('playwright');

const baseUrl = process.argv[2];
const browserArtifactRoot = process.argv[3];
const projectId = {json.dumps(PROJECT_ID)};
const expectedOrigin = new URL(baseUrl).origin;
const finalApiPath = `/api/project/${{encodeURIComponent(projectId)}}/final`;
const exportApiPath = `/api/project/${{encodeURIComponent(projectId)}}/export-docx`;
const consoleIssues = [];
const pageErrors = [];
const requests = [];

async function main() {{
let browser;
let context;
let page;
try {{
  browser = await chromium.launch({{
    headless: true,
    executablePath: chromium.executablePath(),
    downloadsPath: browserArtifactRoot,
  }});
  context = await browser.newContext({{ acceptDownloads: true }});
  page = await context.newPage();
  page.setDefaultTimeout(30000);
  page.setDefaultNavigationTimeout(30000);
  page.on('console', message => {{
    if (message.type() === 'error' || message.type() === 'warning') {{
      consoleIssues.push({{ type: message.type(), text: message.text() }});
    }}
  }});
  page.on('pageerror', error => pageErrors.push(String(error)));
  page.on('request', request => requests.push({{method: request.method(), url: request.url()}}));

  await page.goto(`${{baseUrl}}/review`, {{ waitUntil: 'domcontentloaded' }});
  const finalLink = page.locator('.rw-primary-nav a[href="/final#release"]');
  await finalLink.waitFor({{ state: 'visible' }});
  const finalLinkHref = await finalLink.getAttribute('href');
  if (!(await finalLink.isVisible()) || finalLinkHref !== '/final#release') {{
    throw new Error(`generated Final link is not visible: ${{finalLinkHref}}`);
  }}
  const finalNavigation = page.waitForURL(url => {{
    const destination = new URL(url);
    return destination.pathname === '/final' && destination.hash === '#release';
  }});
  await finalLink.click({{ noWaitAfter: true }});
  await finalNavigation;
  const reviewFinalNavigation = new URL(page.url());
  const reviewFinalNavigationPath = reviewFinalNavigation.pathname;
  const reviewFinalNavigationHash = reviewFinalNavigation.hash;
  if (reviewFinalNavigationPath !== '/final' || reviewFinalNavigationHash !== '#release') {{
    throw new Error(`DOM click did not navigate to /final#release: ${{reviewFinalNavigationPath}}${{reviewFinalNavigationHash}}`);
  }}
  const generateButton = page.locator('#docxGen');
  await generateButton.waitFor({{ state: 'visible' }});
  const initialButtonLabel = (await generateButton.textContent()).trim();
  if (initialButtonLabel !== 'Regenerate DOCX') {{
    throw new Error(`unexpected visible document action: ${{initialButtonLabel}}`);
  }}
  const countRequests = (method, pathname) => requests.filter(request => {{
    if (request.method !== method) return false;
    try {{
      return new URL(request.url).pathname === pathname;
    }} catch (_) {{
      return false;
    }}
  }}).length;
  const finalGetCountBefore = countRequests('GET', finalApiPath);

  const postResponsePromise = page.waitForResponse(response =>
    response.request().method() === 'POST' &&
    new URL(response.url()).pathname === exportApiPath
  );
  const dialogPromise = page.waitForEvent('dialog');
  await generateButton.click({{ noWaitAfter: true }});
  const postResponse = await postResponsePromise;
  const dialog = await dialogPromise;
  const alertMessage = dialog.message();
  await dialog.dismiss();
  await new Promise(resolve => setTimeout(resolve, 250));
  const finalGetCountAfter = countRequests('GET', finalApiPath);
  const externalRequestUrls = requests.map(request => request.url).filter(url => {{
    try {{
      return new URL(url).origin !== expectedOrigin;
    }} catch (_) {{
      return false;
    }}
  }});

  process.stdout.write(JSON.stringify({{
    reviewFinalLinkVisible: true,
    reviewFinalLinkHref: finalLinkHref,
    reviewFinalNavigationPath,
    reviewFinalNavigationHash,
    initialButtonVisible: true,
    initialButtonLabel,
    postMethod: postResponse.request().method(),
    postUrl: postResponse.url(),
    postStatus: postResponse.status(),
    postContentType: postResponse.headers()['content-type'] || '',
    exportPostCount: countRequests('POST', exportApiPath),
    alertMessage,
    finalGetCountBefore,
    finalGetCountAfter,
    consoleIssues,
    pageErrors,
    requestUrls: requests.map(request => request.url),
    externalRequestUrls,
    cookieCount: (await context.cookies()).length,
  }}));
}} catch (error) {{
  const diagnostic = {{
    error: String(error && error.stack ? error.stack : error),
    consoleIssues,
    pageErrors,
    requestUrls: requests.map(request => request.url),
  }};
  process.stderr.write(JSON.stringify(diagnostic));
  process.exitCode = 1;
}} finally {{
  if (context) await context.close().catch(() => {{}});
  if (browser) await browser.close().catch(() => {{}});
}}
}}

main();
"""
    script_path = browser_artifact_root / "public_document_ui_entry.cjs"
    script_path.write_text(browser_script, encoding="utf-8")
    completed = subprocess.run(
        ["node", str(script_path), base_url, str(browser_artifact_root)],
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
        env=_playwright_node_environment(),
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise AssertionError(
            "Playwright tooling first failure during public UI flow: "
            f"{detail[-6000:]}"
        )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            "Playwright tooling returned non-JSON evidence: "
            f"{completed.stdout[-2000:]}"
        ) from exc


def _prepare_review_ui_project(project: Path) -> None:
    """Complete only the legal synthetic source metadata needed by /review."""
    review_state_path = project / "00_brief/review_state.json"
    review_state = json.loads(review_state_path.read_text(encoding="utf-8"))
    review_state["brief"] = {
        **(review_state.get("brief") or {}),
        "project_label": "Synthetic public document UI project",
    }
    review_state_path.write_text(
        json.dumps(review_state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    download_id = "prod006-main-pdf"
    manifest_path = project / "00_discovery/acquisition_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["downloads"][0].update(
        {
            "download_id": download_id,
            "document_role": "MAIN",
            "target_path": "manual_upload/inbox/prod006-main.pdf",
        }
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    pdf_path = project / "00_sources/manual_upload/inbox/prod006-main.pdf"
    receipt = {
        "schema_version": "public-corpus-acquisition-receipt.v1",
        "created_at": "2026-08-16T00:00:00+08:00",
        "manifest_path": "00_discovery/acquisition_manifest.json",
        "manifest_sha256": _sha256_bytes(manifest_path.read_bytes()),
        "results": [
            {
                "download_id": download_id,
                "save_as": f"{download_id}.pdf",
                "study_id": "study-prod006",
                "doi": "10.1000/prod006-tiny",
                "document_role": "MAIN",
                "expected_format": "PDF",
                "target_path": "manual_upload/inbox/prod006-main.pdf",
                "status": "VERIFIED_EXISTING",
                "reason": "Synthetic fixture bytes are already present.",
                "sha256": _sha256_bytes(pdf_path.read_bytes()),
                "size_bytes": pdf_path.stat().st_size,
                "http_status": None,
            }
        ],
        "counts": {"VERIFIED_EXISTING": 1},
        "manual_queue_count": 0,
    }
    receipt_path = project / "00_sources/acquisition_receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_public_document_ui_entry_surfaces_figure_attribution_failure_without_mutation() -> None:
    """The public Final UI must safely surface a failed regeneration attempt."""
    with tempfile.TemporaryDirectory(prefix="rel001-public-document-ui-") as temporary_root:
        temporary_path = Path(temporary_root)
        review_root = temporary_path / "review-root"
        review_root.mkdir()
        browser_artifact_root = temporary_path / "browser-artifacts"
        browser_artifact_root.mkdir()
        project = _build_project(review_root)
        assert project.parent == review_root
        _prepare_review_ui_project(project)

        server, thread, base_url = _start_dashboard(review_root)
        try:
            parsed_base_url = base_url.removeprefix("http://")
            assert parsed_base_url.startswith("127.0.0.1:")
            assert not parsed_base_url.startswith("127.0.0.1:46844")

            release_status, release_result = _post_release(base_url)
            assert release_status == 200
            assert release_result["ok"] is True
            release_relative_paths = (
                "05_release/self_reviewed_draft.md",
                "05_release/self_reviewed_draft.docx",
                "05_release/release_snapshot.json",
                "05_release/quality_report.json",
            )
            release_bytes_before = {
                relative_path: (project / relative_path).read_bytes()
                for relative_path in release_relative_paths
            }

            registry_path = project / "03_figures/source_figure_registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            assert registry["figures"][0]["figure_label"] == "Figure 1"
            registry["figures"][0]["figure_label"] = "Figure 1 Missing Attribution"
            registry["registry_digest"] = canonical_digest(
                {
                    key: registry[key]
                    for key in (
                        "source_truth_digest",
                        "content_list_v2_digest",
                        "chemical_paper_project_binding_digest",
                        "figures",
                        "locator_gaps",
                    )
                }
            )
            registry_path.write_text(
                json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            merged = merge_authoritative_manuscript(project)
            assert merged["status"] == "approved"

            try:
                browser_result = _run_real_browser_flow(
                    base_url,
                    browser_artifact_root,
                )
            finally:
                if browser_artifact_root.exists():
                    shutil.rmtree(browser_artifact_root)
            assert not browser_artifact_root.exists()

            release_bytes_after = {
                relative_path: (project / relative_path).read_bytes()
                for relative_path in release_relative_paths
            }

            assert browser_result["initialButtonVisible"] is True
            assert browser_result["reviewFinalLinkVisible"] is True
            assert browser_result["reviewFinalLinkHref"] == "/final#release"
            assert browser_result["reviewFinalNavigationPath"] == "/final"
            assert browser_result["reviewFinalNavigationHash"] == "#release"
            assert browser_result["initialButtonLabel"] == "Regenerate DOCX"
            assert browser_result["postMethod"] == "POST"
            assert browser_result["postStatus"] == 400
            assert browser_result["postContentType"].lower().startswith("text/html")
            assert browser_result["exportPostCount"] == 1
            assert "FIGURE_ATTRIBUTION_MISSING" in browser_result["alertMessage"]
            assert "JSON.parse" not in browser_result["alertMessage"]
            assert "HTML" not in browser_result["alertMessage"]
            assert browser_result["finalGetCountAfter"] == browser_result["finalGetCountBefore"]
            assert release_bytes_after == release_bytes_before

            assert browser_result["pageErrors"] == []
            assert browser_result["externalRequestUrls"] == []
            assert browser_result["cookieCount"] == 0
            assert all("127.0.0.1:46844" not in url for url in browser_result["requestUrls"])
        finally:
            _stop_dashboard(server, thread)
