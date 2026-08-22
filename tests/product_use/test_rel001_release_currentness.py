from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from review_writer.project.paper_evidence import paper_evidence_state
from tests.product_use.test_prod006_source_to_release import (
    EVIDENCE_ID,
    PROJECT_ID,
    _assert_release_payload,
    _assert_views,
    _build_project,
    _http_json,
    _post_release,
    _sha256_bytes,
    _start_dashboard,
    _stop_dashboard,
)


def _raw_request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    body: bytes = b"",
    content_type: str | None = None,
) -> tuple[int, bytes, dict[str, str]]:
    headers: dict[str, str] = {}
    if body:
        headers["Content-Length"] = str(len(body))
    if content_type is not None:
        headers["Content-Type"] = content_type
    request = Request(
        f"{base_url}{path}",
        data=body if body else None,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, response.read(), dict(response.headers.items())
    except HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers.items())


def _json_request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any], dict[str, str]]:
    body = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if payload is not None
        else b""
    )
    status, raw_body, headers = _raw_request(
        base_url,
        path,
        method=method,
        body=body,
        content_type="application/json" if payload is not None else None,
    )
    try:
        decoded = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AssertionError(f"{method} {path} did not return JSON: {raw_body!r}") from exc
    assert isinstance(decoded, dict), f"{method} {path} returned a non-object JSON payload"
    return status, decoded, headers


def _release_download_path() -> str:
    relative = f"{PROJECT_ID}/05_release/self_reviewed_draft.docx"
    return f"/file?path={quote(relative, safe='')}"


def _release_bytes_and_hashes(
    project: Path, payload: dict[str, Any]
) -> tuple[dict[str, bytes], dict[str, str]]:
    release_bytes = _assert_release_payload(project, payload)
    release_hashes = {
        relative: _sha256_bytes(value) for relative, value in release_bytes.items()
    }
    return release_bytes, release_hashes


def _assert_evidence_boundary(
    project: Path,
    *release_payloads: dict[str, Any],
) -> None:
    evidence = paper_evidence_state(project)
    row = next(row for row in evidence["rows"] if row["evidence_id"] == EVIDENCE_ID)
    assert set(row["risk_classes"]) == {"AI_PROVISIONAL", "GAP", "NON_COMPARABLE"}

    # The current delivery/evidence schema has no explicit promotion or B2
    # field.  Keep this check fail-closed: no payload may claim promotion or a
    # B2 pass while those authority seams are absent.
    for value in (row, *release_payloads):
        assert value.get("promotion", "NONE") == "NONE"
        for key in ("b2", "B2", "b2_status", "B2_STATUS"):
            assert value.get(key) not in {True, "PASS", "PASSED", "GREEN"}


