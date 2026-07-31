from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from review_writer.project.chemical_paper import import_chemical_paper
from review_writer.project.source_truth import canonical_digest
from test_chemical_paper_import import (
    ACTOR,
    PDF_SHA,
    replace_source_pdf_binding,
    source_truth_project,
    v2000,
    write_chemical_zip,
)
from test_dual_source import dual_project


def _http_request(review_root: Path, raw_request: bytes) -> tuple[int, dict[str, str], bytes]:
    from view import serve_review_dashboard as dashboard

    class FakeSocket:
        def __init__(self, incoming: bytes) -> None:
            self.input = io.BytesIO(incoming)
            self.output = io.BytesIO()

        def makefile(self, mode: str, *args, **kwargs):
            return self.input if "r" in mode else self.output

        def sendall(self, data: bytes) -> None:
            self.output.write(data)

        def close(self) -> None:
            pass

    dashboard.DashboardHandler.review_root = review_root
    socket = FakeSocket(raw_request)
    dashboard.DashboardHandler(socket, ("127.0.0.1", 0), object())
    head, body = socket.output.getvalue().split(b"\r\n\r\n", 1)
    lines = head.decode("iso-8859-1").split("\r\n")
    headers = dict(line.split(": ", 1) for line in lines[1:] if ": " in line)
    return int(lines[0].split()[1]), headers, body


def _post_zip(
    review_root: Path,
    archive: Path,
    *,
    project_id: str = "project",
    study_id: str = "study-1",
) -> tuple[int, dict[str, object]]:
    payload = archive.read_bytes()
    raw = (
        f"POST /api/project/{project_id}/chemical-paper/preflight?study_id={study_id} HTTP/1.1\r\n".encode(
            "ascii"
        )
        + b"Host: localhost\r\nContent-Type: application/zip\r\nContent-Length: "
        + str(len(payload)).encode("ascii")
        + b"\r\n\r\n"
        + payload
    )
    status, _, body = _http_request(review_root, raw)
    return status, json.loads(body)


def _post_json(
    review_root: Path,
    suffix: str,
    payload: object,
    *,
    project_id: str = "project",
) -> tuple[int, dict[str, object]]:
    encoded = json.dumps(payload).encode("utf-8")
    raw = (
        f"POST /api/project/{project_id}/{suffix} HTTP/1.1\r\n".encode("ascii")
        + b"Host: localhost\r\nContent-Type: application/json\r\nContent-Length: "
        + str(len(encoded)).encode("ascii")
        + b"\r\n\r\n"
        + encoded
    )
    status, _, body = _http_request(review_root, raw)
    return status, json.loads(body)


def _put_json(review_root: Path, suffix: str, payload: object) -> tuple[int, dict[str, object]]:
    encoded = json.dumps(payload).encode("utf-8")
    raw = (
        f"PUT /api/project/project/{suffix} HTTP/1.1\r\n".encode("ascii")
        + b"Host: localhost\r\nContent-Type: application/json\r\nContent-Length: "
        + str(len(encoded)).encode("ascii")
        + b"\r\n\r\n"
        + encoded
    )
    status, _, body = _http_request(review_root, raw)
    return status, json.loads(body)


def _authoritative_snapshot(project: Path) -> dict[str, bytes]:
    return {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
        and ".dual-parse-staging" not in path.relative_to(project).parts
    }


def test_preflight_writes_no_authoritative_state_and_returns_safe_projection(
    tmp_path: Path,
) -> None:
    review_root = tmp_path / "review-root"
    project = source_truth_project(review_root / "review-projects")
    archive = write_chemical_zip(tmp_path / "chemical.zip")
    before = _authoritative_snapshot(project)

    status, body = _post_zip(review_root, archive)

    assert status == 200
    assert body["status"] == "ready_for_confirmation"
    assert body["study_id"] == "study-1"
    assert body["page_count"] == 2
    assert body["molecule_count"] == 2
    assert body["reaction_data_status"] == "unavailable_not_provided"
    assert body["preflight_token"].startswith("cp-preflight-v1.")
    assert _authoritative_snapshot(project) == before
    encoded = json.dumps(body, sort_keys=True)
    for forbidden in (
        PDF_SHA,
        str(project),
        "source_pdf_sha256",
        "archive_sha256",
        "mol_block",
        "entry_inventory",
    ):
        assert forbidden not in encoded


