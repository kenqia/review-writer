from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest

import review_writer.agent.fresh_bootstrap as fresh_bootstrap
from review_writer.agent.fresh_bootstrap import FreshAgentBootstrap
from review_writer.product_foundation import VersionContext


REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "scripts" / "run_vertical_review.py"


def _dashboard_processes(review_root: Path) -> list[str]:
    result = subprocess.run(
        ["ps", "-eo", "pid=,args="],
        capture_output=True,
        text=True,
        check=True,
    )
    marker = f"serve_review_dashboard.py --review-root {review_root}"
    return [line.strip() for line in result.stdout.splitlines() if marker in line]


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


def test_fresh_agent_bootstrap_creates_canonical_project_then_stops_for_source_role() -> None:
    with tempfile.TemporaryDirectory(prefix="fresh-agent-bootstrap-") as temporary_root:
        root = Path(temporary_root)
        authorized_pdfs = root / "authorized-pdfs"
        authorized_pdfs.mkdir()
        (authorized_pdfs / "selected-paper.pdf").write_bytes(_minimal_pdf())
        project = root / "fresh-agent-project"

        result = FreshAgentBootstrap(project).start(
            topic="Evidence-constrained photochemistry review",
            authorized_pdf_folder=authorized_pdfs,
        )
        try:
            assert result["status"] == "HUMAN_ACTION_REQUIRED"
            assert result["reason_code"] == "SOURCE_ROLE_HUMAN_ACTION_REQUIRED"
            assert result["project_id"] == project.name
            assert result["next_action"]["route"] == "/review"
            assert result["dashboard_url"].startswith("http://127.0.0.1:")

            archive_path = project / "00_sources/manual_upload/inbox/source_bundle.zip"
            assert archive_path.is_file()
            with zipfile.ZipFile(archive_path) as archive:
                assert archive.namelist() == ["selected-paper.pdf"]

            context = VersionContext.load(project)
            state = context.state()
            current = context.view_version(state.current_version_id)
            bootstrap = current.snapshot["agent_bootstrap"]
            assert [row["tool"] for row in bootstrap["tool_trace"]] == [
                "source_archive_preflight",
                "start_dashboard",
                "initialize_review",
                "confirm_review_brief",
            ]
            assert bootstrap["source_archive"]["member"]["safe_locator"].endswith(
                "#MEMBER-0001"
            )

            with urlopen(f"{result['dashboard_url']}/api/projects", timeout=10) as response:
                projects = json.loads(response.read().decode("utf-8"))
            assert any(row["project_id"] == project.name for row in projects)
        finally:
            FreshAgentBootstrap.stop_owned_dashboard(int(result["dashboard_pid"]))


def test_dashboard_start_failure_does_not_publish_partial_fresh_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authorized_pdfs = tmp_path / "authorized-pdfs"
    authorized_pdfs.mkdir()
    (authorized_pdfs / "selected-paper.pdf").write_bytes(_minimal_pdf())
    project = tmp_path / "fresh-agent-project"

    def fail_dashboard(_: Path) -> tuple[str, int]:
        raise fresh_bootstrap.FreshAgentBootstrapError("DASHBOARD_START_FAILED")

    monkeypatch.setattr(fresh_bootstrap, "_start_dashboard", fail_dashboard)

    with pytest.raises(fresh_bootstrap.FreshAgentBootstrapError) as error:
        FreshAgentBootstrap(project).start(
            topic="Evidence-constrained photochemistry review",
            authorized_pdf_folder=authorized_pdfs,
        )

    assert error.value.code == "DASHBOARD_START_FAILED"
    assert not project.exists(), "a failed fresh bootstrap must not leave canonical bytes"


