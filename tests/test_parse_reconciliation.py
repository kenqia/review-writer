from __future__ import annotations

import json
from pathlib import Path

import pytest

from review_writer.project.chemical_paper import import_chemical_paper
from review_writer.project.dual_source import write_dual_source_binding
from review_writer.project.parse_quality import write_parse_quality_gate
from review_writer.project.parse_reconciliation import (
    ParseReconciliationError,
    _candidate,
    apply_reconciliation_decision,
    require_reconciliation_ready,
    write_parse_reconciliation,
)
from review_writer.project.paper_evidence import PaperEvidenceError, register_paper_evidence_candidates
from review_writer.project.source_truth import load_source_truth_bundle, write_source_truth_bundle
from review_writer.project.workflow_projection import workflow_state
from test_chemical_paper_import import ACTOR, v2000, write_chemical_zip
from test_parse_quality import _decide_all, _parse_project
from test_paper_evidence import candidate


def reconciliation_project(tmp_path: Path, *, conflict: bool = True) -> Path:
    project = _parse_project(tmp_path)
    content_path = project / "01_evidence/parses/extracted/10_1000_example/parse_content_list.json"
    content = json.loads(content_path.read_text(encoding="utf-8"))
    content.append({
        "type": "molecule", "page_idx": 0, "bbox": [10, 20, 30, 40],
        "mol_idt": "compound 1",
        "resolved_smiles": "CN" if conflict else "CO",
    })
    content_path.write_text(json.dumps(content), encoding="utf-8")
    write_source_truth_bundle(project, "scholarly-a")
    write_parse_quality_gate(project, "scholarly-a")
    _decide_all(project)
    (project / "00_discovery").mkdir(parents=True, exist_ok=True)
    (project / "00_discovery/candidate_pool.json").write_text(json.dumps({
        "schema_version": "candidate-pool.v1",
        "candidates": [{"candidate_id": "scholarly-a", "study_id": "scholarly-a", "source_id": "stud-a", "tier": "core"}],
    }), encoding="utf-8")
    source_sha = load_source_truth_bundle(project, "scholarly-a")["sources"][0]["pdf"]["sha256"]
    archive = write_chemical_zip(tmp_path / "chemical.zip", pages=1, molecules=[{
        "mol_id": "mol-a", "page_idx": 0, "bbox_normalized": [0.1, 0.2, 0.3, 0.4],
        "smiles_expanded": "CO", "smiles_unexpanded": "CO", "mol_idt": "compound 1",
        "mol_block": v2000(),
    }])
    import_chemical_paper(project, "scholarly-a", source_sha, archive, ACTOR)
    write_dual_source_binding(project, "scholarly-a")
    return project


@pytest.mark.parametrize(
    "row",
    [
        {
            "mol_idt": "compound 1",
            "smiles_expanded": "CO",
            "smiles_unexpanded": "CO",
        },
        {
            "mol_idt": "compound 1",
            "resolved_smiles": "CO",
            "smiles_expanded": "CO",
            "smiles_unexpanded": "CO",
        },
    ],
)
def test_reconciliation_candidate_rejects_legacy_or_dual_smiles_contract(
    row: dict[str, object],
) -> None:
    with pytest.raises(
        ParseReconciliationError,
        match="PARSE_RECONCILIATION_CONTRACT_INVALID",
    ):
        _candidate(row)


def test_conflict_requires_pdf_resolution(tmp_path: Path) -> None:
    registry = write_parse_reconciliation(reconciliation_project(tmp_path), "scholarly-a")

    conflict = next(row for row in registry["objects"] if row["status"] == "conflict")
    assert conflict["generic_candidate"] != conflict["chemical_candidate"]
    assert registry["workflow_can_continue"] is False


def test_resolution_records_pdf_actor_and_object_version(tmp_path: Path) -> None:
    project = reconciliation_project(tmp_path)
    registry = write_parse_reconciliation(project, "scholarly-a")
    conflict = next(row for row in registry["objects"] if row["status"] == "conflict")

    updated = apply_reconciliation_decision(project, "scholarly-a", {
        "object_id": conflict["object_id"], "registry_digest": registry["registry_digest"],
        "action": "pdf_resolved", "selected_lane": "chemical",
        "note": "Original PDF supports this structure.",
        "pdf_locator": {"page": 1, "figure_label": "Scheme 3"},
        "actor_type": "simulated_researcher_agent", "actor_label": "simulated_researcher",
    })

    resolved = next(row for row in updated["objects"] if row["object_id"] == conflict["object_id"])
    assert resolved["decision"]["action"] == "pdf_resolved"
    assert resolved["decision"]["bound_object_digest"] == conflict["object_digest"]
    assert resolved["decision"]["actor_type"] == "simulated_researcher_agent"
    assert updated["workflow_can_continue"] is True
    assert require_reconciliation_ready(project, "scholarly-a") == updated["registry_digest"]


def test_corroborated_objects_do_not_manufacture_approval(tmp_path: Path) -> None:
    registry = write_parse_reconciliation(reconciliation_project(tmp_path, conflict=False), "scholarly-a")

    corroborated = next(row for row in registry["objects"] if row["status"] == "corroborated")
    assert corroborated["decision"] is None
    assert registry["workflow_can_continue"] is True


def test_evidence_prewrite_gate_rejects_unresolved_core_registry_with_zero_write(
    tmp_path: Path,
) -> None:
    project = reconciliation_project(tmp_path)
    write_parse_reconciliation(project, "scholarly-a")
    before = {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in project.rglob("*") if path.is_file()
    }

    with pytest.raises(PaperEvidenceError, match="PARSE_RECONCILIATION_UNRESOLVED"):
        register_paper_evidence_candidates(project, "scholarly-a", {
            **candidate(), "field_dependencies": ["smiles"],
        })

    after = {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in project.rglob("*") if path.is_file()
    }
    assert after == before
    workflow = workflow_state(project)
    assert workflow["active_stage"] == "reconciliation"
    assert workflow["unique_next_action"] == "Resolve the next dual-parse conflict against the PDF."
