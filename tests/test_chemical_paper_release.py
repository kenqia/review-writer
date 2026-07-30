from __future__ import annotations

import copy

import pytest


def _safe_summary(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "chemical-paper-safe-summary.v1",
        "route": "chemical-paper-zip-only",
        "study_count": 3,
        "molecule_count": 309,
        "unresolved_field_count": 93,
        "element_review_counts": {
            "not_reviewed": 309,
            "confirmed": 0,
            "corrected": 0,
            "not_applicable": 0,
        },
        "reaction_data_status": "unavailable_not_provided",
    }
    value.update(overrides)
    return value


def _lineage(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "chemical_paper_import_digests": [
            {"study_id": "study-a", "import_digest": "1" * 64, "state_digest": "4" * 64},
            {"study_id": "study-b", "import_digest": "2" * 64, "state_digest": "5" * 64},
            {"study_id": "study-c", "import_digest": "3" * 64, "state_digest": "6" * 64},
        ],
        "chemical_paper_safe_summary": _safe_summary(),
        "chemical_paper_claim_dependencies": [],
    }
    value.update(overrides)
    return value


def test_safe_summary_is_the_only_release_projection_and_retains_pdf_authority() -> None:
    from review_writer.delivery.chemical_paper_release import (
        analyze_chemical_paper_release,
        render_chemical_paper_limitations,
        safe_chemical_paper_projection,
    )

    state = analyze_chemical_paper_release(_lineage())
    projected = safe_chemical_paper_projection(state)

    assert projected == {
        "schema_version": "chemical-paper-safe-summary.v1",
        "route": "chemical-paper-zip-only",
        "study_count": 3,
        "molecule_count": 309,
        "unresolved_field_count": 93,
        "element_review_counts": {
            "not_reviewed": 309,
            "confirmed": 0,
            "corrected": 0,
            "not_applicable": 0,
        },
        "reaction_data_status": "unavailable_not_provided",
    }
    serialized = repr(projected).lower()
    for forbidden in (
        "digest",
        "sha256",
        "path",
        "molblock",
        "molecule_id",
        "study_id",
        "raw_json",
    ):
        assert forbidden not in serialized
    limitation = render_chemical_paper_limitations(state)
    assert "Original PDFs remain the scientific source of truth" in limitation
    assert "manual-export parsing aid, not scientific truth" in limitation
    assert "unavailable/not provided" in limitation
    assert "does not mean zero confirmed reactions" in limitation


def test_absent_optional_binding_remains_not_applicable_without_fabricating_zero() -> None:
    from review_writer.delivery.chemical_paper_release import (
        analyze_chemical_paper_release,
        safe_chemical_paper_projection,
    )

    state = analyze_chemical_paper_release({})

    assert safe_chemical_paper_projection(state) is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update(chemical_paper_import_digests=[]),
        lambda value: value["chemical_paper_import_digests"].append(
            copy.deepcopy(value["chemical_paper_import_digests"][0])
        ),
        lambda value: value["chemical_paper_import_digests"][0].update(
            import_digest="not-a-digest"
        ),
        lambda value: value["chemical_paper_import_digests"][0].update(
            raw_path="/private/export.zip"
        ),
        lambda value: value["chemical_paper_safe_summary"].update(study_count=2),
        lambda value: value["chemical_paper_safe_summary"].update(extra="raw"),
        lambda value: value["chemical_paper_safe_summary"].update(molecule_count=-1),
        lambda value: value["chemical_paper_safe_summary"].update(unresolved_field_count=-1),
        lambda value: value["chemical_paper_safe_summary"].update(
            element_review_counts={
                "not_reviewed": 308,
                "confirmed": 0,
                "corrected": 0,
                "not_applicable": 0,
            }
        ),
        lambda value: value["chemical_paper_safe_summary"].update(
            reaction_data_status="zero_confirmed"
        ),
    ],
)
def test_safe_summary_mismatch_or_invalid_binding_fails_closed(mutate) -> None:
    from review_writer.delivery.chemical_paper_release import (
        ChemicalPaperReleaseError,
        analyze_chemical_paper_release,
    )

    value = copy.deepcopy(_lineage())
    mutate(value)

    with pytest.raises(ChemicalPaperReleaseError, match="CHEMICAL_PAPER_LINEAGE_INVALID"):
        analyze_chemical_paper_release(value)


