from __future__ import annotations

import json

import pytest


def _rows() -> list[dict[str, object]]:
    return [
        {
            "study_id": "paper-a",
            "molecule_id": "mol-1",
            "status": "CONFIRMED",
            "value": "confirmed value",
            "source_id": "source-a",
            "pdf_locator": {"page": 1, "section_or_item": "Results"},
            "provenance": {"source": "researcher_pdf", "evidence_id": "e-1"},
        },
        {
            "study_id": "paper-a",
            "molecule_id": "mol-2",
            "status": "AI_PROVISIONAL",
            "value": "provisional value",
            "confidence": 0.72,
            "source_id": "source-a",
            "pdf_locator": {"page": 2, "section_or_item": "Figure 2"},
            "provenance": {"source": "ai_candidate", "evidence_id": "e-2"},
        },
        {
            "study_id": "paper-a",
            "molecule_id": "mol-3",
            "status": "BLOCKED",
            "value": None,
            "gap_reason": "The PDF does not support a unique structure.",
            "source_id": "source-a",
            "pdf_locator": {"page": 3, "section_or_item": "Scheme 1"},
            "provenance": {"source": "researcher_pdf", "evidence_id": "e-3"},
        },
    ]


def _project_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index in range(248):
        rows.append(
            {
                "study_id": "paper-a",
                "molecule_id": f"covered-{index + 1}",
                "status": "CONFIRMED",
                "value": "confirmed value",
                "source_id": "source-a",
                "pdf_locator": {"page": 1, "section_or_item": "Results"},
                "provenance": {"source": "researcher_pdf", "evidence_id": f"e-{index + 1}"},
            }
        )
    for index in range(61):
        rows.append(
            {
                "study_id": "paper-a",
                "molecule_id": f"blocked-{index + 1}",
                "status": "BLOCKED",
                "value": None,
                "gap_reason": "The PDF does not support a unique structure.",
                "source_id": "source-a",
                "pdf_locator": {"page": 2, "section_or_item": "Scheme 1"},
                "provenance": {"source": "researcher_pdf", "evidence_id": f"gap-{index + 1}"},
            }
        )
    return rows


def test_honest_progressive_evidence_summary_tracks_three_states_and_gaps() -> None:
    from review_writer.project.paper_evidence import build_honest_progressive_summary

    summary = build_honest_progressive_summary(_rows(), core_molecule_count=3)

    assert summary["route"] == "honest_progressive"
    assert summary["availability"] == "available"
    assert summary["status"] == "needs_more_traceable_candidates"
    assert summary["core_molecule_count"] == 3
    assert summary["confirmed_count"] == 1
    assert summary["ai_provisional_count"] == 1
    assert summary["blocked_count"] == 1
    assert summary["coverage_ratio"] == pytest.approx(2 / 3)
    assert summary["coverage_threshold"] == pytest.approx(0.8)
    assert summary["coverage_sufficient"] is False
    assert summary["paper_coverage"] == [
        {
            "study_id": "paper-a",
            "core_molecule_count": 3,
            "coverage_denominator": 3,
            "confirmed_count": 1,
            "ai_provisional_count": 1,
            "blocked_count": 1,
            "coverage_ratio": pytest.approx(2 / 3),
        }
    ]
    assert summary["gap_registry"][0]["molecule_id"] == "mol-3"
    assert summary["gap_registry"][0]["reason"]
    assert summary["traceability"][1]["provenance"]["source"] == "ai_candidate"
    assert summary["credits_status"] == "NOT_APPLICABLE_BY_CURRENT_SCOPE"
    assert "strict" not in summary
    assert "exploratory" not in summary


def test_honest_progressive_consumption_never_promotes_provisional_or_blocked() -> None:
    from review_writer.project.synthesis import partition_honest_progressive_evidence

    projection = partition_honest_progressive_evidence(_rows())

    assert [row["molecule_id"] for row in projection["exact_conclusions"]] == ["mol-1"]
    assert [row["molecule_id"] for row in projection["internal_comparison"]] == [
        "mol-1",
        "mol-2",
    ]
    assert projection["internal_comparison"][1]["provisional"] is True
    assert [row["molecule_id"] for row in projection["limitation_disclosures"]] == ["mol-3"]
    assert projection["limitation_disclosures"][0]["value"] is None


def test_dual_release_accepts_eighty_percent_coverage_with_visible_blocked_gap() -> None:
    from review_writer.delivery.dual_parse_release import honest_progressive_release_projection

    rows = _project_rows()
    summary = honest_progressive_release_projection(rows, core_molecule_count=5)

    assert summary["route"] == "honest_progressive"
    assert summary["availability"] == "available"
    assert summary["status"] == "ready"
    assert summary["core_molecule_count"] == 309
    assert summary["confirmed_count"] == 248
    assert summary["coverage_ratio"] == pytest.approx(248 / 309)
    assert summary["coverage_sufficient"] is True
    assert summary["internal_release_ready"] is True
    assert summary["blocked_count"] == 61
    assert summary["gap_registry"]
    assert summary["hard_fails"] == []
    assert summary["credits_status"] == "NOT_APPLICABLE_BY_CURRENT_SCOPE"


