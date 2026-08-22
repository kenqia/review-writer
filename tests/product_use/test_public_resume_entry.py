from __future__ import annotations

import hashlib
import json
import tempfile
import threading
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from view import serve_review_dashboard as dashboard
from review_writer.product_foundation import VersionContext
from review_writer.product_foundation.project_root import version_context_root


PROJECT_ID = "rel001-public-resume-synthetic"
CURRENT_VERSION_ID = "v1"
CURRENT_VERSION_TOKEN = "synthetic-current-token"
ARTIFACT_RELATIVE_PATH = "00_brief/review_state.json"


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_registered_project(review_root: Path) -> Path:
    project = review_root / PROJECT_ID
    sentinel = project / ARTIFACT_RELATIVE_PATH
    _write_json(
        sentinel,
        {
            "project_id": PROJECT_ID,
            "status": "in_progress",
            "current_stage": "drafting",
        },
    )
    VersionContext.create(
        {
            "artifact_refs": [
                {
                    "path": ARTIFACT_RELATIVE_PATH,
                    "sha256": hashlib.sha256(sentinel.read_bytes()).hexdigest(),
                }
            ],
            "currentness": "current",
            "version_token": CURRENT_VERSION_TOKEN,
        },
        project_id=PROJECT_ID,
        version_id=CURRENT_VERSION_ID,
        branch_id="main",
        branch_name="Main",
        project_root=project,
    )
    return project


def _resume_payload(project: Path, **overrides: Any) -> dict[str, Any]:
    context = VersionContext.load(project)
    state = context.state()
    current = context.view_version(state.current_version_id)
    payload = {
        "expected_revision": state.revision,
        "node_digest": current.snapshot_digest,
        "version_token": CURRENT_VERSION_TOKEN,
    }
    payload.update(overrides)
    return payload


def _resume_state_bytes(project: Path) -> bytes:
    return (version_context_root(project) / "current.json").read_bytes()


