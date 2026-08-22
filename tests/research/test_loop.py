from __future__ import annotations

import pytest

from review_writer.research import (
    EvidenceMatrix,
    ResearchLoop,
    ResearchQuestion,
    ResearchValidationError,
    ReviewScope,
)


def _scope() -> ReviewScope:
    return ReviewScope(
        topic="photoredox coupling",
        review_questions=(
            ResearchQuestion(question_id="RQ1", text="What is compared?"),
            ResearchQuestion(question_id="RQ2", text="What are the limits?"),
        ),
        inclusion_criteria=("peer reviewed",),
        exclusion_criteria=("editorial",),
    )


def _corpus_records(*, include_duplicate_si: bool = False) -> list[dict[str, object]]:
    records: list[dict[str, object]] = [
        {
            "study_id": "study-a",
            "title": "Alpha study",
            "doi": "10.1000/alpha",
            "source_role": "PRIMARY",
            "lineage_id": "lineage-a",
            "covered_question_ids": ["RQ1"],
            "documents": [
                {
                    "source_id": "study-a-main",
                    "document_role": "MAIN",
                    "sha256": "a" * 64,
                    "locator": {"page": 1},
                },
                {
                    "source_id": "study-a-si",
                    "document_role": "SI",
                    "sha256": "b" * 64,
                    "locator": {"page": 1},
                },
            ],
        },
        {
            "study_id": "study-b",
            "title": "Alpha study duplicate",
            "doi": "doi:10.1000/alpha",
            "source_role": "BACKGROUND",
            "lineage_id": "lineage-b",
            "documents": [
                {
                    "source_id": "study-b-main",
                    "document_role": "MAIN",
                    "sha256": "c" * 64,
                    "locator": {"page": 2},
                },
            ],
        },
    ]
    if include_duplicate_si:
        records.append(
            {
                "study_id": "study-c",
                "title": "Context study",
                "source_role": "METHOD",
                "documents": [
                    {"source_id": "study-c-main", "document_role": "MAIN"},
                    {"source_id": "study-c-si-1", "document_role": "SI"},
                    {"source_id": "study-c-si-2", "document_role": "SI"},
                ],
            }
        )
    return records


def _evidence_records() -> list[dict[str, object]]:
    return [
        {
            "study_id": "study-a",
            "question_id": "RQ1",
            "status": "AI_PROVISIONAL",
            "lineage_id": "lineage-a",
            "statement": "The primary source reports a comparison.",
            "provenance": {
                "source_id": "study-a-main",
                "document_role": "MAIN",
                "locator": {"page": 2, "quote": "reported"},
            },
        },
        {
            "study_id": "study-a",
            "question_id": "RQ1",
            "status": "NON_COMPARABLE",
            "lineage_id": "lineage-a-alt",
            "statement": "A divergent lineage cannot be compared directly.",
            "provenance": {
                "source_id": "study-a-si",
                "document_role": "SI",
                "locator": {"page": 4},
            },
        },
        {
            "study_id": "study-a",
            "question_id": "RQ2",
            "status": "CONFIRMED",
            "lineage_id": "lineage-a",
            "provenance": {
                "source_id": "study-a-main",
                "document_role": "MAIN",
                "locator": {"page": 6},
            },
        },
        {
            "study_id": "study-b",
            "question_id": "RQ1",
            "status": "GAP",
            "lineage_id": "lineage-b",
            "gap_reason": "researcher classification is pending",
        },
    ]


def test_scope_keeps_question_identity_and_rejects_duplicates() -> None:
    scope = _scope()

    assert scope.question_ids == ("RQ1", "RQ2")
    assert scope.review_questions[0].text == "What is compared?"
    assert scope.scope_digest

    with pytest.raises(ResearchValidationError, match="DUPLICATE_QUESTION_ID"):
        ReviewScope(
            topic="topic",
            review_questions=(
                ResearchQuestion("RQ1", "first"),
                ResearchQuestion("RQ1", "second"),
            ),
        )


def test_corpus_preserves_duplicate_lineages_si_state_roles_and_declared_coverage() -> None:
    corpus = ResearchLoop.from_records(
        scope=_scope(),
        corpus=_corpus_records(include_duplicate_si=True),
    ).corpus

    groups = corpus.duplicate_groups()
    assert len(groups) == 1
    assert groups[0].study_ids == ("study-a", "study-b")
    assert groups[0].reason == "doi"
    assert corpus.get("study-a").si_state == "PRESENT"
    assert corpus.get("study-b").si_state == "MISSING"
    assert corpus.get("study-c").si_state == "DUPLICATE"
    assert [item.study_id for item in corpus.view(source_role="method")] == ["study-c"]
    assert corpus.coverage(_scope())["RQ1"]["declared_study_ids"] == ("study-a",)


def test_evidence_matrix_adds_gaps_and_supports_view_filter_and_provenance() -> None:
    loop = ResearchLoop.from_records(
        scope=_scope(),
        corpus=_corpus_records(),
        evidence=_evidence_records(),
    )

    provisional = loop.matrix.view(
        question_id="RQ1",
        status="AI_PROVISIONAL",
        source_role="PRIMARY",
    )
    assert [row.study_id for row in provisional] == ["study-a"]
    assert [row.status for row in loop.matrix.view(include_gaps=False)] == [
        "AI_PROVISIONAL",
        "NON_COMPARABLE",
        "CONFIRMED",
    ]
    assert [row.status for row in loop.matrix.gaps()] == ["GAP", "GAP"]
    assert [item["source_id"] for item in loop.matrix.provenance_for("study-a", "RQ1")] == [
        "study-a-main",
        "study-a-si",
    ]
    assert loop.matrix.coverage()["RQ1"]["gap_study_ids"] == ("study-b",)
    assert loop.to_dict()["matrix"]["rows"][1]["status"] == "NON_COMPARABLE"


def test_evidence_matrix_requires_provenance_for_non_gap_evidence() -> None:
    with pytest.raises(ResearchValidationError, match="PROVENANCE_REQUIRED"):
        EvidenceMatrix.from_records(
            scope=_scope(),
            corpus=ResearchLoop.from_records(scope=_scope(), corpus=_corpus_records()).corpus,
            evidence=[
                {
                    "study_id": "study-a",
                    "question_id": "RQ1",
                    "status": "AI_PROVISIONAL",
                }
            ],
        )


def test_matrix_rejects_unknown_question_and_exact_duplicate_cell() -> None:
    corpus = ResearchLoop.from_records(scope=_scope(), corpus=_corpus_records()).corpus
    with pytest.raises(ResearchValidationError, match="UNKNOWN_REVIEW_QUESTION"):
        EvidenceMatrix.from_records(
            scope=_scope(),
            corpus=corpus,
            evidence=[
                {
                    "study_id": "study-a",
                    "question_id": "RQ9",
                    "status": "GAP",
                    "gap_reason": "unknown question",
                }
            ],
        )

    record = _evidence_records()[0]
    with pytest.raises(ResearchValidationError, match="DUPLICATE_EVIDENCE_ROW"):
        EvidenceMatrix.from_records(
            scope=_scope(),
            corpus=corpus,
            evidence=[record, dict(record)],
        )
