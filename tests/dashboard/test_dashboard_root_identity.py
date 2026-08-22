from __future__ import annotations

import http.client
import json
import threading
from pathlib import Path

import pytest

from view import serve_review_dashboard as dashboard


def _start_server(review_root: Path) -> tuple[dashboard.ThreadingHTTPServer, threading.Thread]:
    server = dashboard.ThreadingHTTPServer(("127.0.0.1", 0), dashboard.DashboardHandler)
    thread = threading.Thread(target=server.serve_forever, name="dashboard-identity-test", daemon=True)
    thread.start()
    return server, thread


def _stop_server(server: dashboard.ThreadingHTTPServer, thread: threading.Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=10)
    assert not thread.is_alive()


def _request(
    server: dashboard.ThreadingHTTPServer,
    method: str,
    path: str,
    body: bytes = b"",
) -> tuple[int, bytes, dict[str, str]]:
    host, port = server.server_address
    connection = http.client.HTTPConnection(host, port, timeout=10)
    try:
        connection.request(
            method,
            path,
            body=body,
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
            },
        )
        response = connection.getresponse()
        return response.status, response.read(), dict(response.getheaders())
    finally:
        connection.close()


def test_foreign_checkout_is_readable_and_downloadable_but_all_mutations_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    foreign_checkout = tmp_path / "foreign-checkout"
    (foreign_checkout / ".git").mkdir(parents=True)
    review_root = foreign_checkout / "projects"
    review_root.mkdir()
    current_path = review_root / "state" / "current.json"
    current_path.parent.mkdir()
    current_bytes = b"current-sentinel-v1"
    current_path.write_bytes(current_bytes)

    context = dashboard.configure_runtime(review_root)
    assert context.mode == dashboard.HISTORICAL_READ_ONLY
    assert context.checkout_root == foreign_checkout.resolve()

    # Static serving must use the configured root captured above, not __file__.
    monkeypatch.setattr(dashboard, "__file__", str(tmp_path / "other-checkout" / "serve.py"))
    server, thread = _start_server(review_root)
    try:
        status, body, _ = _request(server, "GET", "/review")
        assert status == 200
        assert body

        status, body, _ = _request(server, "GET", "/assets/dashboard/review.html")
        assert status == 200
        assert body

        status, body, headers = _request(server, "GET", "/file?path=state/current.json")
        assert status == 200
        assert body == current_bytes

        mutation_routes = {
            "PUT": "/api/project/foreign/draft",
            "PATCH": "/api/project/foreign/chemical-paper/field",
            "POST": "/api/project/foreign/export-docx",
        }
        for method, route in mutation_routes.items():
            status, body, headers = _request(server, method, route, b"body-must-not-be-read")
            assert status == 403
            assert headers["Content-Type"].startswith("application/json")
            assert json.loads(body) == {
                "ok": False,
                "error_code": "HISTORICAL_READ_ONLY",
                "message": "historical review root is read-only",
            }
            assert current_path.read_bytes() == current_bytes

        status, _, _ = _request(server, "DELETE", "/api/project/foreign/draft", b"delete")
        assert status == 501
        assert current_path.read_bytes() == current_bytes
    finally:
        _stop_server(server, thread)


@pytest.mark.parametrize("mismatch_kind", ["code", "assets"])
def test_code_assets_and_imported_delivery_checkout_mismatch_fails_closed(
    tmp_path: Path, mismatch_kind: str
) -> None:
    foreign_code = tmp_path / "foreign-code"
    foreign_assets = foreign_code / "view" / "assets"
    foreign_assets.mkdir(parents=True)
    detached_root = tmp_path / "detached-review-root"
    detached_root.mkdir()

    code_root = foreign_code if mismatch_kind == "code" else dashboard.REPO_ROOT
    asset_root = foreign_assets if mismatch_kind == "assets" else dashboard.REPO_ROOT / "view" / "assets"
    with pytest.raises(RuntimeError) as error:
        dashboard.configure_runtime(
            detached_root,
            code_root=code_root,
            asset_root=asset_root,
        )
    assert getattr(error.value, "code", None) == "DASHBOARD_RUNTIME_IDENTITY_INVALID"


def test_same_checkout_and_detached_roots_remain_writable(tmp_path: Path) -> None:
    same_checkout = dashboard.configure_runtime(dashboard.REPO_ROOT)
    assert same_checkout.mode == dashboard.WRITABLE
    assert same_checkout.checkout_root == same_checkout.code_root

    detached_root = tmp_path / "detached-review-root"
    detached_root.mkdir()
    detached = dashboard.configure_runtime(detached_root)
    assert detached.mode == dashboard.WRITABLE
    assert detached.checkout_root is None
