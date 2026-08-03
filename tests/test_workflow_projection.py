from __future__ import annotations

import json
from pathlib import Path

from review_writer.project.parse_quality import (
    apply_parse_quality_decision,
    parse_quality_state,
    write_parse_quality_gate,
)
from review_writer.project.source_truth import write_source_truth_bundle
from review_writer.project.workflow_projection import workflow_state
from test_source_truth import _source_truth_project


def _legacy_release_files(project: Path) -> None:
    evidence = project / "01_evidence/evidence_cards.jsonl"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps({"study_id": "legacy-study"}) + "\n", encoding="utf-8")
    draft = project / "04_first_draft/first_draft.md"
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text("# Legacy draft\n", encoding="utf-8")
    exported = project / "05_final_audit/final_draft.docx"
    exported.parent.mkdir(parents=True, exist_ok=True)
    exported.write_bytes(b"legacy-docx")


def _approve_parse(project: Path) -> None:
    state = parse_quality_state(project, "scholarly-a")
    for row in state["objects"]:
        if row["status"] == "usable":
            continue
        state = apply_parse_quality_decision(
            project,
            "scholarly-a",
            {
                "object_id": row["object_id"],
                "object_digest": row["object_digest"],
                "gate_digest": state["gate_digest"],
                "action": "approve_candidate_extraction",
                "note": "Compared with the original PDF.",
                "actor_type": "simulated_researcher_agent",
                "actor_label": "workflow-projection-test",
            },
        )


def test_source_truth_project_never_uses_legacy_files_as_completion(
    tmp_path: Path,
) -> None:
    project = _source_truth_project(tmp_path)
    write_source_truth_bundle(project, "scholarly-a")
    _legacy_release_files(project)

    state = workflow_state(project)

    assert state["route"] == "evidence-to-release.v1"
    assert state["active_stage"] == "parsing"
    assert state["parse_ready"] is False
    assert state["paper_evidence_ready"] is False
    assert state["internal_draft_export_ready"] is False


def test_source_truth_project_fails_closed_at_evidence_after_parse_approval(
    tmp_path: Path,
) -> None:
    project = _source_truth_project(tmp_path)
    write_source_truth_bundle(project, "scholarly-a")
    write_parse_quality_gate(project, "scholarly-a")
    _approve_parse(project)
    _legacy_release_files(project)

    first = workflow_state(project)
    second = workflow_state(project)

    assert first["active_stage"] == "evidence"
    assert first["parse_ready"] is True
    assert first["paper_evidence_ready"] is False
    assert first["manuscript_ready"] is False
    assert first["workflow_digest"] == second["workflow_digest"]


def test_project_without_source_truth_keeps_legacy_release_projection(
    tmp_path: Path,
) -> None:
    project = tmp_path / "review-projects/legacy"
    project.mkdir(parents=True)
    _legacy_release_files(project)

    state = workflow_state(project)

    assert state["route"] == "legacy"
    assert state["active_stage"] == "final"
    assert state["manuscript_ready"] is True
    assert state["internal_draft_export_ready"] is True


