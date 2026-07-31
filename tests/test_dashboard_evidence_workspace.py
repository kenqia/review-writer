from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_paper_evidence_workspace_payload_is_safe(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from view import serve_review_dashboard as dashboard

    project = tmp_path / "new-route"
    project.mkdir()
    monkeypatch.setattr(dashboard, "project_dir", lambda _root, _project_id: project)
    monkeypatch.setattr(
        dashboard,
        "workflow_state",
        lambda _project: {"route": "evidence-to-release.v1"},
    )
    monkeypatch.setattr(
        dashboard,
        "paper_evidence_state",
        lambda _project: {
            "status": "needs_review",
            "reason_code": "PAPER_EVIDENCE_NOT_APPROVED",
            "workflow_can_continue": False,
            "rows": [
                {
                    "evidence_id": "E-1",
                    "study_id": "study-a",
                    "source_id": "source-a",
                    "epistemic_type": "experimental_observation",
                    "statement": "Bounded observation.",
                    "locator": {"page": 2, "section_or_item": "Results", "exact_quote": "Observed."},
                    "candidate_digest": "a" * 64,
                    "source_pdf_sha256": "b" * 64,
                    "schema_version": "paper-evidence.v1",
                    "agent_id": "internal-agent-secret",
                    "status": "needs_review",
                }
            ],
        },
    )

    payload = dashboard.project_paper_evidence_payload(tmp_path, "new-route")
    encoded = json.dumps(payload, ensure_ascii=False)
    assert payload["route"] == "evidence-to-release.v1"
    assert payload["items"][0]["evidence_id"] == "E-1"
    assert "candidate_digest" not in encoded
    assert "source_pdf_sha256" not in encoded
    assert "schema_version" not in encoded
    assert "internal-agent-secret" not in encoded


def test_workspace_stale_token_raises_before_writing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from view import serve_review_dashboard as dashboard

    project = tmp_path / "new-route"
    project.mkdir()
    monkeypatch.setattr(dashboard, "project_dir", lambda _root, _project_id: project)
    monkeypatch.setattr(
        dashboard,
        "paper_evidence_state",
        lambda _project: {
            "rows": [{"evidence_id": "E-1", "candidate_digest": "a" * 64}],
        },
    )

    with pytest.raises(dashboard.WorkspaceStaleError):
        dashboard.write_project_workspace_decision(
            tmp_path,
            "new-route",
            "paper-evidence",
            {"evidence_id": "E-1", "action": "approve", "reason": "check", "version_token": "stale"},
        )
    assert list(project.iterdir()) == []


def test_new_route_draft_payload_and_edit_use_manuscript_v2_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from view import serve_review_dashboard as dashboard

    project = tmp_path / "review-projects" / "new-route"
    (project / "01_evidence/source_truth/study-a").mkdir(parents=True)
    section = {
        "section_id": "section-one",
        "heading": "Evidence synthesis",
        "body": "Bounded statement. [evidence:E-1]",
        "status": "approved",
        "draft_digest": "a" * 64,
        "high_risk_reasons": ["paper_evidence:E-1"],
        "claim_bindings": [
            {
                "marker": "[evidence:E-1]",
                "paper_evidence_ids": ["E-1"],
                "synthesis_ids": [],
            }
        ],
        "decision": {
            "action": "approve",
            "reason": "Checked.",
            "actor_type": "simulated_researcher_agent",
            "actor_label": "dashboard-playwright-reviewer",
        },
    }
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        dashboard,
        "workflow_state",
        lambda _project: {"route": "evidence-to-release.v1"},
    )
    monkeypatch.setattr(
        dashboard,
        "build_manuscript_workspace",
        lambda _project: {
            "route": "evidence-to-release.v1",
            "status": "approved",
            "reason_code": "MANUSCRIPT_APPROVED",
            "sections": [section],
        },
    )
    monkeypatch.setattr(
        dashboard,
        "approve_section",
        lambda _project, section_id, actor, **kwargs: captured.update(
            section_id=section_id, actor=actor, **kwargs
        )
        or section,
    )
    monkeypatch.setattr(
        dashboard, "merge_authoritative_manuscript", lambda _project: {"status": "approved"}
    )

    payload = dashboard.project_draft_payload(tmp_path, "new-route")
    projected = payload["sections"][0]
    assert payload["route"] == "evidence-to-release.v1"
    assert projected["risk_classes"] == ["paper_evidence:E-1"]
    assert projected["claim_bindings"][0]["paper_evidence_ids"] == ["E-1"]
    assert "draft_digest" not in json.dumps(payload)

    result = dashboard.write_project_draft_sections(
        tmp_path,
        "new-route",
        {
            "section_id": "section-one",
            "edited_body": "Narrowed statement. [evidence:E-1]",
            "reason": "Narrowed after source review.",
            "version_token": projected["version_token"],
            "actor_type": "simulated_researcher_agent",
            "actor_label": "dashboard-playwright-reviewer",
        },
    )

    assert captured["expected_draft_digest"] == "a" * 64
    assert captured["edited_body"] == "Narrowed statement. [evidence:E-1]"
    assert captured["actor"] == {
        "actor_type": "simulated_researcher_agent",
        "actor_label": "dashboard-playwright-reviewer",
    }
    assert result["route"] == "evidence-to-release.v1"


