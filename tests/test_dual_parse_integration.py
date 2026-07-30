from __future__ import annotations

import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from review_writer.delivery.dual_parse_release import (
    apply_chemical_completion_http,
    confirm_chemical_paper_import,
    dual_parse_dashboard_projection,
    dual_parse_manuscript_bindings,
    dual_parse_release_state,
    preflight_chemical_paper_import,
    refresh_dual_parse_derived_state,
)
from review_writer.project.chemical_completion import (
    apply_chemical_completion_batch,
    chemical_completion_state,
)
from review_writer.project.content_agent_handoff import (
    ContentAgentError,
    build_content_task_package,
)
from review_writer.project.dual_parse_bootstrap import (
    bind_generic_parse_outputs,
    bootstrap_dual_parse_project,
)
from review_writer.project.dual_source import (
    project_dual_source_state,
    write_dual_source_binding,
)
from review_writer.project.paper_evidence import paper_evidence_state
from review_writer.project.parse_quality import write_parse_quality_gate
from review_writer.project.parse_reconciliation import write_parse_reconciliation
from review_writer.project.source_truth import (
    load_source_truth_bundle,
    write_source_truth_bundle,
)
from review_writer.project.workflow_projection import workflow_state
from test_parse_quality import _decide_all
from test_dual_parse_content_package import paper_request
from test_chemical_completion import completion_project
from test_chemical_paper_import import v2000, write_chemical_zip
from test_dual_source import dual_project
from test_parse_reconciliation import reconciliation_project
from test_dual_parse_bootstrap import generic_output, source_request
from view.serve_review_dashboard import project_cockpit_payload
from view.serve_review_dashboard import project_review_figures_workspace_payload


def _ready_project(tmp_path: Path) -> Path:
    project = reconciliation_project(tmp_path, conflict=False)
    write_parse_reconciliation(project, "scholarly-a")
    lineage_root = project / "04_manuscript"
    lineage_root.mkdir(parents=True, exist_ok=True)
    (lineage_root / "manuscript_lineage.v2.json").write_text(
        json.dumps(
            {
                "dual_parse_bindings": dual_parse_manuscript_bindings(
                    project, {"scholarly-a"}
                )
            }
        ),
        encoding="utf-8",
    )
    return project


def test_cockpit_package_and_release_share_dual_currentness(tmp_path: Path) -> None:
    project = _ready_project(tmp_path)

    cockpit = project_cockpit_payload(tmp_path, project.name)
    package = build_content_task_package(project, paper_request(project))
    release = dual_parse_release_state(project)

    assert cockpit["dual_parse_status"] == "current"
    assert package["request_kind"] == "paper_evidence"
    assert release["dual_parse_status"] == "current"
    assert release["internal_release_ready"] is True


def test_reparse_stales_ui_package_and_release_together(tmp_path: Path) -> None:
    project = _ready_project(tmp_path)
    content_path = (
        project
        / "01_evidence/parses/extracted/10_1000_example/parse_content_list.json"
    )
    content = json.loads(content_path.read_text(encoding="utf-8"))
    content[-1]["smiles_expanded"] = "CC"
    content_path.write_text(json.dumps(content), encoding="utf-8")
    write_source_truth_bundle(project, "scholarly-a")
    write_parse_quality_gate(project, "scholarly-a")
    _decide_all(project)

    assert project_cockpit_payload(tmp_path, project.name)["dual_parse_status"] == "stale"
    with pytest.raises(
        ContentAgentError, match="CHEMICAL_PAPER_SOURCE_TRUTH_STALE"
    ):
        build_content_task_package(project, paper_request(project))
    assert dual_parse_release_state(project)["internal_release_ready"] is False