def _request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    body = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if payload is not None
        else None
    )
    headers = (
        {
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        }
        if body is not None
        else {}
    )
    request = Request(f"{base_url}{path}", data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raw = exc.read()
        try:
            payload_value: Any = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload_value = {"raw": raw.decode("utf-8", errors="replace")}
        return exc.code, payload_value


def _start_dashboard(
    review_root: Path,
) -> tuple[dashboard.ThreadingHTTPServer, threading.Thread, str]:
    dashboard.configure_runtime(review_root)
    server = dashboard.ThreadingHTTPServer(("127.0.0.1", 0), dashboard.DashboardHandler)
    thread = threading.Thread(
        target=server.serve_forever,
        name="rel001-public-resume-dashboard",
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


def test_public_resume_entry_is_exposed_for_registered_project() -> None:
    with tempfile.TemporaryDirectory(prefix="rel001-public-resume-") as temporary_root:
        review_root = Path(temporary_root)
        project = _write_registered_project(review_root)
        sentinel = project / "00_brief/review_state.json"
        current_before = _resume_state_bytes(project)
        sentinel_before = sentinel.read_bytes()
        resume_payload = _resume_payload(project)
        resume_payload.pop("node_digest")

        server, thread, base_url = _start_dashboard(review_root)
        try:
            status, projects = _request(base_url, "/api/projects")
            assert status == 200
            assert any(row.get("project_id") == PROJECT_ID for row in projects)

            status, result = _request(
                base_url,
                f"/api/project/{PROJECT_ID}/resume",
                method="POST",
                payload=resume_payload,
            )
            assert status == 200
            assert set(result) == {
                "result",
                "write_mode",
                "currentness",
                "version",
                "revision",
                "next_action",
            }
            assert result["result"] == "RESUMED"
            assert result["write_mode"] == "NONE"
            assert result["currentness"] == "current"
            assert result["version"]["version_id"] == CURRENT_VERSION_ID
            assert result["revision"] == 0
            assert result["next_action"] == {
                "project_id": PROJECT_ID,
                "route": "/review",
            }
            assert sentinel.read_bytes() == sentinel_before
            assert _resume_state_bytes(project) == current_before

            status, repeated = _request(
                base_url,
                f"/api/project/{PROJECT_ID}/resume",
                method="POST",
                payload=resume_payload,
            )
            assert status == 200
            assert repeated["result"] == "UNCHANGED"
            assert repeated["write_mode"] == "NONE"
            assert repeated["version"] == result["version"]
            assert repeated["revision"] == result["revision"]
            assert sentinel.read_bytes() == sentinel_before
            assert _resume_state_bytes(project) == current_before

            serialized = json.dumps(result, ensure_ascii=False)
            assert str(project) not in serialized
            assert "AGENT_RUNTIME_FAILED" not in serialized
        finally:
            _stop_dashboard(server, thread)


def test_public_resume_rejects_missing_invalid_and_corrupt_current_without_writes() -> None:
    with tempfile.TemporaryDirectory(prefix="rel001-public-resume-invalid-") as temporary_root:
        review_root = Path(temporary_root)
        project = _write_registered_project(review_root)
        current_path = version_context_root(project) / "current.json"
        valid_payload = _resume_payload(project)

        server, thread, base_url = _start_dashboard(review_root)
        try:
            invalid_before = _resume_state_bytes(project)
            status, result = _request(
                base_url,
                f"/api/project/{PROJECT_ID}/resume",
                method="POST",
                payload={"version_token": CURRENT_VERSION_TOKEN},
            )
            assert status == 400
            assert result["error_code"] == "RESUME_REQUEST_INVALID"
            assert _resume_state_bytes(project) == invalid_before

            current_path.unlink()
            assert not current_path.exists()
            status, result = _request(
                base_url,
                f"/api/project/{PROJECT_ID}/resume",
                method="POST",
                payload=valid_payload,
            )
            assert status == 404
            assert result["error_code"] == "VERSION_CONTEXT_MISSING"
            assert not current_path.exists()

            current_path.write_bytes(b"not-json")
            corrupt_before = current_path.read_bytes()
            status, result = _request(
                base_url,
                f"/api/project/{PROJECT_ID}/resume",
                method="POST",
                payload=valid_payload,
            )
            assert status == 422
            assert result["error_code"] == "VERSION_CONTEXT_INVALID"
            assert current_path.read_bytes() == corrupt_before
        finally:
            _stop_dashboard(server, thread)


def test_public_resume_fails_closed_for_stale_revision_digest_and_artifact() -> None:
    with tempfile.TemporaryDirectory(prefix="rel001-public-resume-stale-") as temporary_root:
        review_root = Path(temporary_root)
        project = _write_registered_project(review_root)
        sentinel = project / ARTIFACT_RELATIVE_PATH
        current_before = _resume_state_bytes(project)
        valid_payload = _resume_payload(project)

        server, thread, base_url = _start_dashboard(review_root)
        try:
            for payload in (
                {**valid_payload, "expected_revision": 99},
                {**valid_payload, "node_digest": "0" * 64},
                {**valid_payload, "version_token": "stale-token"},
            ):
                status, result = _request(
                    base_url,
                    f"/api/project/{PROJECT_ID}/resume",
                    method="POST",
                    payload=payload,
                )
                assert status == 409
                assert result["error_code"] == "VERSION_CONFLICT"
                assert _resume_state_bytes(project) == current_before

            sentinel.write_bytes(sentinel.read_bytes() + b"external stale mutation")
            status, result = _request(
                base_url,
                f"/api/project/{PROJECT_ID}/resume",
                method="POST",
                payload=valid_payload,
            )
            assert status == 409
            assert result["error_code"] == "VERSION_CONFLICT"
            assert _resume_state_bytes(project) == current_before
        finally:
            _stop_dashboard(server, thread)


def test_public_resume_cold_restart_rehydrates_same_authoritative_current() -> None:
    with tempfile.TemporaryDirectory(prefix="rel001-public-resume-restart-") as temporary_root:
        review_root = Path(temporary_root)
        project = _write_registered_project(review_root)
        payload = _resume_payload(project)
        current_before = _resume_state_bytes(project)

        server, thread, base_url = _start_dashboard(review_root)
        try:
            status, first = _request(
                base_url,
                f"/api/project/{PROJECT_ID}/resume",
                method="POST",
                payload=payload,
            )
            assert status == 200
            assert first["result"] == "RESUMED"
        finally:
            _stop_dashboard(server, thread)

        server, thread, base_url = _start_dashboard(review_root)
        try:
            status, after_restart = _request(
                base_url,
                f"/api/project/{PROJECT_ID}/resume",
                method="POST",
                payload=payload,
            )
            assert status == 200
            assert after_restart["result"] == "RESUMED"
            assert after_restart["write_mode"] == "NONE"
            assert after_restart["version"] == first["version"]
            assert after_restart["revision"] == first["revision"]
            assert _resume_state_bytes(project) == current_before
        finally:
            _stop_dashboard(server, thread)