def test_legacy_full_chemical_lineage_is_rejected_instead_of_projected() -> None:
    from review_writer.delivery.chemical_paper_release import (
        ChemicalPaperReleaseError,
        analyze_chemical_paper_release,
    )

    with pytest.raises(ChemicalPaperReleaseError, match="CHEMICAL_PAPER_LINEAGE_INVALID"):
        analyze_chemical_paper_release(
            {
                "chemical_paper_lineage": {
                    "schema_version": "chemical-paper-lineage-binding.v1",
                    "study_import_bindings": [],
                }
            }
        )


def test_claim_dependencies_are_exact_sorted_internal_bindings_not_safe_projection() -> None:
    from review_writer.delivery.chemical_paper_release import (
        analyze_chemical_paper_release,
        safe_chemical_paper_projection,
    )

    lineage = _lineage(
        chemical_paper_claim_dependencies=[
            {
                "claim_id": "claim-a",
                "study_id": "study-a",
                "molecule_index": 7,
                "required_fields": ["mol_idt", "smiles_expanded"],
                "requires_element_review": False,
                "requires_reaction_data": False,
            }
        ]
    )

    state = analyze_chemical_paper_release(lineage)

    assert state["claim_dependency_count"] == 1
    projected = safe_chemical_paper_projection(state)
    assert "claim_dependency_count" not in projected
    assert "claim-a" not in repr(projected)


@pytest.mark.parametrize(
    "dependency",
    [
        {
            "claim_id": "claim-a",
            "study_id": "study-a",
            "molecule_index": -1,
            "required_fields": [],
            "requires_element_review": False,
            "requires_reaction_data": False,
        },
        {
            "claim_id": "claim-a",
            "study_id": "unknown-study",
            "molecule_index": 0,
            "required_fields": ["mol_idt"],
            "requires_element_review": False,
            "requires_reaction_data": False,
        },
        {
            "claim_id": "claim-a",
            "study_id": "study-a",
            "molecule_index": 0,
            "required_fields": ["elements"],
            "requires_element_review": False,
            "requires_reaction_data": False,
        },
    ],
)
def test_invalid_explicit_claim_dependency_fails_closed(dependency: dict[str, object]) -> None:
    from review_writer.delivery.chemical_paper_release import (
        ChemicalPaperReleaseError,
        analyze_chemical_paper_release,
    )

    lineage = _lineage(chemical_paper_claim_dependencies=[dependency])

    with pytest.raises(ChemicalPaperReleaseError, match="CHEMICAL_PAPER_LINEAGE_INVALID"):
        analyze_chemical_paper_release(lineage)


def test_unresolved_unused_fields_are_issues_not_a_global_hard_fail() -> None:
    from review_writer.delivery.chemical_paper_release import analyze_chemical_paper_release

    state = analyze_chemical_paper_release(_lineage())

    assert "CHEMICAL_FIELDS_UNRESOLVED" in state["issues"]
    assert "hard_fails" not in state


def _claim_lineage() -> dict[str, object]:
    return _lineage(
        chemical_paper_claim_dependencies=[
            {
                "claim_id": "claim-a",
                "study_id": "study-a",
                "molecule_index": 7,
                "required_fields": ["smiles_expanded"],
                "requires_element_review": False,
                "requires_reaction_data": False,
            }
        ]
    )


