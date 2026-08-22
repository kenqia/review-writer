from __future__ import annotations

import hashlib
import json
import tempfile
import threading
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from review_writer.product_foundation import VersionContext
from review_writer.product_foundation.project_root import version_context_root
from view import serve_review_dashboard as dashboard


PROJECT_ID = "public-history-synthetic"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _registered_project(review_root: Path) -> Path:
    project = review_root / PROJECT_ID
    state_path = project / "00_brief" / "review_state.json"
    _write_json(state_path, {"project_id": PROJECT_ID, "status": "drafting"})
    context = VersionContext.create(
        {
            "artifact_refs": [
                {
                    "path": "00_brief/review_state.json",
                    "sha256": hashlib.sha256(state_path.read_bytes()).hexdigest(),
                }
            ],
            "currentness": "current",
            "version_token": "history-v1",
        },
        project_id=PROJECT_ID,
        version_id="v1",
        branch_id="main",
        branch_name="Main",
        project_root=project,
    )
    context.publish_active_head(
        {
            **context.view_version("v1").snapshot,
            "version_token": "history-v2",
        },
        expected_head_id="v1",
        expected_revision=0,
        version_id="v2",
    )
    return project


def _request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {} if body is None else {
        "Content-Type": "application/json",
        "Content-Length": str(len(body)),
    }
    request = Request(f"{base_url}{path}", data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _start_dashboard(
    review_root: Path,
) -> tuple[dashboard.ThreadingHTTPServer, threading.Thread, str]:
    dashboard.configure_runtime(review_root)
    server = dashboard.ThreadingHTTPServer(("127.0.0.1", 0), dashboard.DashboardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, thread, f"http://{host}:{port}"


def _stop_dashboard(server: dashboard.ThreadingHTTPServer, thread: threading.Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=10)
    assert not thread.is_alive()


def test_review_dashboard_includes_history_controls() -> None:
    html = (REPO_ROOT / "view" / "assets" / "dashboard" / "review.html").read_text(
        encoding="utf-8"
    )

    assert 'id="history-panel"' in html
    assert 'id="history-branch-form"' in html
    assert 'id="history-undo-form"' in html


def test_public_history_branch_and_undo_are_explicit_and_pointer_last() -> None:
    with tempfile.TemporaryDirectory(prefix="public-history-entry-") as temporary_root:
        review_root = Path(temporary_root)
        project = _registered_project(review_root)

        server, thread, base_url = _start_dashboard(review_root)
        try:
            status, history = _request(base_url, f"/api/project/{PROJECT_ID}/history")
            assert status == 200
            assert history["current"]["version_id"] == "v2"
            assert history["revision"] == 1
            assert [row["version_id"] for row in history["history"]] == ["v1", "v2"]
            assert history["history"][-1]["can_write"] is True

            pointer_before_invalid = (version_context_root(project) / "current.json").read_bytes()
            status, invalid = _request(
                base_url,
                f"/api/project/{PROJECT_ID}/history/branch",
                method="POST",
                payload={"source_version_id": "v1"},
            )
            assert status == 400
            assert invalid["error_code"] == "HISTORY_REQUEST_INVALID"
            assert (version_context_root(project) / "current.json").read_bytes() == pointer_before_invalid

            pointer_before_stale = (version_context_root(project) / "current.json").read_bytes()
            status, stale = _request(
                base_url,
                f"/api/project/{PROJECT_ID}/history/branch",
                method="POST",
                payload={
                    "source_version_id": "v1",
                    "branch_id": "stale-branch",
                    "branch_name": "Stale branch",
                    "version_id": "stale-v1",
                    "activate": True,
                    "confirm": True,
                    "expected_revision": 0,
                },
            )
            assert status == 409
            assert stale["error_code"] == "STALE_REVISION"
            assert (version_context_root(project) / "current.json").read_bytes() == pointer_before_stale

            status, undone = _request(
                base_url,
                f"/api/project/{PROJECT_ID}/history/undo",
                method="POST",
                payload={
                    "target_version_id": "v1",
                    "branch_id": "rollback",
                    "branch_name": "Rollback from v2",
                    "version_id": "rollback-v1",
                    "expected_head_id": "v2",
                    "confirm": True,
                    "expected_revision": 1,
                },
            )
            assert status == 200
            assert undone["result"] == "UNDONE"
            assert undone["current"]["version_id"] == "rollback-v1"
            assert undone["current"]["branch_id"] == "rollback"
            assert undone["revision"] == 2

            status, branched = _request(
                base_url,
                f"/api/project/{PROJECT_ID}/history/branch",
                method="POST",
                payload={
                    "source_version_id": "v1",
                    "branch_id": "review",
                    "branch_name": "Review branch",
                    "version_id": "review-v1",
                    "activate": True,
                    "confirm": True,
                    "expected_revision": 2,
                },
            )
            assert status == 200
            assert branched["result"] == "BRANCHED"
            assert branched["current"]["version_id"] == "review-v1"
            assert branched["current"]["branch_id"] == "review"
            assert branched["revision"] == 3
            assert {row["version_id"] for row in branched["history"]} == {
                "v1",
                "v2",
                "rollback-v1",
                "review-v1",
            }
        finally:
            _stop_dashboard(server, thread)