def test_source_preflight_failure_does_not_publish_fresh_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authorized_pdfs = tmp_path / "authorized-pdfs"
    authorized_pdfs.mkdir()
    (authorized_pdfs / "selected-paper.pdf").write_bytes(_minimal_pdf())
    project = tmp_path / "fresh-agent-project"

    def fail_preflight(*_: object, **__: object) -> dict[str, object]:
        raise fresh_bootstrap.SourceArchivePreflightError(
            "SOURCE_ARCHIVE_INVALID", "injected preflight failure"
        )

    monkeypatch.setattr(fresh_bootstrap, "_source_archive_preflight", fail_preflight)

    with pytest.raises(fresh_bootstrap.FreshAgentBootstrapError) as error:
        FreshAgentBootstrap(project).start(
            topic="Evidence-constrained photochemistry review",
            authorized_pdf_folder=authorized_pdfs,
        )

    assert error.value.code == "SOURCE_ARCHIVE_INVALID"
    assert not project.exists(), "a failed source preflight must not leave canonical bytes"
    assert not list(tmp_path.glob(".fresh-agent-source-*.zip"))


def test_dashboard_child_early_exit_is_classified_and_zero_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authorized_pdfs = tmp_path / "authorized-pdfs"
    authorized_pdfs.mkdir()
    (authorized_pdfs / "selected-paper.pdf").write_bytes(_minimal_pdf())
    project = tmp_path / "fresh-agent-project"
    child_root = tmp_path / "child-checkout"
    (child_root / "view").mkdir(parents=True)
    (child_root / "view" / "serve_review_dashboard.py").write_text(
        "raise SystemExit(17)\n", encoding="utf-8"
    )
    monkeypatch.setattr(fresh_bootstrap, "_REPO_ROOT", child_root)

    with pytest.raises(fresh_bootstrap.FreshAgentBootstrapError) as error:
        FreshAgentBootstrap(project).start(
            topic="Evidence-constrained photochemistry review",
            authorized_pdf_folder=authorized_pdfs,
        )

    assert error.value.code == "DASHBOARD_START_FAILED"
    assert error.value.runtime_diagnostic == "CHILD_EARLY_EXIT"
    assert error.value.write_mode == "NONE"
    assert not project.exists()
    assert not _dashboard_processes(project.parent)


def test_dashboard_health_timeout_is_classified_and_zero_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authorized_pdfs = tmp_path / "authorized-pdfs"
    authorized_pdfs.mkdir()
    (authorized_pdfs / "selected-paper.pdf").write_bytes(_minimal_pdf())
    project = tmp_path / "fresh-agent-project"
    monkeypatch.setattr(fresh_bootstrap, "_DASHBOARD_START_TIMEOUT_SECONDS", 0.2)

    def never_ready(*_: object, **__: object) -> object:
        raise URLError("injected health unreachable")

    monkeypatch.setattr(fresh_bootstrap, "urlopen", never_ready)

    with pytest.raises(fresh_bootstrap.FreshAgentBootstrapError) as error:
        FreshAgentBootstrap(project).start(
            topic="Evidence-constrained photochemistry review",
            authorized_pdf_folder=authorized_pdfs,
        )

    assert error.value.code == "DASHBOARD_START_FAILED"
    assert error.value.runtime_diagnostic == "CHILD_HEALTH_TIMEOUT"
    assert error.value.write_mode == "NONE"
    assert not project.exists()
    assert not _dashboard_processes(project.parent)


def test_dashboard_port_error_is_classified_from_child_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    review_root = tmp_path / "review-root"
    review_root.mkdir()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    occupied_port = int(listener.getsockname()[1])
    monkeypatch.setattr(fresh_bootstrap, "_open_port", lambda: occupied_port)
    try:
        with pytest.raises(fresh_bootstrap.FreshAgentBootstrapError) as error:
            fresh_bootstrap._start_dashboard(review_root)
    finally:
        listener.close()

    assert error.value.code == "DASHBOARD_START_FAILED"
    assert error.value.runtime_diagnostic == "PYTHON_PORT_ERROR"
    assert error.value.write_mode == "NONE"
    assert not _dashboard_processes(review_root)