def _currentness(
    *,
    claim_status: str = "current",
    dependency_status: str = "current",
    field_status: str = "resolved",
    element_review_state: str = "not_reviewed",
    can_release: bool = True,
    blocking_reasons: list[str] | None = None,
) -> dict[str, object]:
    reasons = list(blocking_reasons or [])
    return {
        "schema_version": "chemical-paper-dependency-currentness.v1",
        "lineage_binding_status": "current",
        "claims": [
            {
                "claim_id": "claim-a",
                "status": claim_status,
                "dependencies": [
                    {
                        "study_id": "study-a",
                        "molecule_index": 7,
                        "status": dependency_status,
                        "required_field_statuses": {
                            "smiles_expanded": field_status,
                        },
                        "element_review_state": element_review_state,
                        "reaction_data_status": "unavailable_not_provided",
                        "blocking_reasons": reasons,
                    }
                ],
                "blocking_reasons": reasons,
            }
        ],
        "can_release": can_release,
        "blocking_reasons": reasons,
    }


def test_strict_currentness_allows_only_current_resolved_dependencies() -> None:
    from review_writer.delivery.chemical_paper_release import (
        analyze_chemical_paper_release,
        validate_dependency_currentness,
    )

    state = analyze_chemical_paper_release(_claim_lineage())
    current = validate_dependency_currentness(state, _currentness())

    assert current["can_release"] is True
    assert current["blocked_claim_count"] == 0


def test_strict_currentness_blocks_only_the_explicit_dependent_claim() -> None:
    from review_writer.delivery.chemical_paper_release import (
        analyze_chemical_paper_release,
        validate_dependency_currentness,
    )

    state = analyze_chemical_paper_release(_claim_lineage())
    current = validate_dependency_currentness(
        state,
        _currentness(
            claim_status="needs_review",
            dependency_status="needs_review",
            field_status="unresolved",
            can_release=False,
            blocking_reasons=["CHEMICAL_REQUIRED_FIELD_UNRESOLVED"],
        ),
    )

    assert current["can_release"] is False
    assert current["blocked_claim_count"] == 1
    assert current["blocking_reasons"] == ["CHEMICAL_REQUIRED_FIELD_UNRESOLVED"]


def test_stale_authority_binding_accepts_uninspectable_fields_but_never_releases() -> None:
    from review_writer.delivery.chemical_paper_release import (
        analyze_chemical_paper_release,
        validate_dependency_currentness,
    )

    state = analyze_chemical_paper_release(_claim_lineage())
    reason = "claim-a:chemical_paper:stale"
    currentness = _currentness(
        claim_status="stale",
        dependency_status="stale",
        can_release=False,
        blocking_reasons=[reason],
    )
    currentness["lineage_binding_status"] = "stale"
    currentness["claims"][0]["dependencies"][0]["required_field_statuses"] = {}
    currentness["blocking_reasons"] = ["chemical_paper_lineage:stale", reason]

    result = validate_dependency_currentness(state, currentness)

    assert result["lineage_binding_status"] == "stale"
    assert result["can_release"] is False


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["claims"][0].update(claim_id="claim-b"),
        lambda value: value["claims"][0]["dependencies"][0].update(molecule_index=8),
        lambda value: value["claims"][0]["dependencies"][0].update(
            required_field_statuses={"mol_idt": "resolved"}
        ),
        lambda value: value["claims"][0]["dependencies"][0].update(
            raw_path="/private/state.json"
        ),
        lambda value: value.update(can_release=False),
    ],
)
def test_strict_currentness_rejects_mismatch_or_inconsistent_gate(mutate) -> None:
    from review_writer.delivery.chemical_paper_release import (
        ChemicalPaperReleaseError,
        analyze_chemical_paper_release,
        validate_dependency_currentness,
    )

    state = analyze_chemical_paper_release(_claim_lineage())
    currentness = copy.deepcopy(_currentness())
    mutate(currentness)

    with pytest.raises(ChemicalPaperReleaseError, match="CHEMICAL_PAPER_CURRENTNESS_INVALID"):
        validate_dependency_currentness(state, currentness)
