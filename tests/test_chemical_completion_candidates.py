from __future__ import annotations

import json
from pathlib import Path

import pytest

from review_writer.project.chemical_completion import apply_chemical_completion_batch, chemical_completion_state
from review_writer.project.chemical_completion_candidates import project_chemical_completion_candidates
from review_writer.project.chemical_paper import import_chemical_paper
from review_writer.project.content_agent_handoff import (
    ContentAgentError,
    build_content_task_package,
    import_content_agent_result,
)
from review_writer.project.dual_source import write_dual_source_binding
from review_writer.project.source_truth import canonical_digest, load_source_truth_bundle
from review_writer.delivery import dual_parse_release
from test_chemical_paper_import import ACTOR, v2000, write_chemical_zip
from test_dual_source import dual_project


def _request(project: Path, study_id: str = "scholarly-a") -> dict[str, object]:
    return {
        "schema_version": "content-agent-request.v1",
        "request_kind": "chemical_completion_candidates",
        "project_id": project.name,
        "target_ids": [study_id],
        "field_dependencies": [],
        "reason": "Researcher requested traceable Chemical Completion candidates.",
    }


def _blocked_project(tmp_path: Path) -> Path:
    project = dual_project(tmp_path, chemical=False)
    bundle = load_source_truth_bundle(project, "scholarly-a")
    archive = write_chemical_zip(
        tmp_path / "chemical.zip",
        pages=1,
        molecules=[
            {
                "mol_id": "mol-a",
                "page_idx": 0,
                "bbox_normalized": [0.1, 0.2, 0.3, 0.4],
                "smiles_expanded": "CO",
                "smiles_unexpanded": "CO",
                "mol_idt": "compound 1",
                "mol_block": v2000(),
            },
            {
                "mol_id": "mol-b",
                "page_idx": 0,
                "bbox_normalized": [0.2, 0.3, 0.5, 0.6],
                "smiles_expanded": "",
                "smiles_unexpanded": "",
                "mol_idt": "compound 2",
                "mol_block": v2000(("N",)),
            },
        ],
    )
    import_chemical_paper(
        project,
        "scholarly-a",
        bundle["sources"][0]["pdf"]["sha256"],
        archive,
        ACTOR,
    )
    return project


def _result(package: dict[str, object], project: Path) -> dict[str, object]:
    candidate = {
        "study_id": "scholarly-a",
        "molecule_index": 1,
        "field": "resolved_smiles",
        "value": "CO",
        "confidence": 0.82,
        "provenance": {"source": "original_pdf_structure", "method": "visible_structure_reading"},
        "pdf_locator": {"page": 1, "figure_label": "Figure 2"},
        "reason": "The visible structure is consistent with the proposed connectivity.",
    }
    result = {
        "schema_version": "content-agent-result.v1",
        "request_kind": "chemical_completion_candidates",
        "project_id": project.name,
        "target_ids": ["scholarly-a"],
        "task_package_digest": package["task_package_digest"],
        "agent_label": "chemical-completion-agent-scholarly-a",
        "content": {"chemical_completion_candidates": [candidate]},
    }
    result["result_digest"] = canonical_digest(result)
    return result


def test_candidate_package_allows_pending_reconciliation_without_evidence_inputs(
    tmp_path: Path,
) -> None:
    project = _blocked_project(tmp_path)
    write_dual_source_binding(project, "scholarly-a")

    package = build_content_task_package(project, _request(project))

    kinds = {row["kind"] for rows in package["inputs"].values() for row in rows}
    assert kinds == {
        "source_asset:pdf",
        "generic_parse_safe_projection",
        "parse_quality_safe_projection",
        "chemical_completion_safe_projection",
    }
    encoded_inputs = json.dumps(package["inputs"])
    assert "canonical_markdown" not in encoded_inputs
    assert "content_list" not in encoded_inputs
    assert "history" not in encoded_inputs
    assert "mol_block" not in encoded_inputs
    assert "reconciliation" not in package["inputs"]