@pytest.mark.parametrize(
    ("child_source", "expected_diagnostic"),
    [
        ("raise ModuleNotFoundError('injected import failure')\n", "PYTHON_IMPORT_ERROR"),
        ("raise PermissionError('injected permission failure')\n", "PYTHON_PERMISSION_ERROR"),
    ],
)
def test_dashboard_python_runtime_errors_are_classified_from_child_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    child_source: str,
    expected_diagnostic: str,
) -> None:
    review_root = tmp_path / "review-root"
    review_root.mkdir()
    child_root = tmp_path / "child-checkout"
    (child_root / "view").mkdir(parents=True)
    (child_root / "view" / "serve_review_dashboard.py").write_text(
        child_source, encoding="utf-8"
    )
    monkeypatch.setattr(fresh_bootstrap, "_REPO_ROOT", child_root)

    with pytest.raises(fresh_bootstrap.FreshAgentBootstrapError) as error:
        fresh_bootstrap._start_dashboard(review_root)

    assert error.value.code == "DASHBOARD_START_FAILED"
    assert error.value.runtime_diagnostic == expected_diagnostic
    assert error.value.write_mode == "NONE"
    assert not _dashboard_processes(review_root)


def test_preexisting_nonempty_project_is_byte_unchanged(tmp_path: Path) -> None:
    project = tmp_path / "fresh-agent-project"
    sentinel = project / "user-owned.txt"
    sentinel.parent.mkdir()
    sentinel.write_bytes(b"user-owned-v1")
    before = sentinel.read_bytes()

    with pytest.raises(fresh_bootstrap.FreshAgentBootstrapError) as error:
        FreshAgentBootstrap(project)

    assert error.value.code == "PROJECT_ROOT_NOT_EMPTY"
    assert sentinel.read_bytes() == before
    assert list(project.iterdir()) == [sentinel]


def test_existing_empty_project_is_restored_to_empty_preimage_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authorized_pdfs = tmp_path / "authorized-pdfs"
    authorized_pdfs.mkdir()
    (authorized_pdfs / "selected-paper.pdf").write_bytes(_minimal_pdf())
    project = tmp_path / "fresh-agent-project"
    project.mkdir()

    def fail_dashboard(_: Path) -> tuple[str, int]:
        raise fresh_bootstrap.FreshAgentBootstrapError("DASHBOARD_START_FAILED")

    monkeypatch.setattr(fresh_bootstrap, "_start_dashboard", fail_dashboard)

    with pytest.raises(fresh_bootstrap.FreshAgentBootstrapError) as error:
        FreshAgentBootstrap(project).start(
            topic="Evidence-constrained photochemistry review",
            authorized_pdf_folder=authorized_pdfs,
        )

    assert error.value.write_mode == "NONE"
    assert project.is_dir()
    assert list(project.iterdir()) == []


def test_corrupt_pdf_is_rejected_with_zero_write(tmp_path: Path) -> None:
    authorized_pdfs = tmp_path / "authorized-pdfs"
    authorized_pdfs.mkdir()
    (authorized_pdfs / "corrupt.pdf").write_bytes(b"%PDF-1.4\nnot-a-pdf")
    project = tmp_path / "fresh-agent-project"

    with pytest.raises(fresh_bootstrap.FreshAgentBootstrapError) as error:
        FreshAgentBootstrap(project).start(
            topic="Evidence-constrained photochemistry review",
            authorized_pdf_folder=authorized_pdfs,
        )

    assert error.value.code == "SOURCE_ARCHIVE_PDF_INVALID"
    assert error.value.write_mode == "NONE"
    assert not project.exists()
    assert not list(tmp_path.glob(".fresh-agent-source-*.zip"))


