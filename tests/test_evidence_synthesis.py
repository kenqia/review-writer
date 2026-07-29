from pathlib import Path

import pytest

from review_writer.project.section_contract import SectionContractError, register_section_contracts
from review_writer.project.synthesis import SynthesisError, register_synthesis_candidates, register_comparison_protocol


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