def test_project_projection_parser_uses_fixed_denominator_and_recomputes_eligibility() -> None:
    from review_writer.project.paper_evidence import honest_progressive_summary_from_projection

    projection = {
        "honest_progressive": {
            "molecules": _rows(),
            "core_molecule_count": 3,
            "coverage_threshold": 0.01,
            "coverage_sufficient": True,
        }
    }

    summary = honest_progressive_summary_from_projection(projection, project_scope=True)

    assert summary is not None
    assert summary["core_molecule_count"] == 309
    assert summary["coverage_ratio"] == pytest.approx(2 / 309)
    assert summary["coverage_threshold"] == pytest.approx(0.8)
    assert summary["coverage_sufficient"] is False
    assert summary["availability"] == "available"
    assert summary["status"] == "needs_more_traceable_candidates"


@pytest.mark.parametrize(
    ("value", "gap_reason"),
    [("unexpected blocked value", "The value is not source-supported."), (None, "")],
)
def test_malformed_blocked_evidence_is_rejected(value: object, gap_reason: str) -> None:
    from review_writer.project.paper_evidence import PaperEvidenceError, build_honest_progressive_summary

    row = {
        "study_id": "paper-a",
        "molecule_id": "blocked-molecule",
        "status": "BLOCKED",
        "value": value,
        "gap_reason": gap_reason,
    }

    with pytest.raises(PaperEvidenceError):
        build_honest_progressive_summary([row], core_molecule_count=1)


def test_release_and_evaluation_project_coverage_traceability_and_gap_honesty() -> None:
    from review_writer.delivery.project_release import honest_progressive_release_fields
    from review_writer.evaluation.review_benchmark import evaluate_honest_progressive
    from review_writer.project.paper_evidence import build_honest_progressive_summary

    summary = build_honest_progressive_summary(_rows(), core_molecule_count=309)
    release_fields = honest_progressive_release_fields(summary)
    evaluation = evaluate_honest_progressive(summary)

    assert release_fields["route"] == "honest_progressive"
    assert release_fields["availability"] == "available"
    assert release_fields["status"] == "needs_more_traceable_candidates"
    assert release_fields["coverage_ratio"] == pytest.approx(2 / 309)
    assert release_fields["paper_coverage"] == summary["paper_coverage"]
    assert release_fields["uncertainty_statement"]
    assert len(release_fields["gap_registry"]) == len(summary["gap_registry"])
    assert release_fields["gap_registry"][0] == summary["gap_registry"][0]
    assert release_fields["traceability"] == summary["traceability"]
    assert "strict" not in release_fields
    assert "exploratory" not in release_fields

    assert evaluation["route"] == "honest_progressive"
    assert evaluation["coverage_ratio"] == pytest.approx(2 / 309)
    assert evaluation["coverage_threshold"] == pytest.approx(0.8)
    assert evaluation["source_traceability"] == pytest.approx(3 / 309)
    assert evaluation["gap_honesty"] is True
    assert evaluation["status"] == "needs_revision"
    assert evaluation["credits_status"] == "NOT_APPLICABLE_BY_CURRENT_SCOPE"
    assert "credits" not in evaluation


def test_legacy_approved_input_remains_compatible_without_strict_exploratory_output() -> None:
    from review_writer.project.paper_evidence import build_honest_progressive_summary

    summary = build_honest_progressive_summary(
        [
            {
                "study_id": "legacy-paper",
                "molecule_id": "legacy-molecule",
                "status": "approved",
                "value": "researcher-approved legacy value",
            }
        ],
        core_molecule_count=1,
    )

    assert summary["route"] == "honest_progressive"
    assert summary["availability"] == "available"
    assert summary["status"] == "ready"
    assert summary["confirmed_count"] == 1
    assert summary["ai_provisional_count"] == 0
    assert summary["coverage_ratio"] == 1.0
    assert "strict" not in summary
    assert "exploratory" not in summary


def test_honest_progressive_safe_projection_omits_sensitive_provenance_and_values() -> None:
    from review_writer.project.paper_evidence import build_honest_progressive_summary

    rows = _rows()
    rows[1]["value"] = {"molblock": "SECRET MOLBLOCK"}
    rows[1]["provenance"] = {
        "source": "ai_candidate",
        "path": "/private/project/source.pdf",
        "sha256": "a" * 64,
        "token": "secret-token",
        "session_id": "private-session",
        "private_url": "https://private.example.invalid/source",
        "raw_json": '{"secret": true}',
        "molblock": "SECRET MOLBLOCK",
    }
    rows[1]["pdf_locator"] = {
        "page": 2,
        "section_or_item": "Figure 2",
        "path": "/private/project/source.pdf",
        "url": "https://private.example.invalid/source",
    }
    rows[2]["source_id"] = "/sensitive/blocked-source.pdf"

    summary = build_honest_progressive_summary(
        rows,
        core_molecule_count=3,
        paper_core_molecule_counts={"/sensitive/paper.pdf": 0},
    )
    serialized = json.dumps(summary, sort_keys=True)

    for secret in (
        "/private/project/source.pdf",
        "/sensitive/blocked-source.pdf",
        "/sensitive/paper.pdf",
        "a" * 64,
        "secret-token",
        "private-session",
        "private.example.invalid",
        "SECRET MOLBLOCK",
        "raw_json",
    ):
        assert secret not in serialized
    assert summary["traceability"][1]["provenance"] == {"source": "ai_candidate"}


