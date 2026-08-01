from __future__ import annotations

from pathlib import Path

import pytest

from review_writer.project.synthesis import (
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
    assert _authoritative_review_question_binding(project, lineage) == lineage
    tampered = {**registered, "review_questions": list(reversed(FROZEN_QUESTIONS))}
    with pytest.raises(ProjectReleaseError, match="REVIEW_QUESTIONS_INVALID"):
        validate_authoritative_review_questions(tampered)
