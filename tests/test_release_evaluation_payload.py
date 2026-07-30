from __future__ import annotations

import json
from pathlib import Path

from review_writer.project.credit_ledger import record_credit_event
from view import serve_review_dashboard as dashboard


DIMENSIONS = (
    ("scope_and_question_value", 10, 9),
    ("source_set_coverage", 15, 10),
    ("evidence_fidelity", 20, 18),
    ("synthesis_and_critique", 20, 17),
    ("structure_and_narrative", 15, 13),
    ("figure_information_value", 10, 7),
    ("citation_and_traceability", 10, 9),
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def _benchmark(
    project: Path, *, chemical_paper: dict[str, object] | None = None
) -> dict[str, object]:
    report: dict[str, object] = {
        "schema_version": "review-benchmark-report.v1",
        "evaluated_at": "2026-07-29T00:00:00Z",
        "project_id": project.name,
        "release_level": "SELF_REVIEWED_DRAFT",
        "status": "pass_internal",
        "score": 83,
        "tier": "acceptable_internal_revision_required",
        "expert_release_ready": False,
        "rubric": [
            {
                "dimension_id": dimension_id,
                "max_score": maximum,
                "score": score,
                "rationale": f"Bounded rationale for {dimension_id}.",
            }
            for dimension_id, maximum, score in DIMENSIONS
        ],
        "hard_fails": [],
        "issues": [
            "SYNTHESIS_FIGURE_PENDING",
            *(
                [
                    "CHEMICAL_ELEMENTS_NOT_REVIEWED",
                    "CHEMICAL_FIELDS_UNRESOLVED",
                    "CHEMICAL_REACTION_DATA_UNAVAILABLE",
                ]
                if chemical_paper is not None
                else []
            ),
        ],
        "chemical_paper_safe_summary": chemical_paper,
        "release_binding": {
            "manuscript_sha256": "a" * 64,
            "release_sha256": "b" * 64,
            "chemical_paper_binding_digest": "c" * 64 if chemical_paper else None,
            "chemical_paper_dependency_can_release": True,
        },
        "standard_corpus": None,
        "comparison_metrics": [
            "section_proportions",
            "comparison_and_critique_density",
            "source_figure_density",
            "caption_information_content",
            "citation_density",
            "claim_traceability",
        ],
        "human_review_required": True,
        "disclaimer": "Regression score only; not scientific correctness, expert acceptance, or publication approval.",
    }
    _write_json(project / "06_evaluation/review_benchmark_report.json", report)
    _write_json(
        project / "05_release/release_snapshot.json",
        {
            "project_id": project.name,
            "release_level": "SELF_REVIEWED_DRAFT",
            "manuscript_sha256": "a" * 64,
            "docx_sha256": "b" * 64,
            **(
                {
                    "chemical_paper_binding_digest": "c" * 64,
                    "chemical_paper_safe_summary": chemical_paper,
                    "chemical_paper_dependency_can_release": True,
                }
                if chemical_paper is not None
                else {
                    "chemical_paper_binding_digest": None,
                    "chemical_paper_safe_summary": None,
                    "chemical_paper_dependency_can_release": True,
                }
            ),
        },
    )
    return report


def test_evaluation_payload_projects_valid_benchmark_and_authoritative_credits(
    tmp_path: Path,
) -> None:
    project = tmp_path / "review-projects/project-a"
    project.mkdir(parents=True)
    _benchmark(project)
    record_credit_event(
        project,
        stage="complete_loop",
        before=2004,
        after=1351,
        source="manual_dashboard",
        forecast=650,
    )

    payload = dashboard.project_evaluation_payload(project)

    assert payload["benchmark"]["status"] == "available"
    assert payload["benchmark"]["score"] == 83
    assert len(payload["benchmark"]["rubric"]) == 7
    assert payload["benchmark"]["hard_fails"] == []
    assert payload["benchmark"]["issues"] == ["SYNTHESIS_FIGURE_PENDING"]
    assert payload["credit_ledger"]["status"] == "available"
    assert payload["credit_ledger"]["measured"] == {
        "before": 2004,
        "after": 1351,
        "consumed": 653,
    }


def test_evaluation_payload_never_guesses_missing_credits_as_zero(tmp_path: Path) -> None:
    project = tmp_path / "review-projects/project-a"
    project.mkdir(parents=True)

    payload = dashboard.project_evaluation_payload(project)

    assert payload["benchmark"] == {"status": "unavailable", "reason_code": "BENCHMARK_REPORT_MISSING"}
    assert payload["credit_ledger"]["status"] == "unavailable"
    assert payload["credit_ledger"]["measured"] is None
    assert payload["credit_ledger"]["remaining"] is None


def test_evaluation_payload_hides_stale_benchmark_values(tmp_path: Path) -> None:
    project = tmp_path / "review-projects/project-a"
    project.mkdir(parents=True)
    _benchmark(project)
    snapshot = project / "05_release/release_snapshot.json"
    data = json.loads(snapshot.read_text(encoding="utf-8"))
    data["docx_sha256"] = "c" * 64
    _write_json(snapshot, data)

    payload = dashboard.project_evaluation_payload(project)

    assert payload["benchmark"] == {"status": "stale", "reason_code": "BENCHMARK_RELEASE_STALE"}
    assert "score" not in payload["benchmark"]


def test_evaluation_payload_exposes_only_aggregate_chemical_paper_state(
    tmp_path: Path,
) -> None:
    project = tmp_path / "review-projects/project-a"
    project.mkdir(parents=True)
    chemical_paper: dict[str, object] = {
        "schema_version": "chemical-paper-safe-summary.v1",
        "route": "chemical-paper-zip-only",
        "study_count": 3,
        "molecule_count": 309,
        "unresolved_field_count": 94,
        "element_review_counts": {
            "not_reviewed": 309,
            "confirmed": 0,
            "corrected": 0,
            "not_applicable": 0,
        },
        "reaction_data_status": "unavailable_not_provided",
    }
    _benchmark(project, chemical_paper=chemical_paper)

    payload = dashboard.project_evaluation_payload(project)

    assert payload["benchmark"]["chemical_paper_safe_summary"] == chemical_paper
    serialized = json.dumps(payload["benchmark"]["chemical_paper_safe_summary"])
    for forbidden in (
        "chemical_paper_lineage_digest",
        "source_pdf_sha256",
        "import_digest",
        "molecule_id",
        "study_id",
        "zip_path",
    ):
        assert forbidden not in serialized
