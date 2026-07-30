from __future__ import annotations

import json
import io
import subprocess
import sys
from pathlib import Path

import pytest

from review_writer.project.chemical_paper import (
    correct_chemical_paper_field,
    import_chemical_paper,
)
from review_writer.project.content_agent_handoff import (
    ContentAgentError,
    build_content_task_package,
    import_content_agent_result,
)
from review_writer.project.manuscript_v2 import approve_section, merge_authoritative_manuscript, register_section_draft
from review_writer.project.review_figures import build_source_figure_registry, load_source_figure_registry
from review_writer.project.source_truth import canonical_digest
from test_chemical_paper_import import ACTOR, PDF_SHA, snapshot, source_truth_project, v2000, write_chemical_zip
from test_content_agent_handoff import _project as content_project, _request, _result
from test_manuscript_v2 import _actor, _draft, project
from test_review_figures import _new_route_project


ROOT = Path(__file__).resolve().parents[1]


def _http_request(review_root: Path, raw_request: bytes) -> tuple[int, dict[str, str], bytes]:
    from view import serve_review_dashboard as dashboard

    class FakeSocket:
        def __init__(self, incoming: bytes) -> None:
            self.input, self.output = io.BytesIO(incoming), io.BytesIO()

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


def _main_binding(project: Path, study_id: str) -> tuple[str, str, int]:
    bundle = json.loads(
        (project / f"01_evidence/source_truth/{study_id}/bundle.json").read_text(encoding="utf-8")
    )
    source = next(row for row in bundle["sources"] if row["document_role"] == "MAIN")
    return source["pdf"]["sha256"], source["source_id"], source["page_count"]


def _archive(path: Path, pages: int) -> Path:
    molecules = [
        {
            "mol_id": "mol-1",
            "page_idx": 0,
            "bbox_normalized": [0.1, 0.2, 0.3, 0.4],
            "smiles_expanded": "C",
            "smiles_unexpanded": "C",
            "mol_idt": "methane-candidate",
            "mol_block": v2000(("C",)),
        }
    ]
    return write_chemical_zip(path, pages=pages, molecules=molecules)