def test_pdf_drift_blocks_saved_dual_binding_and_release(tmp_path: Path) -> None:
    project = _ready_project(tmp_path)
    bundle = load_source_truth_bundle(project, "scholarly-a")
    main = next(
        row for row in bundle["sources"] if row["document_role"] == "MAIN"
    )
    pdf = project / main["pdf"]["path"]
    pdf.write_bytes(pdf.read_bytes() + b"\npost-binding drift")

    scientific = project_dual_source_state(project)
    workflow = workflow_state(project)
    release = dual_parse_release_state(project)

    row = scientific["studies"][0]
    assert row["pdf_status"] == "stale"
    assert row["generic_parse_status"] != "current"
    assert row["status"] == "blocked"
    assert scientific["workflow_can_continue"] is False
    assert scientific["main_source_available_count"] == 0
    assert scientific["generic_source_available_count"] == 0
    assert workflow["dual_source_ready"] is False
    assert release["dual_parse_status"] == "stale"
    assert release["internal_release_ready"] is False
    assert "DUAL_PARSE_STALE" in release["hard_fails"]
    assert "CORE_GENERIC_PARSE_MISSING_OR_STALE" in release["hard_fails"]

    dashboard = dual_parse_dashboard_projection(project)
    assert dashboard["summary"]["chemical_bound"] == 0
    assert dashboard["summary"]["chemical_current"] == 0
    assert dashboard["studies"][0]["chemical_import_status"] == "stale"
    assert dashboard["studies"][0]["chemical_binding_status"] == "stale"