def test_post_confirm_http_projects_bound_import_as_researcher_review_not_current(
    tmp_path: Path,
) -> None:
    review_root = tmp_path / "review-root"
    project = dual_project(review_root, chemical=False)
    archive = write_chemical_zip(
        tmp_path / "chemical.zip",
        pages=1,
        molecules=[
            {
                "mol_id": "mol-a",
                "page_idx": 0,
                "bbox_normalized": [0.1, 0.2, 0.3, 0.4],
                "smiles_expanded": "",
                "smiles_unexpanded": "",
                "mol_idt": "",
                "mol_block": v2000(),
            }
        ],
    )
    status, preflight = _post_zip(
        review_root,
        archive,
        project_id=project.name,
        study_id="scholarly-a",
    )
    assert status == 200

    status, confirmed = _post_json(
        review_root,
        "chemical-paper/confirm",
        {
            "study_id": "scholarly-a",
            "preflight_token": preflight["preflight_token"],
            "actor_type": "simulated_researcher_agent",
            "actor_label": "simulated_researcher",
        },
        project_id=project.name,
    )
    assert status == 200
    assert confirmed == {"status": "imported", "study_id": "scholarly-a"}

    status, _, body = _http_request(
        review_root,
        (
            f"GET /api/project/{project.name}/dual-parse HTTP/1.1\r\n"
            "Host: localhost\r\n\r\n"
        ).encode("ascii"),
    )

    assert status == 200
    payload = json.loads(body)
    assert payload["summary"] == {
        "core_studies": 1,
        "pdf_verified": 1,
        "generic_current": 1,
        "chemical_bound": 1,
        "chemical_current": 0,
        "reaction_data_status": "unavailable_not_provided",
    }
    row = payload["studies"][0]
    assert row["pdf_status"] == "verified"
    assert row["generic_parse_status"] == "current"
    assert row["chemical_import_status"] == "needs_review"
    assert row["completion_status"] == "blocked"
    assert row["reconciliation_status"] == "blocked"
    assert row["paper_evidence_status"] == "blocked"
    assert row["page_count"] == 1
    assert row["molecule_count"] == 1
    assert row["backend"] == "pipeline"
    assert row["version"] == "3.4.4"
    assert isinstance(row["imported_at"], str) and row["imported_at"]
    assert row["reaction_data_status"] == "unavailable_not_provided"
    assert len(payload["completion_queue"]) == 3

    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    for forbidden in (
        "source_pdf_sha256",
        "archive_sha256",
        "binding_digest",
        "state_digest",
        "mol_block",
        "raw_json",
        "entry_inventory",
        "internal_release",
        str(project),
    ):
        assert forbidden not in encoded


