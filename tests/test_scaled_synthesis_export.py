from __future__ import annotations

import json
from pathlib import Path

import pytest

from review_writer.project.source_truth import canonical_digest
from review_writer.project.verification_decision import verification_decision
from review_writer.project.synthesis import (
    FROZEN_REVIEW_QUESTIONS_DIGEST,
    authoritative_synthesis_question_bindings,
    register_synthesis_candidates,
    synthesis_state,
    SynthesisError,
    register_comparison_protocol,
)


FROZEN_QUESTIONS = [
    "主要键组合、反应模式及活化策略是什么？",
    "条件如何影响表现，哪些结果不可直接比较？",
    "底物范围、耐受性、选择性和局限是什么？",
    "机制证据处于什么层级，作者解释之间有哪些冲突？",
    "通用性、选择性、放大、资源效率和机制确定性还存在哪些缺口？",
]
QUESTION_IDS = [f"RQ{index}" for index in range(1, 6)]
PROTOCOL_DIGEST = "a" * 64
EVIDENCE_DIGEST = "b" * 64


def _protocol() -> dict[str, object]:
    return {
        "comparison_id": "authoritative-comparison",
        "comparison_objects": ["study-a", "study-b"],
        "axes": ["reported outcome"],
        "normalization_rules": ["Keep source units."],
        "missing_value_policy": "Mark missing values.",
        "incomparability_rules": ["Do not force unlike measures."],
        "counterevidence_rules": ["Retain limitations."],
        "claim_strength": "bounded",
        "authoritative_run": True,
    }


def _question_digest(question_id: str) -> str:
    index = QUESTION_IDS.index(question_id)
    return canonical_digest(
        {"question_id": question_id, "question": FROZEN_QUESTIONS[index]}
    )


def _artifact(question_id: str, *, decision: bool = True) -> dict[str, object]:
    row: dict[str, object] = {
        "schema_version": "synthesis-claim.v1",
        "synthesis_id": f"synthesis-{question_id}",
        "proposition": f"Bounded synthesis for {question_id}.",
        "comparison_axis": "reported outcome",
        "supporting_evidence_ids": [f"evidence-{question_id}"],
        "counter_evidence_ids": [],
        "applicability_boundary": "The represented evidence only.",
        "mechanism_evidence_grade": "low",
        "uncertainty": "Bounded.",
        "risk_class": "scope",
        "single_study": True,
        "authoritative_run": True,
        "review_question_id": question_id,
        "review_question_digest": _question_digest(question_id),
        "review_questions_digest": FROZEN_REVIEW_QUESTIONS_DIGEST,
        "paper_evidence_projection_digest": EVIDENCE_DIGEST,
        "comparison_protocol_digest": PROTOCOL_DIGEST,
        "decision": None,
    }
    row["review_question_lineage_digest"] = canonical_digest(
        {
            "synthesis_id": row["synthesis_id"],
            "review_question_id": row["review_question_id"],
            "review_question_digest": row["review_question_digest"],
            "review_questions_digest": row["review_questions_digest"],
            "comparison_protocol_digest": row["comparison_protocol_digest"],
            "paper_evidence_projection_digest": row[
                "paper_evidence_projection_digest"
            ],
        }
    )
    row["synthesis_digest"] = canonical_digest(row)
    if decision:
        row["decision"] = verification_decision(
            actor_type="human_researcher",
            actor_label="focused-regression",
            action="approve",
            reason="Explicit bounded disposition.",
            bound_object_digest=row["synthesis_digest"],
        )
    return row


def _write_artifacts(project: Path, rows: list[dict[str, object]]) -> None:
    directory = project / "02_synthesis"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "synthesis_claim_projection.jsonl").write_text(
        "".join(f"{json.dumps(row, ensure_ascii=False)}\n" for row in rows),
        encoding="utf-8",
    )


def _authoritative_state_patches(monkeypatch: pytest.MonkeyPatch) -> None:
    protocol = {
        "workflow_can_continue": True,
        "protocol_digest": PROTOCOL_DIGEST,
        "authoritative_run": True,
        "review_questions": FROZEN_QUESTIONS,
        "review_questions_digest": FROZEN_REVIEW_QUESTIONS_DIGEST,
        "value": {
            "authoritative_run": True,
            "review_questions": FROZEN_QUESTIONS,
            "review_questions_digest": FROZEN_REVIEW_QUESTIONS_DIGEST,
        },
    }
    monkeypatch.setattr(
        "review_writer.project.synthesis.comparison_protocol_state",
        lambda _: protocol,
    )
    monkeypatch.setattr(
        "review_writer.project.synthesis.paper_evidence_state",
        lambda _: {"projection_digest": EVIDENCE_DIGEST, "rows": []},
    )