def test_new_route_draft_edit_rejects_stale_version_before_approval(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from view import serve_review_dashboard as dashboard

    project = tmp_path / "review-projects" / "new-route"
    (project / "01_evidence/source_truth/study-a").mkdir(parents=True)
    monkeypatch.setattr(
        dashboard,
        "workflow_state",
        lambda _project: {"route": "evidence-to-release.v1"},
    )
    monkeypatch.setattr(
        dashboard,
        "build_manuscript_workspace",
        lambda _project: {
            "route": "evidence-to-release.v1",
            "status": "approved",
            "reason_code": "MANUSCRIPT_APPROVED",
            "sections": [
                {
                    "section_id": "section-one",
                    "heading": "Evidence synthesis",
                    "body": "Bounded statement. [evidence:E-1]",
                    "status": "approved",
                    "draft_digest": "a" * 64,
                    "high_risk_reasons": ["paper_evidence:E-1"],
                    "claim_bindings": [],
                    "decision": None,
                }
            ],
        },
    )
    monkeypatch.setattr(
        dashboard,
        "approve_section",
        lambda *_args, **_kwargs: pytest.fail("stale edit reached approval"),
    )

    with pytest.raises(dashboard.WorkspaceStaleError):
        dashboard.write_project_draft_sections(
            tmp_path,
            "new-route",
            {
                "section_id": "section-one",
                "edited_body": "Narrowed statement. [evidence:E-1]",
                "reason": "Narrowed after source review.",
                "version_token": "stale",
                "actor_type": "simulated_researcher_agent",
                "actor_label": "dashboard-playwright-reviewer",
            },
        )


def test_new_route_figure_payload_uses_selected_source_figures_and_placeholders(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from view import serve_review_dashboard as dashboard

    project = tmp_path / "review-projects" / "new-route"
    manuscript = project / "04_manuscript/manuscript.md"
    manuscript.parent.mkdir(parents=True)
    manuscript.write_text(
        "![Selected source](../01_evidence/images/source-one.png)\n",
        encoding="utf-8",
    )
    registry = {
        "figures": [
            {
                "figure_id": "figure-one",
                "asset_path": "01_evidence/images/source-one.png",
                "selection_status": "selected",
            },
            {
                "figure_id": "figure-two",
                "asset_path": "01_evidence/images/source-two.png",
                "selection_status": "available",
            },
        ]
    }
    registry_path = project / "03_figures/source_figure_registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(json.dumps(registry) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        dashboard,
        "workflow_state",
        lambda _project: {"route": "evidence-to-release.v1"},
    )
    monkeypatch.setattr(
        dashboard,
        "project_review_figures_workspace_payload",
        lambda _root, _project_id: {
            "source_figures": [
                {
                    "figure_id": "figure-one",
                    "figure_label": "Figure 1",
                    "caption": "Selected source figure.",
                    "selection_status": "selected",
                    "image_url": "/api/project/new-route/source-figure?figure_id=figure-one",
                    "study_id": "study-one",
                    "page": 3,
                },
                {
                    "figure_id": "figure-two",
                    "figure_label": "Figure 2",
                    "caption": "Unselected source figure.",
                    "selection_status": "available",
                    "image_url": "/api/project/new-route/source-figure?figure_id=figure-two",
                },
            ],
            "placeholders": [
                {
                    "placeholder_id": "placeholder-one",
                    "scientific_question": "How should the studies be compared?",
                    "caption_draft": "User-owned synthesis figure brief.",
                    "status": "awaiting_human_figure",
                }
            ],
        },
    )

    payload = dashboard.project_figures_payload(tmp_path, "new-route")

    assert payload["summary"] == {"total": 2, "placeholders": 1}
    assert [row["state"] for row in payload["figures"]] == [
        "原论文图",
        "图片说明占位符",
    ]
    assert payload["reading_figures"][0]["state"] == "原论文图"
    assert "asset_path" not in json.dumps(payload)


def test_new_route_progress_uses_authoritative_final_stage_not_legacy_risk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from view import serve_review_dashboard as dashboard

    project = tmp_path / "review-projects" / "new-route"
    bundle = project / "01_evidence/source_truth/study-one/bundle.json"
    bundle.parent.mkdir(parents=True)
    bundle.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(dashboard, "project_dir", lambda _root, _project_id: project)
    monkeypatch.setattr(
        dashboard,
        "workflow_state",
        lambda _project: {
            "route": "evidence-to-release.v1",
            "active_stage": "final",
            "parse_ready": True,
            "paper_evidence_ready": True,
            "synthesis_ready": True,
            "section_contracts_ready": True,
            "manuscript_ready": True,
            "internal_draft_export_ready": True,
            "verified_release_ready": False,
            "blockers": [],
        },
    )
    monkeypatch.setattr(
        dashboard,
        "project_parse_quality_state",
        lambda _project: {
            "status": "approved",
            "reason_code": "PARSE_QUALITY_READY",
            "workflow_can_continue": True,
            "studies": [],
        },
    )
    monkeypatch.setattr(
        dashboard,
        "project_source_handoff_payload",
        lambda _root, _project_id: {
            "counts": {"total": 1, "ready": 1},
            "sources": [
                {
                    "study_id": "study-one",
                    "citation": "Study one",
                    "role": "MAIN",
                    "status": "已获得",
                }
            ],
        },
    )
    monkeypatch.setattr(
        dashboard,
        "_project_release_artifact_state",
        lambda _project: {"integrity_valid": False},
    )

    payload = dashboard.project_progress_payload(tmp_path, "new-route")

    assert payload["active_stage"] == "final"
    assert [row["status"] for row in payload["stages"]] == [
        "complete",
        "complete",
        "complete",
        "complete",
        "complete",
        "complete",
        "complete",
        "complete",
        "active",
    ]
    assert payload["studies"][0]["status"] == "已完成"
    assert payload["recommended_next"] == "检查正文并导出 DOCX"


def test_review_html_loads_split_workspace_modules_and_hides_new_route_risk() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    html = (root / "view/assets/dashboard/review.html").read_text(encoding="utf-8")
    evidence = (root / "view/assets/dashboard/review-evidence.js").read_text(encoding="utf-8")
    synthesis = (root / "view/assets/dashboard/review-synthesis.js").read_text(encoding="utf-8")
    assert "/assets/dashboard/review-evidence.css" in html
    assert "/assets/dashboard/review-evidence.js" in html
    assert "/assets/dashboard/review-synthesis.js" in html
    assert "evidence-to-release.v1" in evidence
    assert "原论文图片" in synthesis
    assert "综合图制图任务" in synthesis
    assert "Coverage Map" in synthesis
    assert "protocol.evidence_ready" in synthesis
    assert "button.disabled = !synthesis.protocol_ready" in synthesis
    assert "item.pdf_page_url" in evidence
    assert "item.parsed_text_url" in evidence
    assert "item.image_url" in synthesis
    server = (root / "view/serve_review_dashboard.py").read_text(encoding="utf-8")
    assert "/source-figure" in server


def test_review_simulation_actor_is_exact_query_opt_in() -> None:
    root = Path(__file__).resolve().parents[1]
    html = (root / "view/assets/dashboard/review.html").read_text(encoding="utf-8")
    session = (root / "view/assets/dashboard/review-session.js").read_text(encoding="utf-8")
    evidence = (root / "view/assets/dashboard/review-evidence.js").read_text(encoding="utf-8")
    synthesis = (root / "view/assets/dashboard/review-synthesis.js").read_text(encoding="utf-8")

    assert html.index("/assets/dashboard/review-session.js") < html.index(
        "/assets/dashboard/review-evidence.js"
    )
    assert 'params.get("review_actor") === "simulated_researcher_agent"' in session
    assert 'actor_type: "simulated_researcher_agent"' in session
    assert 'actor_label: "dashboard-playwright-reviewer"' in session
    assert "window.reviewDecisionActor" in evidence
    assert "window.reviewDecisionActor" in synthesis
    assert "actor_label" in evidence
    assert "actor_label" in synthesis


@pytest.mark.parametrize(
    ("actor_fields", "expected"),
    [
        ({}, ("human_researcher", "local-researcher")),
        (
            {
                "actor_type": "simulated_researcher_agent",
                "actor_label": "dashboard-playwright-reviewer",
            },
            ("simulated_researcher_agent", "dashboard-playwright-reviewer"),
        ),
    ],
)
def test_workspace_api_preserves_explicit_actor_and_defaults_to_human(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    actor_fields: dict[str, str],
    expected: tuple[str, str],
) -> None:
    from view import serve_review_dashboard as dashboard

    project = tmp_path / "new-route"
    project.mkdir()
    row = {
        "evidence_id": "E-1",
        "candidate_digest": "a" * 64,
        "bound_parse_object_digests": ["b" * 64],
        "source_pdf_sha256": "c" * 64,
    }
    captured: dict[str, object] = {}
    monkeypatch.setattr(dashboard, "project_dir", lambda _root, _project_id: project)
    monkeypatch.setattr(dashboard, "paper_evidence_state", lambda _project: {"rows": [row]})
    monkeypatch.setattr(
        dashboard,
        "apply_paper_evidence_decision",
        lambda _project, payload: captured.update(payload),
    )
    monkeypatch.setattr(
        dashboard,
        "project_paper_evidence_payload",
        lambda _root, _project_id: {"status": "ok"},
    )
    payload = {
        "evidence_id": "E-1",
        "action": "approve",
        "reason": "Checked.",
        "version_token": dashboard._workspace_token(
            "paper-evidence", "E-1", row["candidate_digest"]
        ),
        **actor_fields,
    }

    dashboard.write_project_workspace_decision(
        tmp_path, "new-route", "paper-evidence", payload
    )

    assert (captured["actor_type"], captured["actor_label"]) == expected
