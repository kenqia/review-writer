from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


def test_new_route_cockpit_uses_authoritative_counts_stage_and_next_action(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from view import serve_review_dashboard as dashboard

    project = tmp_path / "review-projects" / "new-route"
    project.mkdir(parents=True)
    monkeypatch.setattr(dashboard, "project_dir", lambda _root, _project_id: project)
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
                {"study_id": "study-a", "status": "approved"},
                {"study_id": "study-a", "status": "approved"},
                {"study_id": "study-b", "status": "approved"},
                {"study_id": "study-c", "status": "approved"},
            ],
        },
    )
    monkeypatch.setattr(
        dashboard,
        "project_progress_payload",
        lambda _root, _project_id: {
            "active_stage": "final",
            "recommended_next": "检查正文并导出 DOCX",
        },
    )

    payload = dashboard.project_cockpit_payload(tmp_path, "new-route")

    assert payload["current_stage"] == "final"
    assert payload["metrics"] == {
        "included_studies": 3,
        "full_text_main_coverage": 3,
        "reviewed_studies": 3,
        "scientific_risks": 0,
    }
    assert payload["recommended_next"] == "检查正文并导出 DOCX"


def test_safe_decision_preserves_auditable_actor_provenance() -> None:
    from view import serve_review_dashboard as dashboard

    decision = dashboard._safe_decision(
        {
            "action": "approve",
            "reason": "Checked against the source.",
            "decided_at": "2026-07-29T00:00:00Z",
            "actor_type": "simulated_researcher_agent",
            "actor_label": "dashboard-playwright-reviewer",
            "private_note": "must not escape",
        }
    )

    assert decision == {
        "action": "approve",
        "reason": "Checked against the source.",
        "decided_at": "2026-07-29T00:00:00Z",
        "actor_type": "simulated_researcher_agent",
        "actor_label": "dashboard-playwright-reviewer",
    }


def test_new_route_figure_workspace_projects_publication_rights_and_gap_reason(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from view import serve_review_dashboard as dashboard

    project = tmp_path / "review-projects" / "new-route"
    pool = project / "00_discovery/candidate_pool.json"
    pool.parent.mkdir(parents=True)
    pool.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "candidate_id": "study-a",
                        "title": "A bounded study",
                        "authors": ["Ada Researcher", "Bo Scientist"],
                        "year": 2024,
                        "journal": "Journal of Tests",
                        "doi": "10.1000/test.1",
                    }
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )
    registry_path = project / "03_figures/source_figure_registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
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
                        "rights_status": "unknown",
                    }
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        dashboard,
        "workflow_state",
        lambda _project: {"route": "evidence-to-release.v1"},
    )
    monkeypatch.setattr(
        dashboard,
        "load_source_figure_registry",
        lambda _project: json.loads(registry_path.read_text(encoding="utf-8")),
    )
    monkeypatch.setattr(
        dashboard,
        "synthesis_figure_placeholders",
        lambda _project: [
            {
                "placeholder_id": "placeholder-a",
                "scientific_question": "How do the studies differ?",
                "reader_takeaway": "The endpoints are not directly comparable.",
                "unresolved_uncertainties": ["No shared substrate panel."],
                "status": "awaiting_human_figure",
            }
        ],
    )

    payload = dashboard.project_review_figures_workspace_payload(tmp_path, "new-route")
    figure = payload["source_figures"][0]
    placeholder = payload["placeholders"][0]

    assert figure["publication_identity"] == {
        "title": "A bounded study",
        "authors": ["Ada Researcher", "Bo Scientist"],
        "year": 2024,
        "journal": "Journal of Tests",
        "doi": "10.1000/test.1",
    }
    assert "Ada Researcher" in figure["attribution"]
    assert figure["rights_context"]["status"] == "unknown"
    assert figure["rights_context"]["reuse_scope"] == "internal_review_only"
    assert "publication reuse rights are not cleared" in figure["rights_context"]["notice"]
    assert "How do the studies differ?" in placeholder["gap_reason"]
    assert "No shared substrate panel." in placeholder["gap_reason"]