def test_content_agent_package_binds_current_chemical_import(tmp_path: Path) -> None:
    project = content_project(tmp_path)
    pdf_sha, _, pages = _main_binding(project, "scholarly-a")
    before = build_content_task_package(project, _request(project))
    import_chemical_paper(
        project,
        "scholarly-a",
        pdf_sha,
        _archive(tmp_path / "chemical.zip", pages),
        ACTOR,
    )
    destination = tmp_path / "chemical-task-package"
    after = build_content_task_package(project, _request(project), destination)

    assert set(after["inputs"]) == {"chemical_paper", "source_truth"}
    assert [row["kind"] for row in after["inputs"]["chemical_paper"]] == [
        "chemical_paper_state"
    ]
    assert [row["kind"] for row in after["inputs"]["source_truth"]] == [
        "source_asset:pdf"
    ]
    copied = {
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    assert copied == {
        row["path"] for rows in after["inputs"].values() for row in rows
    }
    encoded = json.dumps(after, sort_keys=True)
    for superseded in (
        "canonical_markdown",
        "content_list",
        "source_asset:layout",
        "layout_layer",
        "reading_layer",
        "parse_quality",
    ):
        assert superseded not in encoded
    assert after["chemical_paper_import_bindings"][0]["study_id"] == "scholarly-a"
    assert after["chemical_paper_import_bindings"][0]["chemical_paper_import_digest"]
    assert after["task_package_digest"] != before["task_package_digest"]


def test_chemical_content_package_requires_current_state_before_writing_output(
    tmp_path: Path,
) -> None:
    project = content_project(tmp_path)
    (project / "01_evidence/chemical_paper").mkdir(parents=True)
    destination = tmp_path / "missing-chemical-task-package"
    before = snapshot(project)

    with pytest.raises(ContentAgentError, match="CHEMICAL_PAPER_NOT_IMPORTED"):
        build_content_task_package(project, _request(project), destination)

    assert snapshot(project) == before
    assert not destination.exists()


def test_content_agent_result_from_pre_import_package_is_stale_and_zero_write(tmp_path: Path) -> None:
    project = content_project(tmp_path)
    before_import = build_content_task_package(project, _request(project))
    result = _result(project, before_import)
    pdf_sha, _, pages = _main_binding(project, "scholarly-a")
    import_chemical_paper(
        project,
        "scholarly-a",
        pdf_sha,
        _archive(tmp_path / "chemical.zip", pages),
        ACTOR,
    )
    before = snapshot(project)
    with pytest.raises(ContentAgentError, match="TASK_PACKAGE_STALE"):
        import_content_agent_result(project, result)
    assert snapshot(project) == before


def test_content_agent_result_is_stale_after_chemical_state_change_and_zero_write(
    tmp_path: Path,
) -> None:
    project = content_project(tmp_path)
    pdf_sha, _, pages = _main_binding(project, "scholarly-a")
    imported = import_chemical_paper(
        project,
        "scholarly-a",
        pdf_sha,
        _archive(tmp_path / "chemical.zip", pages),
        ACTOR,
    )
    package = build_content_task_package(project, _request(project))
    result = _result(project, package)
    correct_chemical_paper_field(
        project,
        study_id="scholarly-a",
        molecule_index=0,
        field="smiles_expanded",
        value="CC",
        actor=ACTOR,
        reason="Checked against the original PDF.",
        version_token=imported["version_token"],
    )

    before = snapshot(project)
    with pytest.raises(ContentAgentError, match="TASK_PACKAGE_STALE"):
        import_content_agent_result(project, result)
    assert snapshot(project) == before


def test_chemical_content_package_rejects_pdf_drift_before_writing_output(
    tmp_path: Path,
) -> None:
    project = content_project(tmp_path)
    pdf_sha, _, pages = _main_binding(project, "scholarly-a")
    import_chemical_paper(
        project,
        "scholarly-a",
        pdf_sha,
        _archive(tmp_path / "chemical.zip", pages),
        ACTOR,
    )
    bundle = json.loads(
        (project / "01_evidence/source_truth/scholarly-a/bundle.json").read_text(
            encoding="utf-8"
        )
    )
    main = next(row for row in bundle["sources"] if row["document_role"] == "MAIN")
    (project / main["pdf"]["path"]).write_bytes(b"drifted PDF bytes")
    destination = tmp_path / "drifted-pdf-task-package"
    before = snapshot(project)

    with pytest.raises(ContentAgentError, match="SOURCE_ASSET_DRIFT"):
        build_content_task_package(project, _request(project), destination)

    assert snapshot(project) == before
    assert not destination.exists()


def test_paper_evidence_package_digest_is_isolated_from_existing_evidence(
    tmp_path: Path,
) -> None:
    project = content_project(tmp_path)
    first_bundle_path = project / "01_evidence/source_truth/scholarly-a/bundle.json"
    first_bundle = json.loads(first_bundle_path.read_text(encoding="utf-8"))
    second_body = {
        key: value for key, value in first_bundle.items() if key != "bundle_digest"
    }
    second_body["study_id"] = "scholarly-b"
    second_body["study_identity"] = {
        "doi": "10.1000/example-b",
        "title": "Example B",
    }
    second_body["sources"][0]["source_id"] = "stud-b"
    second_bundle_path = project / "01_evidence/source_truth/scholarly-b/bundle.json"
    second_bundle_path.parent.mkdir(parents=True)
    second_bundle_path.write_text(
        json.dumps(
            {**second_body, "bundle_digest": canonical_digest(second_body)},
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    receipt_path = project / "00_sources/acquisition_final_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["studies"].append({"study_id": "scholarly-b"})
    receipt_path.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")

    pdf_sha, _, pages = _main_binding(project, "scholarly-a")
    for study_id in ("scholarly-a", "scholarly-b"):
        import_chemical_paper(
            project,
            study_id,
            pdf_sha,
            _archive(tmp_path / f"{study_id}.zip", pages),
            ACTOR,
        )

    second_request = _request(project, targets=["scholarly-b"])
    before = build_content_task_package(project, second_request)
    evidence_projection = project / "01_evidence/paper_evidence_projection.jsonl"
    evidence_projection.write_text(
        json.dumps({"study_id": "scholarly-a", "evidence_id": "study-a-candidate"})
        + "\n",
        encoding="utf-8",
    )
    target_candidates = project / "01_evidence/scholarly-b/paper_evidence_candidates.json"
    target_candidates.parent.mkdir(parents=True, exist_ok=True)
    target_candidates.write_text(
        json.dumps({"candidates": [{"evidence_id": "existing-study-b-candidate"}]}),
        encoding="utf-8",
    )
    after = build_content_task_package(project, second_request)

    assert "paper_evidence" not in after["inputs"]
    assert after["task_package_digest"] == before["task_package_digest"]
    synthesis = build_content_task_package(
        project,
        _request(
            project,
            kind="synthesis_claims",
            targets=["scholarly-a", "scholarly-b"],
        ),
    )
    assert {row["kind"] for row in synthesis["inputs"]["paper_evidence"]} == {
        "paper_evidence_projection",
        "paper_evidence_candidates",
    }


def test_source_figure_registry_keeps_generic_authority_with_chemical_gap(tmp_path: Path) -> None:
    project = _new_route_project(tmp_path)
    pdf_sha, _, pages = _main_binding(project, "scholarly-a")
    import_chemical_paper(
        project,
        "scholarly-a",
        pdf_sha,
        _archive(tmp_path / "chemical.zip", pages),
        ACTOR,
    )
    registry = build_source_figure_registry(project)

    assert registry["chemical_paper_project_binding_digest"]
    assert [row["figure_label"] for row in registry["figures"]] == ["Figure 1"]
    assert all(
        row["asset_path"].startswith("01_evidence/parses/extracted/")
        for row in registry["figures"]
    )
    assert any(
        "Chemical Paper" in row["reason"] and "独立图片" in row["reason"]
        for row in registry["locator_gaps"]
    )
    assert load_source_figure_registry(project)["registry_digest"] == registry["registry_digest"]


def test_manuscript_lineage_includes_exact_frozen_chemical_fields(
    project: Path, monkeypatch
) -> None:
    chemical_root = project / "01_evidence/chemical_paper"
    chemical_root.mkdir(parents=True)
    expected = {
        "chemical_paper_import_digests": [],
        "chemical_paper_safe_summary": {
            "schema_version": "chemical-paper-safe-summary.v1",
            "route": "chemical-paper-zip-only",
            "study_count": 0,
            "molecule_count": 0,
            "unresolved_field_count": 0,
            "element_review_counts": {
                "not_reviewed": 0,
                "confirmed": 0,
                "corrected": 0,
                "not_applicable": 0,
            },
            "reaction_data_status": "unavailable_not_provided",
        },
    }
    monkeypatch.setattr(
        "review_writer.project.manuscript_v2.chemical_paper_manuscript_bindings",
        lambda *_args, **_kwargs: expected,
    )
    draft = register_section_draft(
        project, _draft("The experiment reported the product. [evidence:evidence-low]")
    )
    approve_section(project, draft["section_id"], actor=_actor(), reason="Checked evidence.")
    merge_authoritative_manuscript(project)
    lineage = json.loads(
        (project / "04_manuscript/manuscript_lineage.v2.json").read_text(encoding="utf-8")
    )
    assert lineage["chemical_paper_import_digests"] == expected["chemical_paper_import_digests"]
    assert lineage["chemical_paper_safe_summary"] == expected["chemical_paper_safe_summary"]
    assert lineage["chemical_paper_claim_dependencies"] == []
    assert {key for key in lineage if key.startswith("chemical_paper_")} == {
        "chemical_paper_import_digests",
        "chemical_paper_safe_summary",
        "chemical_paper_claim_dependencies",
    }


def test_cli_exposes_only_the_four_frozen_commands(tmp_path: Path) -> None:
    script = ROOT / "scripts/review/chemical_paper.py"
    help_result = subprocess.run(
        [sys.executable, str(script), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    for command in (
        "import-chemical-paper",
        "chemical-paper-state",
        "correct-chemical-paper-field",
        "review-chemical-paper-elements",
    ):
        assert command in help_result.stdout

    project = content_project(tmp_path)
    pdf_sha, _, pages = _main_binding(project, "scholarly-a")
    archive = _archive(tmp_path / "chemical.zip", pages)
    imported = subprocess.run(
        [
            sys.executable,
            str(script),
            "import-chemical-paper",
            "--project",
            str(project),
            "--study-id",
            "scholarly-a",
            "--source-pdf-sha256",
            pdf_sha,
            "--zip",
            str(archive),
            "--actor-type",
            "simulated_researcher_agent",
            "--actor-label",
            "fixture-researcher",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(imported.stdout)["result"]["status"] == "imported"
    projected = subprocess.run(
        [sys.executable, str(script), "chemical-paper-state", "--project", str(project)],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(projected.stdout)["result"]
    assert payload["schema_version"] == "chemical-paper-projection.v1"
    assert "source_pdf_sha256" not in projected.stdout


def test_primary_vertical_cli_exposes_all_frozen_chemical_commands() -> None:
    script = ROOT / "scripts/run_vertical_review.py"
    commands = {
        "import-chemical-paper": (
            "--project",
            "--study-id",
            "--source-pdf-sha256",
            "--zip",
            "--actor-type",
            "--actor-label",
        ),
        "chemical-paper-state": ("--project",),
        "correct-chemical-paper-field": (
            "--project",
            "--study-id",
            "--molecule-index",
            "--field",
            "--value",
            "--reason",
            "--version-token",
            "--actor-type",
            "--actor-label",
        ),
        "review-chemical-paper-elements": (
            "--project",
            "--study-id",
            "--molecule-index",
            "--state",
            "--reason",
            "--version-token",
            "--element",
            "--actor-type",
            "--actor-label",
        ),
    }
    root_help = subprocess.run(
        [sys.executable, str(script), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    for command, options in commands.items():
        assert command in root_help.stdout
        result = subprocess.run(
            [sys.executable, str(script), command, "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "invalid choice" not in result.stderr
        for option in options:
            assert option in result.stdout


def test_primary_vertical_cli_executes_safe_chemical_workflow(tmp_path: Path) -> None:
    script = ROOT / "scripts/run_vertical_review.py"
    project = content_project(tmp_path)
    pdf_sha, _, pages = _main_binding(project, "scholarly-a")
    archive = _archive(tmp_path / "chemical.zip", pages)

    def invoke(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), *arguments],
            check=check,
            capture_output=True,
            text=True,
        )

    imported_process = invoke(
        "import-chemical-paper",
        "--project",
        str(project),
        "--study-id",
        "scholarly-a",
        "--source-pdf-sha256",
        pdf_sha,
        "--zip",
        str(archive),
        "--actor-type",
        ACTOR["actor_type"],
        "--actor-label",
        ACTOR["actor_label"],
    )
    imported = json.loads(imported_process.stdout)
    assert imported["ok"] is True
    assert imported["result"]["status"] == "imported"

    state_process = invoke("chemical-paper-state", "--project", str(project))
    state = json.loads(state_process.stdout)
    assert state["ok"] is True
    projection = state["result"]
    assert projection["schema_version"] == "chemical-paper-projection.v1"
    assert projection["route"] == "chemical-paper-zip-only"
    version = projection["studies"][0]["version_token"]

    corrected_process = invoke(
        "correct-chemical-paper-field",
        "--project",
        str(project),
        "--study-id",
        "scholarly-a",
        "--molecule-index",
        "0",
        "--field",
        "smiles_expanded",
        "--value",
        "CC",
        "--reason",
        "Checked against the original PDF.",
        "--version-token",
        version,
        "--actor-type",
        ACTOR["actor_type"],
        "--actor-label",
        ACTOR["actor_label"],
    )
    corrected = json.loads(corrected_process.stdout)
    assert corrected["ok"] is True
    assert corrected["result"]["status"] == "corrected"
    assert corrected["result"]["molecule_index"] == 0

    reviewed_process = invoke(
        "review-chemical-paper-elements",
        "--project",
        str(project),
        "--study-id",
        "scholarly-a",
        "--molecule-index",
        "0",
        "--state",
        "confirmed",
        "--reason",
        "Optional element review against the original PDF.",
        "--version-token",
        corrected["result"]["version_token"],
        "--actor-type",
        ACTOR["actor_type"],
        "--actor-label",
        ACTOR["actor_label"],
    )
    reviewed = json.loads(reviewed_process.stdout)
    assert reviewed["ok"] is True
    assert reviewed["result"]["status"] == "confirmed"

    final_state_process = invoke("chemical-paper-state", "--project", str(project))
    final_state = json.loads(final_state_process.stdout)["result"]
    molecule = final_state["studies"][0]["molecules"][0]
    assert molecule["smiles_expanded"] == "CC"
    assert molecule["element_review_state"] == "confirmed"

    encoded_outputs = "\n".join(
        process.stdout
        for process in (
            imported_process,
            state_process,
            corrected_process,
            reviewed_process,
            final_state_process,
        )
    )
    for forbidden in (
        str(project),
        pdf_sha,
        "source_pdf_sha256",
        "archive_sha256",
        "mol_block",
        '"molecule_id"',
        "entry_inventory",
    ):
        assert forbidden not in encoded_outputs

    invalid_project = tmp_path / "does-not-exist"
    failed = invoke(
        "chemical-paper-state",
        "--project",
        str(invalid_project),
        check=False,
    )
    assert failed.returncode == 2
    assert failed.stdout == ""
    error = json.loads(failed.stderr)
    assert error["ok"] is False
    assert set(error) == {"ok", "error_code"}
    assert str(invalid_project) not in failed.stderr


def test_http_get_and_patch_follow_safe_frozen_v1_contract(tmp_path: Path) -> None:
    review_root = tmp_path / "review-root"
    project = source_truth_project(review_root / "review-projects")
    import_chemical_paper(
        project,
        "study-1",
        PDF_SHA,
        write_chemical_zip(tmp_path / "chemical.zip"),
        ACTOR,
    )

    status, headers, body = _http_request(
        review_root,
        b"GET /api/project/project/chemical-paper HTTP/1.1\r\nHost: localhost\r\n\r\n",
    )
    assert status == 200
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    projection = json.loads(body)
    assert projection["schema_version"] == "chemical-paper-projection.v1"
    encoded = body.decode("utf-8")
    assert PDF_SHA not in encoded
    assert "mol-2" not in encoded
    version = projection["studies"][0]["version_token"]

    request = {
        "study_id": "study-1",
        "molecule_index": 1,
        "field": "smiles_expanded",
        "value": "N",
        "reason": "Checked against the original PDF.",
        "actor_type": "simulated_researcher_agent",
        "actor_label": "fixture-researcher",
        "version_token": version,
    }
    payload = json.dumps(request).encode("utf-8")
    raw = (
        b"PATCH /api/project/project/chemical-paper/field HTTP/1.1\r\n"
        b"Host: localhost\r\nContent-Type: application/json\r\nContent-Length: "
        + str(len(payload)).encode()
        + b"\r\n\r\n"
        + payload
    )
    status, _, response = _http_request(review_root, raw)
    assert status == 200
    field_result = json.loads(response)
    assert field_result["molecule_index"] == 1

    elements = json.dumps(
        {
            "study_id": "study-1",
            "molecule_index": 1,
            "action": "corrected",
            "corrected_elements": [{"symbol": "N", "count": 1}, {"symbol": "H", "count": 3}],
            "reason": "Optional review against the original PDF.",
            "actor_type": "simulated_researcher_agent",
            "actor_label": "fixture-researcher",
            "version_token": field_result["version_token"],
        }
    ).encode("utf-8")
    elements_raw = (
        b"PATCH /api/project/project/chemical-paper/elements HTTP/1.1\r\n"
        b"Host: localhost\r\nContent-Type: application/json\r\nContent-Length: "
        + str(len(elements)).encode()
        + b"\r\n\r\n"
        + elements
    )
    status, _, response = _http_request(review_root, elements_raw)
    assert status == 200
    assert json.loads(response)["status"] == "corrected"

    before = snapshot(project)
    status, _, response = _http_request(review_root, raw)
    assert status == 409
    assert json.loads(response) == {
        "ok": False,
        "error_code": "STALE_CHEMICAL_PAPER_STATE",
        "message": "化学论文状态已更新，请刷新后重新审查。",
    }
    assert snapshot(project) == before


def test_http_patch_rejects_invalid_and_missing_without_internal_detail(tmp_path: Path) -> None:
    review_root = tmp_path / "review-root"
    project = source_truth_project(review_root / "review-projects")
    bad = json.dumps({"study_id": "study-1", "unexpected": True}).encode("utf-8")
    raw = (
        b"PATCH /api/project/project/chemical-paper/elements HTTP/1.1\r\n"
        b"Host: localhost\r\nContent-Type: application/json\r\nContent-Length: "
        + str(len(bad)).encode()
        + b"\r\n\r\n"
        + bad
    )
    status, _, response = _http_request(review_root, raw)
    assert status == 422
    assert json.loads(response)["error_code"] == "CHEMICAL_PAPER_REQUEST_INVALID"
    assert str(project) not in response.decode("utf-8")

    status, _, response = _http_request(
        review_root,
        b"GET /api/project/project/chemical-paper HTTP/1.1\r\nHost: localhost\r\n\r\n",
    )
    assert status == 200
    assert json.loads(response)["studies"][0]["status"] == "missing"