def test_first_smiles_completion_locator_serves_the_bound_original_pdf_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from view import serve_review_dashboard as dashboard

    review_root = tmp_path / "review-root"
    project = dual_project(review_root, chemical=False)
    archive = write_chemical_zip(
        tmp_path / "chemical.zip",
        pages=1,
        molecules=[
            {
                "mol_id": "mol-a",
                "page_idx": 0,
                "bbox_normalized": [0.1, 0.2, 0.3, 0.4],
                "smiles_expanded": "",
                "smiles_unexpanded": "",
                "mol_idt": "",
                "mol_block": v2000(),
            }
        ],
    )
    status, preflight = _post_zip(
        review_root,
        archive,
        project_id=project.name,
        study_id="scholarly-a",
    )
    assert status == 200
    status, _ = _post_json(
        review_root,
        "chemical-paper/confirm",
        {
            "study_id": "scholarly-a",
            "preflight_token": preflight["preflight_token"],
            "actor_type": "simulated_researcher_agent",
            "actor_label": "simulated_researcher",
        },
        project_id=project.name,
    )
    assert status == 200

    status, _, body = _http_request(
        review_root,
        (
            f"GET /api/project/{project.name}/dual-parse HTTP/1.1\r\n"
            "Host: localhost\r\n\r\n"
        ).encode("ascii"),
    )
    assert status == 200
    projection = json.loads(body)
    item = next(
        row
        for row in projection["completion_queue"]
        if row["field"] == "smiles_expanded"
    )
    locator = item["pdf_page_url"]
    assert locator.startswith(
        f"/api/project/{project.name}/source/stud-a/pdf-page?page=1&binding=cpb1."
    )
    assert all(
        row["pdf_page_url"] == locator for row in projection["completion_queue"]
    )
    assert "/parse-quality/" not in json.dumps(projection, sort_keys=True)

    bound_pdf = project / "00_sources/papers/paper-a.pdf"
    rendered = b"\x89PNG\r\n\x1a\nbound-original-pdf-page"
    seen: list[tuple[Path, int]] = []

    def render(path: Path, page: int) -> bytes:
        seen.append((path, page))
        return rendered

    monkeypatch.setattr(dashboard, "render_pdf_page", render)
    status, headers, body = _http_request(
        review_root,
        f"GET {locator} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode("ascii"),
    )

    assert status == 200
    assert headers["Content-Type"] == "image/png"
    assert body == rendered
    assert seen == [(bound_pdf, 1)]