def test_malformed_new_route_artifacts_cannot_advance_workflow(tmp_path: Path) -> None:
    project = _source_truth_project(tmp_path)
    write_source_truth_bundle(project, "scholarly-a")
    write_parse_quality_gate(project, "scholarly-a")
    _approve_parse(project)
    decision = {
        "schema_version": "verification-decision.v1",
        "actor_type": "simulated_researcher_agent",
        "actor_label": "forged-shape",
        "action": "approve",
        "reason": "Shape-only data must not authorize a workflow.",
        "decided_at": "2026-07-28T00:00:00+00:00",
        "bound_object_digest": "0" * 64,
    }
    fake_rows = {
        "01_evidence/paper_evidence_projection.jsonl": {
            "schema_version": "paper-evidence.v1",
            "status": "approved",
            "decision": decision,
        },
        "02_synthesis/synthesis_claim_projection.jsonl": {
            "schema_version": "synthesis-claim.v1",
            "status": "approved",
            "decision": decision,
        },
        "02_synthesis/section_contracts.jsonl": {
            "schema_version": "section-contract.v1",
            "status": "approved",
            "decision": decision,
        },
    }
    for relative, fake_row in fake_rows.items():
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(fake_row) + "\n", encoding="utf-8")
    protocol = project / "02_synthesis/comparison_protocol.json"
    protocol.write_text(
        json.dumps(
            {
                "schema_version": "comparison-protocol.v1",
                "status": "approved",
                "decision": decision,
            }
        ),
        encoding="utf-8",
    )
    manuscript = project / "04_manuscript/manuscript.md"
    manuscript.parent.mkdir(parents=True, exist_ok=True)
    manuscript.write_text("# Forged shape\n", encoding="utf-8")
    (manuscript.parent / "manuscript_lineage.v2.json").write_text("{}\n", encoding="utf-8")
    release = project / "05_release/release_snapshot.json"
    release.parent.mkdir(parents=True, exist_ok=True)
    release.write_text(
        json.dumps(
            {
                "status": "SELF_REVIEWED_DRAFT",
                "verified_release_ready": True,
            }
        ),
        encoding="utf-8",
    )
    (release.parent / "self_reviewed_draft.docx").write_bytes(b"forged")

    state = workflow_state(project)

    assert state["active_stage"] == "evidence"
    assert state["paper_evidence_ready"] is False
    assert state["synthesis_ready"] is False
    assert state["manuscript_ready"] is False
    assert state["verified_release_ready"] is False


def test_declared_study_missing_from_source_truth_fails_closed(tmp_path: Path) -> None:
    project = _source_truth_project(tmp_path)
    write_source_truth_bundle(project, "scholarly-a")
    write_parse_quality_gate(project, "scholarly-a")
    _approve_parse(project)
    receipt_path = project / "00_sources/acquisition_final_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["studies"].append(
        {
            "study_id": "scholarly-b",
            "doi": "10.1000/missing",
            "document_role": "MAIN",
            "status": "ACQUIRED",
            "main_pdf": {
                "path": "papers/missing.pdf",
                "sha256": "0" * 64,
                "size_bytes": 1,
            },
        }
    )
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    state = workflow_state(project)

    assert state["active_stage"] == "sources"
    assert state["parse_ready"] is False
    assert state["blockers"] == ["SOURCE_TRUTH_MISSING_OR_INVALID"]


def test_new_route_approved_manuscript_enables_only_internal_export(
    tmp_path: Path, monkeypatch
) -> None:
    from review_writer.project import workflow_projection

    project = tmp_path / "review-projects/approved-manuscript"
    bundle = project / "01_evidence/source_truth/study-a/bundle.json"
    bundle.parent.mkdir(parents=True)
    bundle.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(workflow_projection, "declared_study_ids", lambda _: ["study-a"])
    monkeypatch.setattr(
        workflow_projection,
        "project_parse_quality_state",
        lambda _: {"workflow_can_continue": True, "status": "approved"},
    )
    monkeypatch.setattr(
        workflow_projection,
        "paper_evidence_state",
        lambda _: {"workflow_can_continue": True},
    )
    monkeypatch.setattr(
        workflow_projection,
        "synthesis_state",
        lambda _: {"workflow_can_continue": True},
    )
    monkeypatch.setattr(
        workflow_projection,
        "section_contract_state",
        lambda _: {"workflow_can_continue": True},
    )
    monkeypatch.setattr(
        "review_writer.project.manuscript_v2.manuscript_state",
        lambda _: {"workflow_can_continue": True},
    )

    state = workflow_projection.workflow_state(project)

    assert state["active_stage"] == "final"
    assert state["manuscript_ready"] is True
    assert state["internal_draft_export_ready"] is True
    assert state["verified_release_ready"] is False
    assert state["blockers"] == []