def test_candidate_result_import_is_staged_and_never_approves_authoritative_state(
    tmp_path: Path,
) -> None:
    project = _blocked_project(tmp_path)
    write_dual_source_binding(project, "scholarly-a")
    package = build_content_task_package(project, _request(project))
    before = chemical_completion_state(project, "scholarly-a")

    imported = import_content_agent_result(project, _result(package, project))

    assert imported["request_kind"] == "chemical_completion_candidates"
    assert imported["changed_files"]
    assert any("chemical_completion_candidates" in path for path in imported["changed_files"])
    after = chemical_completion_state(project, "scholarly-a")
    assert after["blocked_count"] == before["blocked_count"]
    assert after["ai_provisional_count"] == before["ai_provisional_count"]
    assert after["history"] == before["history"] == []
    assert list((project / "01_evidence/chemical_completion_candidates").rglob("*.json"))


def test_candidate_result_rejects_authoritative_decision_and_writes_nothing(
    tmp_path: Path,
) -> None:
    project = _blocked_project(tmp_path)
    write_dual_source_binding(project, "scholarly-a")
    package = build_content_task_package(project, _request(project))
    result = _result(package, project)
    result["content"]["chemical_completion_candidates"][0]["decision"] = {"action": "approve"}
    result["result_digest"] = canonical_digest({key: value for key, value in result.items() if key != "result_digest"})

    with pytest.raises(ContentAgentError, match="RESULT_INVALID"):
        import_content_agent_result(project, result)

    assert not (project / "01_evidence/chemical_completion_candidates").exists()


def test_candidate_projection_is_invalidated_after_researcher_adopts_the_row(
    tmp_path: Path,
) -> None:
    project = _blocked_project(tmp_path)
    write_dual_source_binding(project, "scholarly-a")
    package = build_content_task_package(project, _request(project))
    import_content_agent_result(project, _result(package, project))
    assert project_chemical_completion_candidates(project, "scholarly-a")[1]
    gate = chemical_completion_state(project, "scholarly-a")

    apply_chemical_completion_batch(project, "scholarly-a", {
        "version_token": gate["version_token"],
        "actor_type": "simulated_researcher_agent",
        "actor_label": "simulated_researcher",
        "corrections": [{
            "molecule_index": 1,
            "field": "resolved_smiles",
            "value": "CO",
            "reason": "Researcher confirmed the visible PDF structure.",
            "pdf_locator": {"page": 1},
            "resolution_status": "AI_PROVISIONAL",
            "confidence": 0.82,
            "provenance": {"source": "original_pdf_structure"},
        }],
    })

    assert project_chemical_completion_candidates(project, "scholarly-a") == {}


def test_paper_evidence_package_still_requires_reconciliation(tmp_path: Path) -> None:
    project = dual_project(tmp_path)
    write_dual_source_binding(project, "scholarly-a")
    request = _request(project)
    request.update({
        "request_kind": "paper_evidence",
        "reason": "Evidence candidate request.",
    })

    with pytest.raises(ContentAgentError, match="PARSE_RECONCILIATION_MISSING"):
        build_content_task_package(project, request)


def test_completion_http_refreshes_every_declared_core_study(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _blocked_project(tmp_path)
    write_dual_source_binding(project, "scholarly-a")
    gate = chemical_completion_state(project, "scholarly-a")
    calls: list[str] = []

    monkeypatch.setattr(
        "review_writer.project.chemical_completion.apply_chemical_completion_batch",
        lambda *_args, **_kwargs: {"status": "applied"},
    )
    monkeypatch.setattr(
        dual_parse_release,
        "declared_study_ids",
        lambda _root: ["scholarly-a", "scholarly-b", "scholarly-c"],
    )
    monkeypatch.setattr(
        dual_parse_release,
        "study_source_tier",
        lambda _root, _study_id: "core",
    )

    def refresh(_root: Path, study_id: str) -> dict[str, object]:
        calls.append(study_id)
        return {"status": "current", "stage": "reconciliation"}

    monkeypatch.setattr(dual_parse_release, "refresh_dual_parse_derived_state", refresh)
    result = dual_parse_release.apply_chemical_completion_http(project, {
        "study_id": "scholarly-a",
        "version_token": gate["version_token"],
        "actor_type": "simulated_researcher_agent",
        "actor_label": "simulated_researcher",
        "corrections": [{
            "molecule_index": 1,
            "field": "resolved_smiles",
            "value": "CO",
            "reason": "PDF supports the candidate.",
            "pdf_locator": {"page": 1},
            "resolution_status": "AI_PROVISIONAL",
            "confidence": 0.8,
            "provenance": {"source": "original_pdf"},
        }],
    })

    assert calls == ["scholarly-a", "scholarly-b", "scholarly-c"]
    assert [row["study_id"] for row in result["derived_refreshes"]] == calls