def test_chemical_locator_from_binding_a_never_serves_rebound_pdf_b(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from view import serve_review_dashboard as dashboard

    review_root = tmp_path / "review-root"
    project = source_truth_project(review_root / "review-projects")
    import_chemical_paper(
        project,
        "study-1",
        PDF_SHA,
        write_chemical_zip(tmp_path / "chemical.zip"),
        ACTOR,
    )
    status, _, body = _http_request(
        review_root,
        (
            f"GET /api/project/{project.name}/chemical-paper HTTP/1.1\r\n"
            "Host: localhost\r\n\r\n"
        ).encode("ascii"),
    )
    assert status == 200
    projection = json.loads(body)
    locator = projection["studies"][0]["molecules"][0]["pdf_page_url"]

    replace_source_pdf_binding(
        project,
        "study-1",
        b"%PDF-1.4\nbinding-b\n%%EOF\n",
    )
    rendered: list[tuple[Path, int]] = []

    def render(path: Path, page: int) -> bytes:
        rendered.append((path, page))
        return b"unexpected binding B"

    monkeypatch.setattr(dashboard, "render_pdf_page", render)
    status, _, _ = _http_request(
        review_root,
        f"GET {locator} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode("ascii"),
    )

    assert status == 404
    assert rendered == []


def test_dual_parse_route_returns_zero_locators_for_cross_study_source_collision(
    tmp_path: Path,
) -> None:
    review_root = tmp_path / "review-root"
    project = dual_project(review_root, chemical=False)
    bundle_path = project / "01_evidence/source_truth/scholarly-a/bundle.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    source = bundle["sources"][0]
    import_chemical_paper(
        project,
        "scholarly-a",
        source["pdf"]["sha256"],
        write_chemical_zip(
            tmp_path / "chemical.zip",
            pages=1,
            molecules=[
                {
                    "mol_id": "mol-a",
                    "page_idx": 0,
                    "bbox_normalized": [0.1, 0.2, 0.3, 0.4],
                    "smiles_expanded": "",
                    "smiles_unexpanded": "",
                    "mol_idt": "",
                    "mol_block": v2000(),
                }
            ],
        ),
        ACTOR,
    )
    second_body = {
        key: value for key, value in bundle.items() if key != "bundle_digest"
    }
    second_body["study_id"] = "scholarly-b"
    second_body["study_identity"] = {
        "doi": "10.1000/example-b",
        "title": "Example B",
    }
    second_path = project / "01_evidence/source_truth/scholarly-b/bundle.json"
    second_path.parent.mkdir(parents=True)
    second_path.write_text(
        json.dumps(
            {**second_body, "bundle_digest": canonical_digest(second_body)}
        ),
        encoding="utf-8",
    )
    receipt_path = project / "00_sources/acquisition_final_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["studies"].append({"study_id": "scholarly-b"})
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    status, _, body = _http_request(
        review_root,
        (
            f"GET /api/project/{project.name}/dual-parse HTTP/1.1\r\n"
            "Host: localhost\r\n\r\n"
        ).encode("ascii"),
    )

    payload = json.loads(body)
    assert status == 404
    assert payload["error_code"] == "PROJECT_INVALID"
    assert "pdf_page_url" not in json.dumps(payload, sort_keys=True)


def test_dual_parse_route_returns_zero_locators_for_orphan_source_collision(
    tmp_path: Path,
) -> None:
    review_root = tmp_path / "review-root"
    project = dual_project(review_root, chemical=False)
    bundle_path = project / "01_evidence/source_truth/scholarly-a/bundle.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    source = bundle["sources"][0]
    import_chemical_paper(
        project,
        "scholarly-a",
        source["pdf"]["sha256"],
        write_chemical_zip(
            tmp_path / "chemical.zip",
            pages=1,
            molecules=[
                {
                    "mol_id": "mol-a",
                    "page_idx": 0,
                    "bbox_normalized": [0.1, 0.2, 0.3, 0.4],
                    "smiles_expanded": "",
                    "smiles_unexpanded": "",
                    "mol_idt": "",
                    "mol_block": v2000(),
                }
            ],
        ),
        ACTOR,
    )
    orphan_body = {
        key: value for key, value in bundle.items() if key != "bundle_digest"
    }
    orphan_body["study_id"] = "orphan-study"
    orphan_body["study_identity"] = {
        "doi": "10.1000/orphan",
        "title": "Undeclared orphan fixture",
    }
    orphan_path = project / "01_evidence/source_truth/orphan-study/bundle.json"
    orphan_path.parent.mkdir(parents=True)
    orphan_path.write_text(
        json.dumps(
            {**orphan_body, "bundle_digest": canonical_digest(orphan_body)}
        ),
        encoding="utf-8",
    )

    receipt = json.loads(
        (project / "00_sources/acquisition_final_receipt.json").read_text(
            encoding="utf-8"
        )
    )
    assert [row["study_id"] for row in receipt["studies"]] == ["scholarly-a"]
    status, _, body = _http_request(
        review_root,
        (
            f"GET /api/project/{project.name}/dual-parse HTTP/1.1\r\n"
            "Host: localhost\r\n\r\n"
        ).encode("ascii"),
    )

    payload = json.loads(body)
    assert status == 404
    assert payload["error_code"] == "PROJECT_INVALID"
    assert "pdf_page_url" not in json.dumps(payload, sort_keys=True)


def test_confirm_revalidates_records_actor_and_rejects_second_confirm(
    tmp_path: Path,
) -> None:
    review_root = tmp_path / "review-root"
    project = source_truth_project(review_root / "review-projects")
    status, preflight = _post_zip(
        review_root, write_chemical_zip(tmp_path / "chemical.zip")
    )
    assert status == 200
    request = {
        "study_id": "study-1",
        "preflight_token": preflight["preflight_token"],
        "actor_type": "simulated_researcher_agent",
        "actor_label": "simulated_researcher",
    }

    status, body = _post_json(review_root, "chemical-paper/confirm", request)

    assert status == 200
    assert body == {"status": "imported", "study_id": "study-1"}
    state = json.loads(
        (project / "01_evidence/chemical_paper/study-1/state.json").read_text(
            encoding="utf-8"
        )
    )
    event = state["imports"][state["current_import_digest"]]
    assert event["actor"] == {
        "actor_type": "simulated_researcher_agent",
        "actor_label": "simulated_researcher",
    }

    before = _authoritative_snapshot(project)
    status, body = _post_json(review_root, "chemical-paper/confirm", request)
    assert status == 409
    assert body["error_code"] == "PREFLIGHT_ALREADY_CONFIRMED"
    assert _authoritative_snapshot(project) == before


def test_confirm_never_reports_failure_after_authoritative_import_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from review_writer.delivery import dual_parse_release as release

    review_root = tmp_path / "review-root"
    project = source_truth_project(review_root / "review-projects")
    status, preflight = _post_zip(
        review_root, write_chemical_zip(tmp_path / "chemical.zip")
    )
    assert status == 200
    real_atomic_bytes = release._atomic_bytes

    def fail_consumed_marker(path: Path, payload: bytes) -> None:
        if path.name.endswith(".consumed.json"):
            raise release.DualParseReleaseError("PREFLIGHT_STAGING_FAILED")
        real_atomic_bytes(path, payload)

    monkeypatch.setattr(release, "_atomic_bytes", fail_consumed_marker)

    status, body = _post_json(
        review_root,
        "chemical-paper/confirm",
        {
            "study_id": "study-1",
            "preflight_token": preflight["preflight_token"],
            "actor_type": "simulated_researcher_agent",
            "actor_label": "simulated_researcher",
        },
    )

    assert status == 200
    assert body == {"status": "imported", "study_id": "study-1"}
    assert (project / "01_evidence/chemical_paper/study-1/state.json").is_file()


def test_confirm_rejects_staged_drift_with_zero_authoritative_write(
    tmp_path: Path,
) -> None:
    review_root = tmp_path / "review-root"
    project = source_truth_project(review_root / "review-projects")
    status, preflight = _post_zip(
        review_root, write_chemical_zip(tmp_path / "chemical.zip")
    )
    assert status == 200
    staged_archives = list(
        (project / ".dual-parse-staging/chemical-paper").glob("*.zip")
    )
    assert len(staged_archives) == 1
    staged_archives[0].write_bytes(b"changed-after-preflight")
    before = _authoritative_snapshot(project)

    status, body = _post_json(
        review_root,
        "chemical-paper/confirm",
        {
            "study_id": "study-1",
            "preflight_token": preflight["preflight_token"],
            "actor_type": "simulated_researcher_agent",
            "actor_label": "simulated_researcher",
        },
    )

    assert status == 409
    assert body["error_code"] == "PREFLIGHT_STAGED_BYTES_STALE"
    assert _authoritative_snapshot(project) == before
    assert str(project) not in json.dumps(body)


def test_preflight_rejects_bad_content_type_without_writing(tmp_path: Path) -> None:
    review_root = tmp_path / "review-root"
    project = source_truth_project(review_root / "review-projects")
    archive = write_chemical_zip(tmp_path / "chemical.zip")
    payload = archive.read_bytes()
    before = _authoritative_snapshot(project)
    raw = (
        b"POST /api/project/project/chemical-paper/preflight?study_id=study-1 HTTP/1.1\r\n"
        b"Host: localhost\r\nContent-Type: application/octet-stream\r\nContent-Length: "
        + str(len(payload)).encode("ascii")
        + b"\r\n\r\n"
        + payload
    )

    status, _, body = _http_request(review_root, raw)

    assert status == 415
    assert json.loads(body)["error_code"] == "CHEMICAL_ZIP_CONTENT_TYPE_INVALID"
    assert _authoritative_snapshot(project) == before
    assert not (project / ".dual-parse-staging").exists()


def test_get_dual_parse_returns_only_safe_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from view import serve_review_dashboard as dashboard

    review_root = tmp_path / "review-root"
    source_truth_project(review_root / "review-projects")
    monkeypatch.setattr(
        dashboard,
        "dual_parse_dashboard_projection",
        lambda project: {
            "project_status": "needs_chemical_import",
            "summary": {
                "core_studies": 1,
                "generic_current": 1,
                "chemical_current": 0,
                "reaction_data_status": "unavailable_not_provided",
            },
            "studies": [
                {
                    "study_id": "study-1",
                    "source_tier": "core",
                    "generic_parse_status": "current",
                    "chemical_import_status": "missing",
                    "completion_status": "blocked",
                    "reconciliation_status": "blocked",
                    "pdf_page_url": "/api/project/project/source/study-1/pdf-page?page=1",
                }
            ],
            "unique_next_action": "Import the Chemical Paper export for study-1.",
        },
    )

    status, _, body = _http_request(
        review_root,
        b"GET /api/project/project/dual-parse HTTP/1.1\r\nHost: localhost\r\n\r\n",
    )

    assert status == 200
    payload = json.loads(body)
    assert payload["summary"]["reaction_data_status"] == "unavailable_not_provided"
    assert payload["unique_next_action"].startswith("Import")
    assert "credits" not in json.dumps(payload).casefold()


def test_completion_and_reconciliation_put_keep_snake_case_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from view import serve_review_dashboard as dashboard

    review_root = tmp_path / "review-root"
    source_truth_project(review_root / "review-projects")
    seen: dict[str, object] = {}

    def completion(project: Path, payload: object) -> dict[str, object]:
        seen["completion"] = payload
        return {"status": "updated", "applied_count": 1}

    def reconciliation(project: Path, payload: object) -> dict[str, object]:
        seen["reconciliation"] = payload
        return {"status": "pdf_resolved", "study_id": "study-1"}

    monkeypatch.setattr(dashboard, "apply_chemical_completion_http", completion)
    monkeypatch.setattr(dashboard, "apply_reconciliation_http", reconciliation)
    completion_payload = {
        "study_id": "study-1",
        "version_token": "opaque-current-token",
        "actor_type": "simulated_researcher_agent",
        "actor_label": "simulated_researcher",
        "corrections": [
            {
                "molecule_index": 0,
                "field": "smiles_expanded",
                "value": "C",
                "reason": "Visible in Scheme 1.",
                "pdf_locator": {"page": 1, "figure_label": "Scheme 1"},
            }
        ],
    }
    reconciliation_payload = {
        "study_id": "study-1",
        "object_id": "molecule-0",
        "registry_digest": "opaque-registry-token",
        "action": "pdf_resolved",
        "selected_lane": "chemical",
        "note": "The original PDF supports the Chemical Paper candidate.",
        "pdf_locator": {"page": 1, "figure_label": "Scheme 1"},
        "actor_type": "simulated_researcher_agent",
        "actor_label": "simulated_researcher",
    }

    completion_status, completion_body = _put_json(
        review_root, "chemical-completion", completion_payload
    )
    reconciliation_status, reconciliation_body = _put_json(
        review_root, "parse-reconciliation", reconciliation_payload
    )

    assert completion_status == 200
    assert completion_body["applied_count"] == 1
    assert reconciliation_status == 200
    assert reconciliation_body["status"] == "pdf_resolved"
    assert seen == {
        "completion": completion_payload,
        "reconciliation": reconciliation_payload,
    }


def test_completion_route_rejects_camel_case_before_authority_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from view import serve_review_dashboard as dashboard

    review_root = tmp_path / "review-root"
    project = source_truth_project(review_root / "review-projects")
    called = False

    def completion(project: Path, payload: object) -> dict[str, object]:
        nonlocal called
        called = True
        return {"status": "updated"}

    monkeypatch.setattr(dashboard, "apply_chemical_completion_http", completion)
    before = _authoritative_snapshot(project)

    status, body = _put_json(
        review_root,
        "chemical-completion",
        {
            "studyId": "study-1",
            "versionToken": "opaque",
            "actorType": "simulated_researcher_agent",
            "actorLabel": "simulated_researcher",
            "corrections": [],
        },
    )

    assert status == 422
    assert body["error_code"] == "CHEMICAL_COMPLETION_REQUEST_INVALID"
    assert called is False
    assert _authoritative_snapshot(project) == before


def test_dual_parse_evaluation_marks_credits_not_applicable_without_zero(
    tmp_path: Path,
) -> None:
    from view import serve_review_dashboard as dashboard

    project = tmp_path / "project"
    (project / "01_evidence/dual_source").mkdir(parents=True)

    payload = dashboard.project_evaluation_payload(project)

    assert payload["credits_status"] == "NOT_APPLICABLE_BY_CURRENT_SCOPE"
    assert "credit_ledger" not in payload
    assert "credits" not in payload