def test_backend_projection_is_consumable_by_dashboard_ui(tmp_path: Path) -> None:
    project = _ready_project(tmp_path)
    projection = dual_parse_dashboard_projection(project)

    assert projection["schema_version"] == "dual-parse-projection.v1"
    assert projection["status"] == "ready"
    assert set(projection["next_action"]) == {"label", "description"}
    assert len(projection["studies"]) == 1
    assert projection["completion_queue"] == []
    assert projection["reconciliation_items"] == []
    encoded = json.dumps(projection, ensure_ascii=False, sort_keys=True)
    for forbidden in (
        "source_pdf_sha256",
        "binding_digest",
        "state_digest",
        "mol_block",
        "raw_json",
        "credit",
        str(project),
    ):
        assert forbidden not in encoded.casefold()

    node = shutil.which("node")
    assert node is not None
    script = Path(__file__).resolve().parents[1] / "view/assets/dashboard/review-dual-parse.js"
    completed = subprocess.run(
        [
            node,
            "-e",
            (
                "const ui=require(process.argv[1]);"
                "const model=ui.projectionModel(JSON.parse(process.argv[2]));"
                "if(!model.contractValid||model.status!=='ready'||model.studies.length!==1)"
                "throw new Error(JSON.stringify(model));"
            ),
            str(script),
            encoded,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_backend_projection_exposes_safe_researcher_work_queues(
    tmp_path: Path,
) -> None:
    completion = completion_project(tmp_path / "completion")
    write_parse_quality_gate(completion, "scholarly-a")
    _decide_all(completion)
    write_dual_source_binding(completion, "scholarly-a")

    completion_projection = dual_parse_dashboard_projection(completion)
    assert [row["field"] for row in completion_projection["completion_queue"]] == [
        "mol_idt",
        "smiles_expanded",
        "smiles_unexpanded",
    ]
    assert all(
        row["version_token"].startswith("cpv1.")
        for row in completion_projection["completion_queue"]
    )

    conflict = reconciliation_project(tmp_path / "conflict", conflict=True)
    write_parse_reconciliation(conflict, "scholarly-a")
    reconciliation_projection = dual_parse_dashboard_projection(conflict)
    assert len(reconciliation_projection["reconciliation_items"]) == 1
    item = reconciliation_projection["reconciliation_items"][0]
    assert item["status"] == "conflict"
    assert item["registry_digest"].startswith("rcv1.")
    assert item["generic_candidate"].startswith("名称: compound 1")
    assert item["chemical_candidate"].startswith("名称: compound 1")


def test_fresh_generic_sources_remain_available_before_parse_and_chemical_review(
    tmp_path: Path,
) -> None:
    request = source_request(tmp_path)
    project = bootstrap_dual_parse_project(
        tmp_path / "review-projects", request
    )
    bind_generic_parse_outputs(project, generic_output(tmp_path / "generic", request))

    scientific = project_dual_source_state(project)
    dashboard = dual_parse_dashboard_projection(project)
    workflow = workflow_state(project)
    cockpit = project_cockpit_payload(tmp_path, project.name)
    evidence = paper_evidence_state(project)

    assert len(scientific["studies"]) == 3
    assert all(row["pdf_status"] == "verified" for row in scientific["studies"])
    assert all(
        row["generic_parse_status"] == "current"
        for row in scientific["studies"]
    )
    assert all(row["status"] == "blocked" for row in scientific["studies"])
    assert scientific["workflow_can_continue"] is False

    assert dashboard["summary"] == {
        "core_studies": 3,
        "pdf_verified": 3,
        "generic_current": 3,
        "chemical_current": 0,
        "chemical_bound": 0,
        "reaction_data_status": "unavailable_not_provided",
    }
    assert all(row["pdf_status"] == "verified" for row in dashboard["studies"])
    assert all(
        row["generic_parse_status"] == "current" for row in dashboard["studies"]
    )
    assert all(
        row["chemical_import_status"] == "missing"
        for row in dashboard["studies"]
    )
    assert all(
        row["completion_status"] == "blocked"
        and row["reconciliation_status"] == "blocked"
        and row["paper_evidence_status"] == "blocked"
        for row in dashboard["studies"]
    )

    assert workflow["active_stage"] == "parsing"
    assert workflow["parse_ready"] is False
    assert workflow["dual_source_ready"] is False
    assert workflow["paper_evidence_ready"] is False
    assert workflow["main_source_available_count"] == 3
    assert workflow["generic_source_available_count"] == 3
    assert cockpit["metrics"]["full_text_main_coverage"] == 3
    assert cockpit["metrics"]["reviewed_studies"] == 0
    assert evidence["workflow_can_continue"] is False


def test_dashboard_projection_validates_each_source_once_per_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from review_writer.project import dual_source as authority

    request = source_request(tmp_path)
    project = bootstrap_dual_parse_project(
        tmp_path / "review-projects", request
    )
    bind_generic_parse_outputs(project, generic_output(tmp_path / "generic", request))
    before = {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    }
    real_availability = authority._source_availability
    calls: list[str] = []

    def counted_availability(root: Path, study_id: str) -> dict[str, str]:
        calls.append(study_id)
        return real_availability(root, study_id)

    monkeypatch.setattr(authority, "_source_availability", counted_availability)

    first = dual_parse_dashboard_projection(project)

    assert first["summary"]["generic_current"] == 3
    assert calls == ["study-0", "study-1", "study-2"]

    calls.clear()
    second = dual_parse_dashboard_projection(project)

    assert second["summary"]["generic_current"] == 3
    assert calls == ["study-0", "study-1", "study-2"]
    assert {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    } == before


def test_malformed_precomputed_dual_state_recomputes_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from review_writer.project import workflow_projection as projection

    request = source_request(tmp_path)
    project = bootstrap_dual_parse_project(
        tmp_path / "review-projects", request
    )
    bind_generic_parse_outputs(project, generic_output(tmp_path / "generic", request))
    valid = project_dual_source_state(project)
    missing_keys = {
        "schema_version": valid["schema_version"],
        "studies": [{"study_id": row["study_id"]} for row in valid["studies"]],
    }
    invalid_status = copy.deepcopy(valid)
    invalid_status["studies"][0]["status"] = "forged_current"
    count_mismatch = copy.deepcopy(valid)
    count_mismatch["main_source_available_count"] += 1
    workflow_contradiction = copy.deepcopy(valid)
    workflow_contradiction["workflow_can_continue"] = True
    recomputes = 0

    def fresh_state(_project: Path) -> dict[str, object]:
        nonlocal recomputes
        recomputes += 1
        return copy.deepcopy(valid)

    monkeypatch.setattr(projection, "project_dual_source_state", fresh_state)

    for index, malformed in enumerate(
        (
            missing_keys,
            invalid_status,
            count_mismatch,
            workflow_contradiction,
        ),
        start=1,
    ):
        state = projection._new_route_state(
            project, _precomputed_dual_state=malformed
        )

        assert recomputes == index
        assert state["main_source_available_count"] == 3
        assert state["generic_source_available_count"] == 3
        assert state["dual_source_ready"] is False
        assert state["paper_evidence_ready"] is False


def test_fresh_figure_workspace_get_is_read_only(tmp_path: Path) -> None:
    project = _ready_project(tmp_path)
    before = {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    }

    payload = project_review_figures_workspace_payload(tmp_path, project.name)

    after = {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    }
    assert payload["status"] == "not_built"
    assert payload["source_figures"] == []
    assert payload["locator_gaps"] == [
        {
            "study_id": "",
            "page": None,
            "reason": "原论文图注册表尚未在正式制图阶段生成。",
        }
    ]
    assert not (project / "03_figures").exists()
    assert after == before


def test_browser_mutations_can_advance_only_deterministic_dual_gates(
    tmp_path: Path,
) -> None:
    project = completion_project(tmp_path)
    missing_before = chemical_completion_state(project, "scholarly-a")

    blocked = refresh_dual_parse_derived_state(project, "scholarly-a")

    assert blocked["status"] == "blocked"
    assert not (project / "01_evidence/dual_source").exists()
    assert chemical_completion_state(project, "scholarly-a") == missing_before

    write_parse_quality_gate(project, "scholarly-a")
    _decide_all(project)
    awaiting_completion = refresh_dual_parse_derived_state(project, "scholarly-a")

    assert awaiting_completion == {
        "status": "blocked",
        "stage": "chemical_completion",
        "reason_code": "CHEMICAL_COMPLETION_INCOMPLETE",
    }
    assert (
        project / "01_evidence/dual_source/scholarly-a/binding.json"
    ).is_file()
    assert not (project / "01_evidence/parse_reconciliation").exists()
    assert workflow_state(project)["active_stage"] == "chemical_completion"

    gate = chemical_completion_state(project, "scholarly-a")
    apply_chemical_completion_batch(
        project,
        "scholarly-a",
        {
            "version_token": gate["version_token"],
            "actor_type": "simulated_researcher_agent",
            "actor_label": "simulated_researcher",
            "corrections": [
                {
                    "molecule_index": 0,
                    "field": field,
                    "value": "compound 3a" if field == "mol_idt" else "CO",
                    "reason": "Original PDF Scheme 2 supports this value.",
                    "pdf_locator": {"page": 1, "figure_label": "Scheme 2"},
                }
                for field in ("mol_idt", "smiles_expanded", "smiles_unexpanded")
            ],
        },
    )

    advanced = refresh_dual_parse_derived_state(project, "scholarly-a")

    assert advanced["status"] == "current"
    assert advanced["stage"] == "reconciliation"
    assert (
        project / "01_evidence/parse_reconciliation/scholarly-a/registry.json"
    ).is_file()
    assert workflow_state(project)["active_stage"] == "evidence"


def test_confirm_and_completion_http_advance_derived_gates(tmp_path: Path) -> None:
    project = dual_project(tmp_path, chemical=False)
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
    preflight = preflight_chemical_paper_import(
        project, "scholarly-a", archive.read_bytes()
    )

    confirm_chemical_paper_import(
        project,
        {
            "study_id": "scholarly-a",
            "preflight_token": preflight["preflight_token"],
            "actor_type": "simulated_researcher_agent",
            "actor_label": "simulated_researcher",
        },
    )

    assert (
        project / "01_evidence/dual_source/scholarly-a/binding.json"
    ).is_file()
    assert workflow_state(project)["active_stage"] == "chemical_completion"
    gate = chemical_completion_state(project, "scholarly-a")

    apply_chemical_completion_http(
        project,
        {
            "study_id": "scholarly-a",
            "version_token": gate["version_token"],
            "actor_type": "simulated_researcher_agent",
            "actor_label": "simulated_researcher",
            "corrections": [
                {
                    "molecule_index": 0,
                    "field": field,
                    "value": "compound 3a" if field == "mol_idt" else "CO",
                    "reason": "Original PDF Scheme 2 supports this value.",
                    "pdf_locator": {"page": 1, "figure_label": "Scheme 2"},
                }
                for field in ("mol_idt", "smiles_expanded", "smiles_unexpanded")
            ],
        },
    )

    assert (
        project / "01_evidence/parse_reconciliation/scholarly-a/registry.json"
    ).is_file()
    assert workflow_state(project)["active_stage"] == "evidence"
