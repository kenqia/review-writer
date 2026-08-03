from pathlib import Path
import json

import pytest

from review_writer.project.section_contract import SectionContractError, register_section_contracts
from review_writer.project.synthesis import SynthesisError, register_synthesis_candidates, register_comparison_protocol, register_coverage_map


def test_synthesis_requires_approved_comparison_protocol(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    with pytest.raises(SynthesisError, match="COMPARISON_PROTOCOL_NOT_APPROVED"):
        register_synthesis_candidates(project, {"synthesis_id": "s1"})


def test_comparison_protocol_requires_explicit_fields(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    with pytest.raises(SynthesisError, match="COMPARISON_PROTOCOL_INVALID"):
        register_comparison_protocol(project, {"comparison_id": "cmp"})


def test_section_contract_requires_counterevidence_and_figure_plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr("review_writer.project.section_contract.synthesis_state", lambda _: {"workflow_can_continue": True, "projection_digest": "a" * 64})
    with pytest.raises(SectionContractError, match="SECTION_CONTRACT_INVALID"):
        register_section_contracts(project, {"section_id": "s1", "research_question": "q"})


def test_single_study_claim_cannot_claim_consensus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr("review_writer.project.synthesis.comparison_protocol_state", lambda _: {"workflow_can_continue": True, "protocol_digest": "b" * 64})
    monkeypatch.setattr("review_writer.project.synthesis.paper_evidence_state", lambda _: {"projection_digest": "c" * 64, "rows": [{"evidence_id": "e1", "study_id": "study-a", "status": "approved"}]})
    with pytest.raises(SynthesisError, match="SINGLE_STUDY_OVERGENERALIZATION"):
        register_synthesis_candidates(project, {"synthesis_id": "s1", "proposition": "The field generally establishes this.", "comparison_axis": "yield", "supporting_evidence_ids": ["e1"], "applicability_boundary": "this study", "mechanism_evidence_grade": "low", "uncertainty": "high", "risk_class": "scope", "single_study": True})


def test_rejected_evidence_cannot_enter_synthesis(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr("review_writer.project.synthesis.comparison_protocol_state", lambda _: {"workflow_can_continue": True, "protocol_digest": "b" * 64})
    monkeypatch.setattr("review_writer.project.synthesis.paper_evidence_state", lambda _: {"projection_digest": "c" * 64, "rows": [{"evidence_id": "e1", "study_id": "study-a", "status": "rejected"}, {"evidence_id": "e2", "study_id": "study-b", "status": "approved"}]})
    with pytest.raises(SynthesisError, match="SYNTHESIS_EVIDENCE_NOT_APPROVED"):
        register_synthesis_candidates(project, {"synthesis_id": "s1", "proposition": "Bounded comparison.", "comparison_axis": "yield", "supporting_evidence_ids": ["e1", "e2"], "applicability_boundary": "these studies", "mechanism_evidence_grade": "low", "uncertainty": "high", "risk_class": "scope"})


def test_coverage_map_requires_approved_protocol(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr("review_writer.project.synthesis.comparison_protocol_state", lambda _: {"workflow_can_continue": False})
    with pytest.raises(SynthesisError, match="COMPARISON_PROTOCOL_NOT_APPROVED"):
        register_coverage_map(project, {"comparison_id": "cmp", "axes": [{}]})


def test_synthesis_state_marks_claim_stale_when_protocol_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from review_writer.project.synthesis import synthesis_state
    from review_writer.project.source_truth import canonical_digest

    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr("review_writer.project.synthesis.comparison_protocol_state", lambda _: {"workflow_can_continue": True, "protocol_digest": "b" * 64})
    monkeypatch.setattr("review_writer.project.synthesis.paper_evidence_state", lambda _: {"projection_digest": "c" * 64, "rows": []})
    claim_dir = project / "02_synthesis"
    claim_dir.mkdir()
    claim = {
        "synthesis_id": "s1",
        "comparison_protocol_digest": "a" * 64,
        "paper_evidence_projection_digest": "c" * 64,
    }
    claim["synthesis_digest"] = canonical_digest({k: v for k, v in claim.items() if k != "synthesis_digest"})
    (claim_dir / "synthesis_claim_projection.jsonl").write_text(json.dumps(claim) + "\n", encoding="utf-8")
    assert synthesis_state(project)["rows"][0]["reason_code"] == "SYNTHESIS_PROTOCOL_STALE"


def test_candidate_cannot_supply_approval_decision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr("review_writer.project.synthesis.comparison_protocol_state", lambda _: {"workflow_can_continue": True, "protocol_digest": "b" * 64})
    monkeypatch.setattr("review_writer.project.synthesis.paper_evidence_state", lambda _: {"projection_digest": "c" * 64, "rows": []})
    with pytest.raises(SynthesisError, match="SYNTHESIS_DECISION_INVALID"):
        register_synthesis_candidates(project, {"synthesis_id": "s1", "decision": {"action": "approve"}})


def test_section_candidate_cannot_supply_approval_decision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("review_writer.project.section_contract.synthesis_state", lambda _: {"workflow_can_continue": True, "projection_digest": "a" * 64})
    project = tmp_path / "project"
    project.mkdir()
    with pytest.raises(SectionContractError, match="SECTION_CONTRACT_DECISION_INVALID"):
        register_section_contracts(project, {"section_id": "s1", "decision": {"action": "approve"}})
