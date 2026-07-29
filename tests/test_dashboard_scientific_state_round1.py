from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_new_route_cockpit_uses_authoritative_scientific_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from view import serve_review_dashboard as dashboard

    project = tmp_path / "review-projects/new-route"
    project.mkdir(parents=True)
    monkeypatch.setattr(dashboard, "project_dir", lambda *_args: project)
    monkeypatch.setattr(
        dashboard,
        "workflow_state",
        lambda _project: {
            "route": "evidence-to-release.v1",
            "active_stage": "final",
            "parse_ready": True,
            "blockers": [],
        },
    )
    monkeypatch.setattr(
        dashboard,
        "paper_evidence_state",
        lambda _project: {
            "study_count": 3,
            "rows": [
                {"study_id": "a", "status": "approved"},
                {"study_id": "a", "status": "approved"},
                {"study_id": "b", "status": "approved"},
                {"study_id": "c", "status": "approved"},
            ],
        },
    )
    monkeypatch.setattr(
        dashboard,
        "project_progress_payload",
        lambda *_args: {
            "active_stage": "final",
            "recommended_next": "检查正文并导出 DOCX",
        },
    )

    payload = dashboard.project_cockpit_payload(tmp_path, "new-route")

    assert payload["current_stage"] == "final"
    assert payload["recommended_next"] == "检查正文并导出 DOCX"
    assert payload["metrics"] == {
        "included_studies": 3,
        "full_text_main_coverage": 3,
        "reviewed_studies": 3,
        "scientific_risks": 0,
    }


def test_safe_decision_preserves_only_auditable_actor_fields() -> None:
    from view import serve_review_dashboard as dashboard

    decision = dashboard._safe_decision(
        {
            "action": "approve",
            "reason": "Checked.",
            "decided_at": "2026-07-29T00:00:00Z",
            "actor_type": "simulated_researcher_agent",
            "actor_label": "dashboard-playwright-reviewer",
            "private_note": "must not escape",
        }
    )

    assert decision == {
        "action": "approve",
        "reason": "Checked.",
        "decided_at": "2026-07-29T00:00:00Z",
        "actor_type": "simulated_researcher_agent",
        "actor_label": "dashboard-playwright-reviewer",
    }


def test_figure_workspace_projects_publication_rights_and_gap_reason(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from view import serve_review_dashboard as dashboard

    project = tmp_path / "review-projects/new-route"
    pool = project / "00_discovery/candidate_pool.json"
    pool.parent.mkdir(parents=True)
    pool.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "candidate_id": "study-a",
                        "title": "A bounded study",
                        "authors": ["Ada Researcher"],
                        "year": 2024,
                        "journal": "Journal of Tests",
                        "doi": "10.1000/test.1",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    registry = project / "03_figures/source_figure_registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps(
            {
                "figures": [
                    {
                        "figure_id": "figure-a",
                        "study_id": "study-a",
                        "source_id": "source-a",
                        "page": 4,
                        "figure_label": "Figure 2",
                        "caption": "Observed scope.",
                        "selection_status": "selected",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        dashboard, "workflow_state", lambda _project: {"route": "evidence-to-release.v1"}
    )
    monkeypatch.setattr(
        dashboard,
        "synthesis_figure_placeholders",
        lambda _project: [
            {
                "placeholder_id": "placeholder-a",
                "scientific_question": "How do the studies differ?",
                "unresolved_uncertainties": ["No shared substrate panel."],
                "status": "awaiting_human_figure",
            }
        ],
    )

    payload = dashboard.project_review_figures_workspace_payload(tmp_path, "new-route")
    figure = payload["source_figures"][0]
    placeholder = payload["placeholders"][0]
    assert figure["publication_identity"]["title"] == "A bounded study"
    assert "Ada Researcher" in figure["attribution"]
    assert figure["rights_context"]["status"] == "unknown"
    assert figure["rights_context"]["reuse_scope"] == "internal_review_only"
    assert "publication reuse rights are not cleared" in figure["rights_context"]["notice"]
    assert "How do the studies differ?" in placeholder["gap_reason"]
    assert "No shared substrate panel." in placeholder["gap_reason"]


@pytest.mark.parametrize(
    ("axes", "expected", "count"),
    [
        (
            [
                {
                    "axis_id": "scope",
                    "counterevidence_ids": ["E-2"],
                    "incomparable_items": ["Different endpoints."],
                    "impact_on_conclusion": "Do not rank.",
                }
            ],
            "registered",
            1,
        ),
        ([{"axis_id": "scope", "counterevidence_ids": [], "incomparable_items": []}], "checked_no_conflicts", 0),
        ([{"axis_id": "scope"}], "not_checked", 0),
    ],
)
def test_coverage_projects_three_state_conflict_register(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    axes: list[dict[str, object]],
    expected: str,
    count: int,
) -> None:
    from view import serve_review_dashboard as dashboard

    project = tmp_path / "review-projects/new-route"
    project.mkdir(parents=True)
    monkeypatch.setattr(dashboard, "project_dir", lambda *_args: project)
    monkeypatch.setattr(
        dashboard, "workflow_state", lambda _project: {"route": "evidence-to-release.v1"}
    )
    monkeypatch.setattr(dashboard, "synthesis_state", lambda _project: {"rows": []})
    monkeypatch.setattr(
        dashboard,
        "coverage_map_state",
        lambda _project: {"value": {"axes": axes}, "status": "approved"},
    )
    monkeypatch.setattr(
        dashboard, "comparison_protocol_state", lambda _project: {"workflow_can_continue": True}
    )

    coverage = dashboard.project_synthesis_payload(tmp_path, "new-route")["coverage"]
    assert coverage["conflict_status"] == expected
    assert len(coverage["conflict_register"]) == count


def test_frontend_renders_complete_protocol_actor_figure_and_conflict_state() -> None:
    root = Path(__file__).resolve().parents[1] / "view/assets/dashboard"
    evidence = (root / "review-evidence.js").read_text(encoding="utf-8")
    synthesis = (root / "review-synthesis.js").read_text(encoding="utf-8")
    for label in ("归一化规则", "缺失值规则", "不可比规则", "反证规则"):
        assert label in synthesis
    for key in (
        "counterevidence_ids",
        "incomparable_items",
        "impact_on_conclusion",
        "conflict_status",
        "conflict_register",
        "publication_identity",
        "rights_context",
        "gap_reason",
    ):
        assert key in synthesis
    assert "actor_type" in evidence and "actor_label" in evidence
    assert "actor_type" in synthesis and "actor_label" in synthesis
