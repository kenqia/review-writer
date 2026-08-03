from __future__ import annotations

from pathlib import Path

import pytest

from review_writer.project.chemical_completion import (
    ChemicalCompletionError,
    apply_chemical_completion_batch,
    chemical_completion_state,
    require_honest_progressive_projection,
)
from review_writer.project.chemical_paper import (
    ChemicalPaperError,
    chemical_dependency_state,
    chemical_paper_dependency_currentness,
    chemical_paper_manuscript_bindings,
    correct_chemical_paper_field,
    load_chemical_paper_state,
)
from review_writer.project.paper_evidence import PaperEvidenceError, build_honest_progressive_summary
from review_writer.project.synthesis import partition_honest_progressive_evidence
from test_chemical_completion import _large_completion_project, completion_project


HUMAN = {"actor_type": "human_researcher", "actor_label": "researcher"}


def _resolved_smiles_dependency(project: Path) -> list[dict[str, object]]:
    state = load_chemical_paper_state(project, "scholarly-a")
    molecule = state["molecules"][0]
    return [
        {
            "study_id": "scholarly-a",
            "molecule_id": molecule["molecule_id"],
            "molecule_digest": molecule["molecule_digest"],
            "chemical_paper_import_digest": state["current_import_digest"],
            "required_fields": ["resolved_smiles"],
        }
    ]


def test_ai_provisional_has_traceability_and_never_enters_exact_partition() -> None:
    row = {
        "study_id": "paper-a",
        "molecule_id": "mol-ai",
        "status": "AI_PROVISIONAL",
        "value": "CO",
        "confidence": 0.72,
        "source_id": "source-a",
        "pdf_locator": {"page": 2, "section_or_item": "Scheme 1"},
        "provenance": {"source": "original_pdf", "evidence_id": "candidate-1"},
    }

    summary = build_honest_progressive_summary([row], core_molecule_count=1)
    projection = partition_honest_progressive_evidence([row])

    assert summary["ai_provisional_count"] == 1
    assert summary["traceability"][0]["confidence"] == 0.72
    assert summary["traceability"][0]["pdf_locator"]["page"] == 2
    assert summary["traceability"][0]["provenance"]["source"] == "original_pdf"
    assert projection["exact_conclusions"] == []
    assert projection["internal_comparison"][0]["provisional"] is True


@pytest.mark.parametrize("missing", ["confidence", "pdf_locator", "provenance"])
def test_ai_provisional_missing_traceability_is_rejected(missing: str) -> None:
    row = {
        "study_id": "paper-a",
        "molecule_id": "mol-ai",
        "status": "AI_PROVISIONAL",
        "value": "CO",
        "confidence": 0.72,
        "source_id": "source-a",
        "pdf_locator": {"page": 2},
        "provenance": {"source": "original_pdf"},
    }
    row.pop(missing)

    with pytest.raises(PaperEvidenceError, match="HONEST_PROGRESSIVE_PROVISIONAL_PROVENANCE_REQUIRED"):
        build_honest_progressive_summary([row], core_molecule_count=1)


def test_blocked_evidence_requires_null_value_and_gap_reason() -> None:
    row = {
        "study_id": "paper-a",
        "molecule_id": "mol-blocked",
        "status": "BLOCKED",
        "value": None,
        "gap_reason": "The source does not support a unique structure.",
    }

    projection = partition_honest_progressive_evidence([row])

    assert projection["exact_conclusions"] == []
    assert projection["internal_comparison"] == []
    assert projection["limitation_disclosures"] == [
        {
            "study_id": "paper-a",
            "molecule_id": "mol-blocked",
            "status": "BLOCKED",
            "value": None,
            "gap_reason": "The source does not support a unique structure.",
            "source_id": None,
            "pdf_locator": {},
            "provenance": {},
        }
    ]


def test_exact_projection_rejects_provisional_even_when_coverage_reaches_threshold(
    tmp_path: Path,
) -> None:
    project = _large_completion_project(tmp_path, candidate_count=248)
    gate = chemical_completion_state(project, "scholarly-a")

    assert gate["ai_provisional_count"] == 248
    assert gate["coverage_ratio"] >= 0.8

    with pytest.raises(ChemicalCompletionError, match="CHEMICAL_COMPLETION_INCOMPLETE"):
        require_honest_progressive_projection(
            project,
            "scholarly-a",
            allow_provisional=False,
        )


def test_confirmed_resolved_smiles_cannot_be_overwritten_by_direct_correction(
    tmp_path: Path,
) -> None:
    project = completion_project(tmp_path)
    gate = chemical_completion_state(project, "scholarly-a")
    first = apply_chemical_completion_batch(
        project,
        "scholarly-a",
        {
            "version_token": gate["version_token"],
            **HUMAN,
            "corrections": [
                {
                    "molecule_index": 0,
                    "field": "resolved_smiles",
                    "value": "CO",
                    "resolution_status": "CONFIRMED",
                    "reason": "Researcher confirmed the structure against the original PDF.",
                    "pdf_locator": {"page": 1},
                }
            ],
        },
    )
    before = load_chemical_paper_state(project, "scholarly-a")

    with pytest.raises(ChemicalPaperError, match="CONFIRMED_FIELD_IMMUTABLE"):
        correct_chemical_paper_field(
            project,
            study_id="scholarly-a",
            molecule_index=0,
            field="resolved_smiles",
            value="CC",
            actor=HUMAN,
            reason="Attempted replacement after confirmation.",
            pdf_locator={"page": 1},
            version_token=first["version_token"],
            resolution_status="CONFIRMED",
        )

    after = load_chemical_paper_state(project, "scholarly-a")
    assert after == before


def test_chemical_dependencies_do_not_treat_provisional_smiles_as_exact(
    tmp_path: Path,
) -> None:
    project = completion_project(tmp_path)
    gate = chemical_completion_state(project, "scholarly-a")
    apply_chemical_completion_batch(
        project,
        "scholarly-a",
        {
            "version_token": gate["version_token"],
            "actor_type": "simulated_researcher_agent",
            "actor_label": "candidate-agent",
            "corrections": [
                {
                    "molecule_index": 0,
                    "field": "resolved_smiles",
                    "value": "CO",
                    "resolution_status": "AI_PROVISIONAL",
                    "confidence": 0.72,
                    "provenance": {"source": "original_pdf", "evidence_id": "candidate-1"},
                    "reason": "Candidate is traceable to the original PDF.",
                    "pdf_locator": {"page": 1},
                }
            ],
        },
    )

    dependency = chemical_dependency_state(
        project,
        "evidence-provisional",
        _resolved_smiles_dependency(project),
    )
    bindings = chemical_paper_manuscript_bindings(project)
    currentness = chemical_paper_dependency_currentness(
        project,
        import_digests=bindings["chemical_paper_import_digests"],
        claim_dependencies=[
            {
                "claim_id": "claim-provisional",
                "study_id": "scholarly-a",
                "molecule_index": 0,
                "required_fields": ["resolved_smiles"],
                "requires_element_review": False,
                "requires_reaction_data": False,
            }
        ],
    )

    assert dependency["dependency_status"] == "blocked_unresolved"
    assert dependency["gaps"] == [
        "scholarly-a/mol-a:resolved_smiles:provisional_not_confirmed"
    ]
    assert currentness["can_release"] is False
    assert currentness["claims"][0]["status"] == "needs_review"
    assert currentness["claims"][0]["blocking_reasons"] == [
        "claim-provisional:resolved_smiles:provisional_not_confirmed"
    ]
