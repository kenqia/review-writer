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
    assert "actor_label" not in evidence
    assert "actor_label" not in synthesis


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