def test_rel001_release_currentness_is_fail_closed_and_stable_after_reload() -> None:
    with tempfile.TemporaryDirectory(prefix="rel001-product-use-") as temporary_root:
        review_root = Path(temporary_root)
        project = _build_project(review_root)
        authoritative_path = project / "04_manuscript/manuscript.md"
        first_authoritative_bytes = authoritative_path.read_bytes()

        server, thread, base_url = _start_dashboard(review_root)
        try:
            _assert_views(base_url, project)

            status, first_result = _post_release(base_url)
            assert status == 200
            assert first_result["ok"] is True
            first_release_bytes, first_release_hashes = _release_bytes_and_hashes(
                project, first_result
            )
            first_snapshot = json.loads(
                (project / "05_release/release_snapshot.json").read_text(encoding="utf-8")
            )
            first_quality = json.loads(
                (project / "05_release/quality_report.json").read_text(encoding="utf-8")
            )
            _assert_evidence_boundary(project, first_result, first_snapshot, first_quality)
            _assert_views(base_url, project, release_current=True)

            download_status, download_bytes, _ = _raw_request(
                base_url, _release_download_path()
            )
            assert download_status == 200
            assert download_bytes == first_release_bytes[
                "05_release/self_reviewed_draft.docx"
            ]

            draft_status, draft_payload, _ = _json_request(
                base_url, f"/api/project/{PROJECT_ID}/draft"
            )
            assert draft_status == 200
            section = next(
                item
                for item in draft_payload["sections"]
                if item["section_id"] == "reported-result"
            )
            edited_body = section["body"].replace(
                "records a bounded outcome.", "records a bounded outcome!", 1
            )
            assert edited_body != section["body"]
            edit_status, edit_result, _ = _json_request(
                base_url,
                f"/api/project/{PROJECT_ID}/draft",
                method="PUT",
                payload={
                    "section_id": section["section_id"],
                    "edited_body": edited_body,
                    "reason": "Controlled currentness edit for REL-001.",
                    "version_token": section["version_token"],
                    "actor_type": "simulated_researcher_agent",
                    "actor_label": "rel001-product-use",
                },
            )
            assert edit_status == 200
            assert edit_result["project_id"] == PROJECT_ID
            assert edit_result["route"] == "evidence-to-release.v1"
            assert edit_result["status"] == "approved"
            assert authoritative_path.read_bytes() != first_authoritative_bytes

            final_status, stale_final, _ = _json_request(
                base_url, f"/api/project/{PROJECT_ID}/final"
            )
            assert final_status == 200
            assert stale_final["manuscript_source"] == "authoritative_manuscript"
            assert stale_final["release_status"] == "RELEASE_OUTDATED"
            assert stale_final["release_snapshot"] == {
                "exists": True,
                "matches_authoritative": False,
                "integrity_valid": False,
                "docx_exists": False,
            }

            stale_download_status, stale_download_body, _ = _raw_request(
                base_url, _release_download_path()
            )
            assert stale_download_status == 403
            assert b"release DOCX is outdated" in stale_download_body

            # A stale read must not rewrite any of the four previously current
            # release files or alter their recorded bytes/hashes.
            assert {
                relative: path.read_bytes()
                for relative, path in {
                    "05_release/self_reviewed_draft.md": project
                    / "05_release/self_reviewed_draft.md",
                    "05_release/self_reviewed_draft.docx": project
                    / "05_release/self_reviewed_draft.docx",
                    "05_release/release_snapshot.json": project
                    / "05_release/release_snapshot.json",
                    "05_release/quality_report.json": project
                    / "05_release/quality_report.json",
                }.items()
            } == first_release_bytes
            assert {
                relative: _sha256_bytes(value)
                for relative, value in first_release_bytes.items()
            } == first_release_hashes

            status, second_result = _post_release(base_url)
            assert status == 200
            assert second_result["ok"] is True
            second_release_bytes, second_release_hashes = _release_bytes_and_hashes(
                project, second_result
            )
            second_snapshot = json.loads(
                (project / "05_release/release_snapshot.json").read_text(encoding="utf-8")
            )
            assert second_snapshot["manuscript_sha256"] != first_snapshot["manuscript_sha256"]
            assert second_release_bytes["05_release/self_reviewed_draft.md"] != first_release_bytes[
                "05_release/self_reviewed_draft.md"
            ]
            _assert_evidence_boundary(project, second_result)
            _assert_views(base_url, project, release_current=True)
        finally:
            _stop_dashboard(server, thread)

        # Reload the same root in a fresh owned Dashboard process.  Persisted
        # bytes, hashes, and currentness must remain identical.
        server, thread, base_url = _start_dashboard(review_root)
        try:
            final_status, current_final, _ = _json_request(
                base_url, f"/api/project/{PROJECT_ID}/final"
            )
            assert final_status == 200
            assert current_final["manuscript_source"] == "release_snapshot"
            assert current_final["release_snapshot"] == {
                "exists": True,
                "matches_authoritative": True,
                "integrity_valid": True,
                "docx_exists": True,
            }
            reloaded_bytes, reloaded_hashes = _release_bytes_and_hashes(
                project, {"release_level": current_final["release_status"]}
            )
            assert reloaded_bytes == second_release_bytes
            assert reloaded_hashes == second_release_hashes
            assert reloaded_bytes["05_release/self_reviewed_draft.docx"] == _raw_request(
                base_url, _release_download_path()
            )[1]
            _assert_evidence_boundary(project, current_final)
        finally:
            _stop_dashboard(server, thread)


def test_rel001_historical_export_is_read_only_and_preserves_current_pointer() -> None:
    with tempfile.TemporaryDirectory(prefix="rel001-historical-") as temporary_root:
        temporary_path = Path(temporary_root)
        foreign_checkout = temporary_path / "foreign-checkout"
        (foreign_checkout / ".git").mkdir(parents=True)
        review_root = foreign_checkout / "projects"
        review_root.mkdir()
        current_path = review_root / "state/current.json"
        current_path.parent.mkdir()
        current_bytes = b"rel001-current-sentinel-v1"
        current_path.write_bytes(current_bytes)
        _build_project(review_root)

        server, thread, base_url = _start_dashboard(review_root)
        try:
            exact_body = b'{"release_level":"SELF_REVIEWED_DRAFT"}'
            status, body, headers = _raw_request(
                base_url,
                f"/api/project/{PROJECT_ID}/export-docx",
                method="POST",
                body=exact_body,
                content_type="application/json",
            )
            assert status == 403
            assert headers["Content-Type"].startswith("application/json")
            assert json.loads(body.decode("utf-8")) == {
                "ok": False,
                "error_code": "HISTORICAL_READ_ONLY",
                "message": "historical review root is read-only",
            }
            assert current_path.read_bytes() == current_bytes
        finally:
            _stop_dashboard(server, thread)