def test_version_conflict_failure_rolls_back_fresh_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authorized_pdfs = tmp_path / "authorized-pdfs"
    authorized_pdfs.mkdir()
    (authorized_pdfs / "selected-paper.pdf").write_bytes(_minimal_pdf())
    project = tmp_path / "fresh-agent-project"

    def fail_publish(*_: object, **__: object) -> object:
        raise fresh_bootstrap.ProductFoundationError("injected version conflict")

    monkeypatch.setattr(
        fresh_bootstrap.VersionContext,
        "publish_active_head",
        fail_publish,
    )

    with pytest.raises(fresh_bootstrap.FreshAgentBootstrapError) as error:
        FreshAgentBootstrap(project).start(
            topic="Evidence-constrained photochemistry review",
            authorized_pdf_folder=authorized_pdfs,
        )

    assert error.value.code == "BOOTSTRAP_VERSION_CONTEXT_FAILED"
    assert error.value.write_mode == "NONE"
    assert not project.exists()
    assert not _dashboard_processes(project.parent)


def test_unsafe_rollback_reports_partial_write_mode_with_changed_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authorized_pdfs = tmp_path / "authorized-pdfs"
    authorized_pdfs.mkdir()
    (authorized_pdfs / "selected-paper.pdf").write_bytes(_minimal_pdf())
    project = tmp_path / "fresh-agent-project"

    def fail_publish(*_: object, **__: object) -> object:
        (project / "concurrent-user-byte").write_bytes(b"user-write")
        raise fresh_bootstrap.ProductFoundationError("injected version conflict")

    monkeypatch.setattr(
        fresh_bootstrap.VersionContext,
        "publish_active_head",
        fail_publish,
    )

    with pytest.raises(fresh_bootstrap.FreshAgentBootstrapError) as error:
        FreshAgentBootstrap(project).start(
            topic="Evidence-constrained photochemistry review",
            authorized_pdf_folder=authorized_pdfs,
        )

    assert error.value.code == "BOOTSTRAP_ROLLBACK_FAILED"
    assert error.value.write_mode == "PARTIAL"
    assert (project / "concurrent-user-byte").read_bytes() == b"user-write"
    assert not _dashboard_processes(project.parent)


def test_cli_corrupt_pdf_reports_true_zero_write_mode(tmp_path: Path) -> None:
    authorized_pdfs = tmp_path / "authorized-pdfs"
    authorized_pdfs.mkdir()
    (authorized_pdfs / "corrupt.pdf").write_bytes(b"%PDF-1.4\nnot-a-pdf")
    project = tmp_path / "fresh-agent-project"
    result = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "agent-bootstrap",
            "--project",
            str(project),
            "--topic",
            "Evidence-constrained photochemistry review",
            "--authorized-pdf-folder",
            str(authorized_pdfs),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    payload = json.loads(result.stderr)
    assert payload["error_code"] == "SOURCE_ARCHIVE_PDF_INVALID"
    assert payload["write_mode"] == "NONE"
    assert not project.exists()


def test_agent_bootstrap_cli_keeps_its_owned_dashboard_available_after_exit() -> None:
    with tempfile.TemporaryDirectory(prefix="fresh-agent-bootstrap-cli-") as temporary_root:
        root = Path(temporary_root)
        authorized_pdfs = root / "authorized-pdfs"
        authorized_pdfs.mkdir()
        (authorized_pdfs / "selected-paper.pdf").write_bytes(_minimal_pdf())
        result = subprocess.run(
            [
                sys.executable,
                str(CLI),
                "agent-bootstrap",
                "--project",
                str(root / "fresh-agent-project"),
                "--topic",
                "Evidence-constrained photochemistry review",
                "--authorized-pdf-folder",
                str(authorized_pdfs),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        pid = int(payload["dashboard_pid"])
        try:
            assert os.getsid(pid) == pid
            with urlopen(f"{payload['dashboard_url']}/api/projects", timeout=5) as response:
                assert response.status == 200
        finally:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            for _ in range(40):
                try:
                    with urlopen(f"{payload['dashboard_url']}/api/projects", timeout=0.1):
                        time.sleep(0.05)
                except (OSError, URLError):
                    break
