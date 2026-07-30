from __future__ import annotations

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
from review_writer.project.dual_source import write_dual_source_binding
from review_writer.project.parse_quality import write_parse_quality_gate
from review_writer.project.parse_reconciliation import write_parse_reconciliation
from review_writer.project.source_truth import write_source_truth_bundle
from review_writer.project.workflow_projection import workflow_state
from test_parse_quality import _decide_all
from test_dual_parse_content_package import paper_request
from test_chemical_completion import completion_project
from test_chemical_paper_import import v2000, write_chemical_zip
from test_dual_source import dual_project
from test_parse_reconciliation import reconciliation_project
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