def test_honest_progressive_release_uses_fixed_project_threshold_and_denominator() -> None:
    from review_writer.delivery.dual_parse_release import honest_progressive_release_projection

    summary = honest_progressive_release_projection(_rows(), core_molecule_count=3)

    assert summary["route"] == "honest_progressive"
    assert summary["core_molecule_count"] == 309
    assert summary["coverage_threshold"] == pytest.approx(0.8)
    assert summary["coverage_sufficient"] is False


def test_actor_provenance_residual_is_safe_append_only_history() -> None:
    from review_writer.delivery.project_release import honest_progressive_release_fields
    from review_writer.evaluation.review_benchmark import evaluate_honest_progressive
    from review_writer.project.paper_evidence import build_honest_progressive_summary

    rows = _project_rows()
    residual = {
        "actor_type": "simulated_researcher_agent",
        "actor_label": "agent-a",
        "reason_code": "ACTOR_MISMATCH",
        "path": "/private/project/state.json",
        "token": "secret-token",
    }
    rows[0]["actor_provenance_residual"] = [residual, residual.copy()]

    summary = build_honest_progressive_summary(rows, core_molecule_count=309)

    assert summary["actor_provenance_residual"] == [
        {
            "actor_type": "simulated_researcher_agent",
            "actor_label": "agent-a",
            "reason_code": "ACTOR_MISMATCH",
        },
        {
            "actor_type": "simulated_researcher_agent",
            "actor_label": "agent-a",
            "reason_code": "ACTOR_MISMATCH",
        },
    ]
    release_fields = honest_progressive_release_fields(summary)
    evaluation = evaluate_honest_progressive(summary)
    assert release_fields["actor_provenance_residual"] == summary["actor_provenance_residual"]
    assert evaluation["actor_provenance_residual"] == summary["actor_provenance_residual"]


def test_dual_release_keeps_expert_not_ready_when_figure_is_pending(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from review_writer.delivery import dual_parse_release as release

    project = tmp_path / "project"
    (project / "04_manuscript").mkdir(parents=True)
    (project / "04_manuscript/manuscript_lineage.v2.json").write_text(
        json.dumps({"dual_parse_bindings": [{"study_id": "paper-a"}]}),
        encoding="utf-8",
    )
    summary = release.honest_progressive_release_projection(_project_rows())
    current_rows = [{"study_id": "paper-a", "honest_progressive": summary}]
    monkeypatch.setattr(release, "_current_authority_rows", lambda _: current_rows)
    monkeypatch.setattr(
        release,
        "validate_dual_parse_release_bindings",
        lambda *_: {
            "status": "current",
            "hard_fails": [],
            "dual_parse_bindings": [{"study_id": "paper-a"}],
        },
    )
    monkeypatch.setattr(release, "_awaiting_human_figure", lambda _: True)

    state = release.dual_parse_release_state(project)

    assert state["internal_release_ready"] is True
    assert state["expert_release_ready"] is False
    assert "SYNTHESIS_FIGURE_PENDING" in state["issues"]


def test_honest_progressive_report_keeps_expert_not_ready_when_figure_is_pending(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from review_writer.evaluation import review_benchmark

    summary = review_benchmark.honest_progressive_summary_from_projection(
        {"honest_progressive": {"molecules": _project_rows(), "core_molecule_count": 309}},
        project_scope=True,
    )
    assert summary is not None
    binding = {
        "project_id": "project-a",
        "release_level": "SELF_REVIEWED_DRAFT",
        "manuscript_sha256": None,
        "release_sha256": None,
        "placeholders": [{"status": "awaiting_human_figure"}],
        "verified_figure_ready": False,
        "chemical_paper_state": {"issues": []},
        "chemical_paper_safe_summary": None,
        "chemical_paper_binding_digest": None,
        "chemical_paper_dependency_can_release": True,
        "dual_parse_status": "not_applicable",
        "dual_parse_binding_digest": None,
        "reaction_data_status": "not_applicable",
        "reaction_count": None,
        "hard_fail_signals": [],
        "honest_progressive": summary,
    }
    monkeypatch.setattr(review_benchmark, "_release_payload", lambda *_args, **_kwargs: binding)
    scores = [
        {
            "dimension_id": dimension_id,
            "max_score": maximum,
            "score": maximum,
            "rationale": "covered",
        }
        for dimension_id, maximum in review_benchmark.RUBRIC_DIMENSIONS
    ]

    report = review_benchmark.evaluate_review(tmp_path / "unused", scores)

    assert report["route"] == "honest_progressive"
    assert report["core_molecule_count"] == 309
    assert report["expert_release_ready"] is False