@pytest.mark.parametrize(
    ("axes", "expected_status", "expected_count"),
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
        (
            [
                {
                    "axis_id": "scope",
                    "counterevidence_ids": [],
                    "incomparable_items": [],
                    "impact_on_conclusion": "No conflict found.",
                }
            ],
            "checked_no_conflicts",
            0,
        ),
        ([{"axis_id": "scope"}], "not_checked", 0),
    ],
)
def test_synthesis_coverage_projects_explicit_conflict_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    axes: list[dict[str, object]],
    expected_status: str,
    expected_count: int,
) -> None:
    from view import serve_review_dashboard as dashboard

    project = tmp_path / "review-projects" / "new-route"
    project.mkdir(parents=True)
    monkeypatch.setattr(dashboard, "project_dir", lambda _root, _project_id: project)
    monkeypatch.setattr(
        dashboard,
        "workflow_state",
        lambda _project: {"route": "evidence-to-release.v1"},
    )
    monkeypatch.setattr(
        dashboard,
        "synthesis_state",
        lambda _project: {"rows": [], "status": "approved", "workflow_can_continue": True},
    )
    monkeypatch.setattr(
        dashboard,
        "coverage_map_state",
        lambda _project: {
            "value": {"comparison_id": "comparison-a", "axes": axes},
            "status": "approved",
            "reason_code": "COVERAGE_READY",
        },
    )
    monkeypatch.setattr(
        dashboard,
        "comparison_protocol_state",
        lambda _project: {"workflow_can_continue": True},
    )

    coverage = dashboard.project_synthesis_payload(tmp_path, "new-route")["coverage"]

    assert coverage["conflict_status"] == expected_status
    assert len(coverage["conflict_register"]) == expected_count
    if expected_count:
        assert coverage["conflict_register"][0] == {
            "axis_id": "scope",
            "counterevidence_ids": ["E-2"],
            "incomparable_items": ["Different endpoints."],
            "impact_on_conclusion": "Do not rank.",
        }


def test_frontend_projects_complete_scientific_state() -> None:
    root = Path(__file__).resolve().parents[1]
    evidence = (root / "view/assets/dashboard/review-evidence.js").read_text(encoding="utf-8")
    synthesis = (root / "view/assets/dashboard/review-synthesis.js").read_text(encoding="utf-8")

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
    assert "actor_type" in evidence
    assert "actor_label" in evidence
    assert "actor_type" in synthesis
    assert "actor_label" in synthesis


def test_parse_audit_uses_authoritative_decision_freshness() -> None:
    root = Path(__file__).resolve().parents[1]
    node = shutil.which("node")
    assert node is not None
    script = root / "view/assets/dashboard/review-audit.js"
    runtime = f"""
      const ui = require({json.dumps(str(script))});
      const model = ui.buildAuditModel({{
        parseQuality: {{last_decision_at:'2026-07-30T05:40:27.024231+00:00'}}
      }});
      if (!model.parseQuality.freshness.includes('2026-07-30')) {{
        throw new Error(model.parseQuality.freshness);
      }}
      if (model.parseQuality.freshness.includes('更新时间未提供')) {{
        throw new Error('authoritative freshness was discarded');
      }}
    """

    subprocess.run([node, "-e", runtime], check=True)


def test_figure_workspace_refuses_stale_locators_without_rewriting_registry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from review_writer.project.review_figures import build_source_figure_registry
    from review_writer.project.source_truth import write_source_truth_bundle
    from test_review_figures import _new_route_project
    from view import serve_review_dashboard as dashboard

    project = _new_route_project(tmp_path)
    registry_path = project / "03_figures/source_figure_registry.json"
    build_source_figure_registry(project)
    before = registry_path.read_bytes()
    markdown = project / "01_evidence/mineru/markdown/10_1000_example.md"
    markdown.write_text("# Canonical\nReparsed source\n", encoding="utf-8")
    write_source_truth_bundle(project, "scholarly-a")
    monkeypatch.setattr(
        dashboard,
        "workflow_state",
        lambda _project: {"route": "evidence-to-release.v1"},
    )
    monkeypatch.setattr(
        dashboard,
        "synthesis_figure_placeholders",
        lambda _project: [],
    )

    payload = dashboard.project_review_figures_workspace_payload(tmp_path, "case")

    assert payload["status"] == "needs_rebuild"
    assert payload["source_figures"] == []
    assert payload["locator_gaps"] == [
        {
            "study_id": "",
            "page": None,
            "reason": "论文解析来源已更新；原论文图定位必须重建后才能继续使用。",
        }
    ]
    assert registry_path.read_bytes() == before