def test_authoritative_synthesis_and_release_require_the_five_frozen_questions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(
        "review_writer.project.synthesis.paper_evidence_state",
        lambda _: {"projection_digest": "a" * 64},
    )

    with pytest.raises(SynthesisError, match="REVIEW_QUESTIONS_REQUIRED"):
        register_comparison_protocol(project, _protocol())

    registered = register_comparison_protocol(
        project, {**_protocol(), "review_questions": FROZEN_QUESTIONS}
    )
    assert registered["authoritative_run"] is True
    assert registered["review_questions"] == FROZEN_QUESTIONS

    from review_writer.delivery.project_release import (
        ProjectReleaseError,
        _authoritative_review_question_binding,
        validate_authoritative_review_questions,
    )

    assert validate_authoritative_review_questions(registered)["review_questions"] == FROZEN_QUESTIONS
    lineage = {
        "authoritative_run": True,
        "review_questions": FROZEN_QUESTIONS,
        "review_questions_digest": registered["review_questions_digest"],
    }
    with pytest.raises(
        ProjectReleaseError, match="SYNTHESIS_REVIEW_QUESTION_MISSING"
    ):
        _authoritative_review_question_binding(project, lineage)
    monkeypatch.setattr(
        "review_writer.delivery.project_release.synthesis_state",
        lambda _: {
            "workflow_can_continue": True,
            "question_gate": {
                "workflow_can_continue": True,
                "reason_code": "SYNTHESIS_REVIEW_QUESTIONS_APPROVED",
            },
        },
    )
    assert _authoritative_review_question_binding(project, lineage) == lineage
    tampered = {**registered, "review_questions": list(reversed(FROZEN_QUESTIONS))}
    with pytest.raises(ProjectReleaseError, match="REVIEW_QUESTIONS_INVALID"):
        validate_authoritative_review_questions(tampered)


def test_authoritative_synthesis_requires_current_one_to_one_five_question_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _authoritative_state_patches(monkeypatch)
    _write_artifacts(project, [_artifact(question_id) for question_id in QUESTION_IDS])

    state = synthesis_state(project)

    assert state["workflow_can_continue"] is True
    assert state["question_gate"]["reason_code"] == "SYNTHESIS_REVIEW_QUESTIONS_APPROVED"
    assert [row["review_question_id"] for row in state["rows"]] == QUESTION_IDS
    assert all(row["current"] is True for row in state["rows"])
    assert all(row["disposition"] == "approve" for row in state["rows"])
    assert [
        row["review_question_id"]
        for row in authoritative_synthesis_question_bindings(state)
    ] == QUESTION_IDS


def test_authoritative_registration_persists_question_digest_and_lineage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _authoritative_state_patches(monkeypatch)
    monkeypatch.setattr(
        "review_writer.project.synthesis.paper_evidence_state",
        lambda _: {
            "projection_digest": EVIDENCE_DIGEST,
            "rows": [
                {"evidence_id": "evidence-a", "study_id": "study-a", "status": "approved"},
                {"evidence_id": "evidence-b", "study_id": "study-b", "status": "approved"},
            ],
        },
    )

    result = register_synthesis_candidates(
        project,
        {
            "synthesis_id": "synthesis-RQ1",
            "proposition": "A bounded cross-study comparison.",
            "comparison_axis": "reported outcome",
            "supporting_evidence_ids": ["evidence-a", "evidence-b"],
            "counter_evidence_ids": [],
            "applicability_boundary": "These two studies.",
            "mechanism_evidence_grade": "low",
            "uncertainty": "Bounded.",
            "risk_class": "scope",
            "single_study": False,
            "review_question_id": "RQ1",
        },
    )

    artifact = result["claims"][0]
    assert artifact["review_question_id"] == "RQ1"
    assert artifact["review_question_digest"] == _question_digest("RQ1")
    assert artifact["review_questions_digest"] == FROZEN_REVIEW_QUESTIONS_DIGEST
    assert artifact["review_question_lineage_digest"]


@pytest.mark.parametrize(
    ("case", "expected_code"),
    [
        ("missing", "SYNTHESIS_REVIEW_QUESTION_MISSING"),
        ("duplicate", "SYNTHESIS_REVIEW_QUESTION_DUPLICATE"),
        ("unknown", "SYNTHESIS_REVIEW_QUESTION_UNKNOWN"),
        ("stale", "SYNTHESIS_REVIEW_QUESTION_STALE"),
        ("digest_mismatch", "SYNTHESIS_REVIEW_QUESTION_DIGEST_MISMATCH"),
        (
            "artifact_digest",
            "SYNTHESIS_REVIEW_QUESTION_ARTIFACT_DIGEST_MISMATCH",
        ),
        ("disposition", "SYNTHESIS_REVIEW_QUESTION_DISPOSITION_REQUIRED"),
    ],
)
def test_authoritative_synthesis_question_gate_blocks_incomplete_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    expected_code: str,
) -> None:
    project = tmp_path / case
    project.mkdir()
    _authoritative_state_patches(monkeypatch)
    rows = [_artifact(question_id) for question_id in QUESTION_IDS]
    if case == "missing":
        rows = rows[:-1]
    elif case == "duplicate":
        duplicate = _artifact(QUESTION_IDS[-2])
        duplicate["synthesis_id"] = "synthesis-duplicate"
        rows.append(duplicate)
    elif case == "unknown":
        unknown = _artifact(QUESTION_IDS[0])
        unknown["synthesis_id"] = "synthesis-unknown"
        unknown["review_question_id"] = "RQ6"
        rows.append(unknown)
    elif case == "stale":
        rows[0]["review_questions_digest"] = "s" * 64
    elif case == "digest_mismatch":
        rows[0]["review_question_digest"] = "d" * 64
    elif case == "artifact_digest":
        rows[0]["synthesis_digest"] = "a" * 64
    elif case == "disposition":
        rows[0]["decision"] = None
    _write_artifacts(project, rows)

    state = synthesis_state(project)

    assert state["workflow_can_continue"] is False
    assert state["question_gate"]["reason_code"] == expected_code
