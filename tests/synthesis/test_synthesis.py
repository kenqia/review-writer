from __future__ import annotations

import copy

import pytest

from review_writer.synthesis import SynthesisError, synthesize


def _evidence(
    evidence_id: str,
    source_id: str,
    comparison_key: str,
    position: object,
    *,
    status: str = "CONFIRMED",
    relation: str = "supports",
    source_role: str = "PRIMARY_RESEARCH",
    study_id: str | None = None,
    **extra: object,
) -> dict[str, object]:
    row: dict[str, object] = {
        "evidence_id": evidence_id,
        "source_id": source_id,
        "study_id": study_id or source_id,
        "source_role": source_role,
        "status": status,
        "comparison_key": comparison_key,
        "position": position,
        "relation": relation,
        "locator": {
            "source_mode": "original_pdf_manual",
            "page": 1,
            "section_or_item": "results",
            "figure_or_table": None,
            "exact_quote": f"quote for {evidence_id}",
        },
    }
    row.update(extra)
    return row


def test_synthesize_builds_consensus_and_difference_with_source_lineage() -> None:
    evidence = [
        _evidence("E1", "S1", "capture-window", "narrow"),
        _evidence(
            "E2",
            "S2",
            "capture-window",
            "narrow",
            status="AI_PROVISIONAL",
        ),
        _evidence("E3", "S1", "selectivity", "A"),
        _evidence("E4", "S2", "selectivity", "B"),
    ]

    result = synthesize(evidence)
    rows = {row["comparison_key"]: row for row in result["rows"]}

    assert rows["capture-window"]["classification"] == "consensus"
    assert rows["capture-window"]["synthesis_status"] == "AI_PROVISIONAL"
    assert rows["capture-window"]["supporting_evidence_ids"] == ["E1", "E2"]
    assert rows["selectivity"]["classification"] == "difference"
    assert rows["selectivity"]["position_groups"][0]["evidence_ids"]
    assert {item["source_role"] for item in rows["capture-window"]["lineage"]} == {
        "PRIMARY_RESEARCH"
    }


def test_explicit_counter_evidence_is_traceable_as_conflict() -> None:
    result = synthesize(
        [
            _evidence("E1", "S1", "mechanism", "path-A"),
            _evidence(
                "E2",
                "S2",
                "mechanism",
                "path-B",
                relation="counter",
                status="AI_PROVISIONAL",
            ),
        ]
    )

    row = result["rows"][0]
    assert row["classification"] == "conflict"
    assert row["counter_evidence_ids"] == ["E2"]
    assert row["conflict_evidence_ids"] == ["E2"]
    assert row["synthesis_status"] == "AI_PROVISIONAL"


def test_non_comparable_and_missing_keys_remain_explicit_gaps() -> None:
    result = synthesize(
        [
            _evidence(
                "E1",
                "S1",
                "conditions",
                "not-comparable",
                status="NON_COMPARABLE",
                source_role="PRIMARY_RESEARCH",
            ),
            _evidence(
                "E2",
                "S2",
                "conditions",
                "review-only",
                source_role="BACKGROUND_REVIEW",
            ),
        ],
        expected_keys=["conditions", "mechanism"],
    )
    rows = {row["comparison_key"]: row for row in result["rows"]}

    assert rows["conditions"]["classification"] == "NON_COMPARABLE"
    assert rows["conditions"]["synthesis_status"] == "AI_PROVISIONAL"
    assert rows["conditions"]["non_comparable_evidence_ids"] == ["E1"]
    assert rows["conditions"]["context_only_evidence_ids"] == ["E2"]
    assert rows["mechanism"]["classification"] == "GAP"
    assert rows["mechanism"]["synthesis_status"] == "AI_PROVISIONAL"
    assert rows["mechanism"]["reason_code"] == "NO_TRACEABLE_EVIDENCE"
    assert result["workflow_can_continue"] is False


def test_background_only_evidence_does_not_fill_independent_primary_coverage() -> None:
    result = synthesize(
        [
            _evidence("E1", "S1", "scope", "broad"),
            _evidence(
                "E2",
                "S2",
                "scope",
                "broad",
                source_role="BACKGROUND_REVIEW",
            ),
        ]
    )

    row = result["rows"][0]
    assert row["classification"] == "GAP"
    assert row["reason_code"] == "INSUFFICIENT_INDEPENDENT_PRIMARY_SOURCES"
    assert row["context_only_evidence_ids"] == ["E2"]


def test_synthesis_is_deterministic_and_does_not_mutate_input() -> None:
    evidence = [
        _evidence("E2", "S2", "scope", "broad"),
        _evidence("E1", "S1", "scope", "broad"),
    ]
    original = copy.deepcopy(evidence)

    first = synthesize(evidence)
    second = synthesize(list(reversed(evidence)))

    assert evidence == original
    assert first == second
    assert len(first["projection_digest"]) == 64


def test_synthesis_rejects_duplicate_ids_and_missing_locator() -> None:
    duplicate = _evidence("E1", "S1", "scope", "broad")
    with pytest.raises(SynthesisError, match="EVIDENCE_ID_DUPLICATE"):
        synthesize([duplicate, copy.deepcopy(duplicate)])

    untraceable = _evidence("E2", "S2", "scope", "broad")
    del untraceable["locator"]
    with pytest.raises(SynthesisError, match="TRACEABILITY_REQUIRED"):
        synthesize([untraceable])


@pytest.mark.parametrize(
    ("field", "value", "error_code"),
    [
        ("status", "PROMOTED", "STATUS_INVALID"),
        ("relation", "inferred", "RELATION_INVALID"),
    ],
)
def test_synthesis_rejects_invalid_status_and_relation(
    field: str, value: str, error_code: str
) -> None:
    row = _evidence("E1", "S1", "scope", "broad")
    row[field] = value

    with pytest.raises(SynthesisError, match=error_code):
        synthesize([row])
