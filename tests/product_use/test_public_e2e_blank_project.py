from __future__ import annotations

import json
import tempfile
import threading
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from view import serve_review_dashboard as dashboard


PROJECT_ID = "public-blank-synthetic"


def _request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: object | None = None,
) -> tuple[int, Any]:
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
            content_type = response.headers.get_content_type()
            if content_type == "application/json":
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
        name="public-blank-project-dashboard",
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


def test_public_blank_project_creation_is_visible_and_persists_after_restart() -> None:
    with tempfile.TemporaryDirectory(prefix="public-e2e-blank-project-") as temporary_root:
        review_root = Path(temporary_root)
        (review_root / "synthetic.pdf").write_bytes(
            b"%PDF-1.4\n% non-sensitive synthetic input only\n"
        )

        server, thread, base_url = _start_dashboard(review_root)
        try:
            status, projects = _request(base_url, "/api/projects")
            assert status == 200
            assert projects == []

            status, created = _request(
                base_url,
                "/api/projects",
                method="POST",
                payload={
                    "project_id": PROJECT_ID,
                    "brief": {
                        "topic": "Synthetic visible-light chemistry",
                        "review_question": "What evidence supports the synthetic reaction outcome?",
                    },
                },
            )
            assert status == 201
            assert created["ok"] is True
            assert created["project_id"] == PROJECT_ID
            assert created["status"] == "created"
            assert created["next_action"] == {
                "project_id": PROJECT_ID,
                "route": "/review",
            }

            status, state = _request(
                base_url,
                f"/api/project/{PROJECT_ID}/review-state",
            )
            assert status == 200
            assert state["project_id"] == PROJECT_ID
            assert state["status"] == "AWAITING_BRIEF_CONFIRMATION"
            assert state["current_stage"] == "review_brief"
            assert state["brief"]["topic"] == "Synthetic visible-light chemistry"
            assert state["brief"]["review_question"].startswith("What evidence")
            assert (review_root / PROJECT_ID / "00_sources").exists() is False
            assert (review_root / PROJECT_ID / "state/current.json").exists() is False

            status, html = _request(base_url, "/review")
            assert status == 200
            assert 'id="blank-project-form"' in html
            assert "创建空白综述项目" in html
            assert 'pattern="[A-Za-z0-9][A-Za-z0-9._\\-]*"' in html
        finally:
            _stop_dashboard(server, thread)

        server, thread, base_url = _start_dashboard(review_root)
        try:
            status, projects = _request(base_url, "/api/projects")
            assert status == 200
            row = next(item for item in projects if item["project_id"] == PROJECT_ID)
            assert row["topic"] == "Synthetic visible-light chemistry"
            assert row["selectable"] is True
        finally:
            _stop_dashboard(server, thread)


def test_public_blank_project_invalid_request_is_zero_write() -> None:
    with tempfile.TemporaryDirectory(prefix="public-e2e-blank-project-invalid-") as temporary_root:
        review_root = Path(temporary_root)
        (review_root / "synthetic.pdf").write_bytes(b"%PDF-1.4\n% fixture\n")
        before = _tree_bytes(review_root)

        server, thread, base_url = _start_dashboard(review_root)
        try:
            status, result = _request(
                base_url,
                "/api/projects",
                method="POST",
                payload={"project_id": PROJECT_ID},
            )
            assert status == 400
            assert result["ok"] is False
            assert result["error_code"] == "PROJECT_CREATE_REQUEST_INVALID"
            assert _tree_bytes(review_root) == before
        finally:
            _stop_dashboard(server, thread)
