from __future__ import annotations

import io
import json
from pathlib import Path

import pytest


def _http_request(review_root: Path, raw_request: bytes) -> tuple[int, dict[str, str], bytes]:
    from view import serve_review_dashboard as dashboard

    class FakeSocket:
        def __init__(self, incoming: bytes) -> None:
            self.input = io.BytesIO(incoming)
            self.output = io.BytesIO()

        def makefile(self, mode: str, *args, **kwargs):
            return self.input if "r" in mode else self.output

        def sendall(self, data: bytes) -> None:
            self.output.write(data)

        def close(self) -> None:
            pass

    dashboard.DashboardHandler.review_root = review_root
    socket = FakeSocket(raw_request)
    dashboard.DashboardHandler(socket, ("127.0.0.1", 0), object())
    head, body = socket.output.getvalue().split(b"\r\n\r\n", 1)
    lines = head.decode("iso-8859-1").split("\r\n")
    headers = dict(line.split(": ", 1) for line in lines[1:] if ": " in line)
    return int(lines[0].split()[1]), headers, body


def _base_projection() -> dict[str, object]:
    return {
        "schema_version": "dual-parse-projection.v2",
        "status": "ready",
        "next_action": {"label": "继续补充可追溯候选", "description": "保留当前 gap。"},
        "project_status": "needs_review",
        "summary": {"core_studies": 1, "generic_current": 1},
        "studies": [
            {
                "study_id": "study-a",
                "source_tier": "core",
                "pdf_status": "verified",
                "generic_parse_status": "current",
                "chemical_import_status": "needs_review",
                "completion_status": "blocked",
                "reconciliation_status": "blocked",
                "paper_evidence_status": "blocked",
            }
        ],
        "import_preflight": None,
        "completion_queue": [
            {
                "study_id": "study-a",
                "molecule_index": 0,
                "version_token": "opaque-version",
                "field": "resolved_smiles",
                "page": 3,
                "bbox_normalized": [0.1, 0.2, 0.3, 0.4],
            },
            {
                "study_id": "study-a",
                "molecule_index": 1,
                "version_token": "opaque-version",
                "field": "resolved_smiles",
                "page": 4,
                "bbox_normalized": [0.2, 0.3, 0.4, 0.5],
            },
        ],
        "reconciliation_items": [],
        "unique_next_action": "completion",
    }


def _authoritative_molecules() -> list[dict[str, object]]:
    return [
        {
            "molecule_index": index,
            "resolved_smiles_status": (
                "AI_PROVISIONAL"
                if index == 0
                else "BLOCKED"
                if index == 1
                else "CONFIRMED"
                if index < 182
                else "AI_PROVISIONAL"
                if index < 241
                else "BLOCKED"
            ),
        }
        for index in range(309)
    ]


def _honest_completion_state() -> dict[str, object]:
    molecules = _authoritative_molecules()
    return {
        "schema_version": "chemical-completion-project-state.v2",
        "route": "honest_progressive",
        "core_molecule_count": 999,
        "confirmed_count": 0,
        "ai_provisional_count": 0,
        "blocked_count": 0,
        "coverage_ratio": 0.0,
        "coverage_threshold": 0.01,
        "coverage_sufficient": True,
        "workflow_can_continue": True,
        "coverage_denominator": 309,
        "compatibility_aggregation": {"mode": "project_core_309"},
        "molecules": molecules,
        "actor_provenance_residual": True,
        "uncertainty_statement": "/private/raw-state.json should never be returned",
        "gap_registry": [
            {
                "study_id": "study-a",
                "molecule_index": 1,
                "status": "BLOCKED",
                "value": "SECRET-BLOCKED-VALUE",
                "gap_reason": "PDF 仅给出 generic R-group",
                "pdf_locator": {
                    "page": 4,
                    "figure_label": "Figure 2",
                    "bbox": [0.2, 0.3, 0.4, 0.5],
                    "path": "/private/gap.json",
                    "sha256": "b" * 64,
                },
            },
            {"status": "AI_PROVISIONAL", "value": "must be excluded"},
        ],
        "studies": [
            {
                "study_id": "study-a",
                "study_molecule_count": 3,
                "study_confirmed_count": 1,
                "study_ai_provisional_count": 1,
                "study_blocked_count": 1,
                "coverage_ratio": 0.99,
                "coverage_threshold": 0.01,
                "workflow_can_continue": True,
                "uncertainty_statement": "raw study statement",
                "actor_provenance_residual": True,
                "molecules": molecules,
            }
        ],
    }


def _honest_chemical_projection() -> dict[str, object]:
    molecules = [
        {
            "molecule_index": 0,
            "resolved_smiles": "CCO",
            "resolved_smiles_status": "AI_PROVISIONAL",
            "confidence": 0.72,
            "provenance": {
                "source": "structure_figure",
                "pdf_locator": {"page": 3, "figure_label": "Scheme 1"},
                "evidence_excerpt": "RAW JSON SHOULD NOT LEAK",
                "path": "/private/provenance.json",
                "sha256": "c" * 64,
                "session": "private-session",
            },
            "pdf_locator": {"page": 3, "figure_label": "Scheme 1"},
            "gap_reason": None,
        },
        {
            "molecule_index": 1,
            "resolved_smiles": "SECRET-BLOCKED-VALUE",
            "resolved_smiles_status": "BLOCKED",
            "confidence": 0.88,
            "provenance": {
                "source": "should-not-be-used",
                "path": "/private/blocked.json",
            },
            "pdf_locator": {"page": 4, "figure_label": "Figure 2"},
            "gap_reason": "PDF 仅给出 generic R-group",
        },
    ]
    molecules.extend(
        {
            "molecule_index": index,
            "resolved_smiles": "CCO",
            "resolved_smiles_status": "AI_PROVISIONAL",
            "confidence": 0.7,
            "provenance": {
                "source": "structure_figure",
                "pdf_locator": {"page": 5},
            },
            "pdf_locator": {"page": 5},
            "gap_reason": None,
        }
        for index in range(2, 309)
    )
    return {
        "schema_version": "chemical-paper-projection.v2",
        "studies": [
            {
                "study_id": "study-a",
                "status": "needs_review",
                "molecule_count": 309,
                "reaction_data_status": "unavailable_not_provided",
                "molecules": molecules,
            }
        ],
    }


def _missing_chemical_completion_state() -> dict[str, object]:
    """Shape returned when the project has declared studies but no Chemical cohort."""
    return {
        "schema_version": "chemical-completion-project-state.v2",
        "route": "honest_progressive",
        "studies": [
            {
                "study_id": "study-a",
                "status": "blocked",
                "workflow_can_continue": False,
            }
        ],
        # These are the misleading values from the fresh no-import projection.
        "core_molecule_count": 309,
        "confirmed_count": 0,
        "ai_provisional_count": 0,
        "blocked_count": 0,
        "coverage_ratio": 0.0,
        "coverage_threshold": 0.8,
        "coverage_denominator": 0,
        "coverage_sufficient": False,
        "workflow_can_continue": False,
    }


def _missing_chemical_projection() -> dict[str, object]:
    return {
        "schema_version": "chemical-paper-projection.v2",
        "studies": [
            {
                "study_id": "study-a",
                "status": "missing",
                "molecule_count": None,
                "molecules": [],
            }
        ],
    }


def test_progress_exposes_honest_parse_quality_blocker_and_unique_next_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from view import serve_review_dashboard as dashboard

    project = tmp_path / "project"
    project.mkdir()
    bundle = project / "01_evidence" / "source_truth" / "study-a" / "bundle.json"
    bundle.parent.mkdir(parents=True)
    bundle.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(dashboard, "project_dir", lambda _root, _project_id: project)
    monkeypatch.setattr(
        dashboard,
        "workflow_state",
        lambda _project: {
            "route": "evidence-to-release.v1",
            "active_stage": "parsing",
            "paper_evidence_ready": False,
            "synthesis_ready": False,
            "section_contracts_ready": False,
            "manuscript_ready": False,
            "internal_draft_export_ready": False,
            "verified_release_ready": False,
            "blockers": ["PARSE_QUALITY_REVIEW_REQUIRED"],
        },
    )
    monkeypatch.setattr(
        dashboard,
        "project_parse_quality_state",
        lambda _project: {
            "status": "needs_review",
            "workflow_can_continue": False,
            "reason_code": None,
            "studies": [{"study_id": "study-a", "status": "needs_review"}],
        },
    )
    monkeypatch.setattr(
        dashboard,
        "project_source_handoff_payload",
        lambda _root, _project_id: {
            "counts": {"total": 3, "ready": 3},
            "sources": [
                {"study_id": "study-a", "role": "MAIN", "status": "已获得"}
            ],
        },
    )
    monkeypatch.setattr(dashboard, "project_evaluation_payload", lambda _project: {})

    payload = dashboard.project_progress_payload(tmp_path, "project")

    assert payload["active_stage"] == "parsing"
    assert payload["blocker_code"] == "PARSE_QUALITY_REVIEW_REQUIRED"
    assert "Generic" in payload["blocker"]
    assert payload["recommended_next"] == "核对解析质量后继续"


def test_dual_parse_api_projects_server_calculated_honest_progressive_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from view import serve_review_dashboard as dashboard

    review_root = tmp_path / "review-root"
    (review_root / "review-projects" / "project").mkdir(parents=True)
    monkeypatch.setattr(dashboard, "dual_parse_dashboard_projection", lambda _: _base_projection())
    monkeypatch.setattr(
        dashboard,
        "project_chemical_completion_state",
        lambda _: _honest_completion_state(),
        raising=False,
    )
    monkeypatch.setattr(
        dashboard,
        "chemical_paper_projection",
        lambda _: _honest_chemical_projection(),
    )

    status, _, body = _http_request(
        review_root,
        b"GET /api/project/project/dual-parse HTTP/1.1\r\nHost: localhost\r\n\r\n",
    )

    assert status == 200
    payload = json.loads(body)
    assert payload["route"] == "honest_progressive"
    honest = payload["honest_progressive"]
    assert honest["availability"] == "available"
    assert honest["status"] == "ready"
    assert honest["core_molecule_count"] == 309
    assert honest["coverage_denominator"] == 309
    assert honest["coverage_threshold"] == pytest.approx(0.8)
    assert honest["confirmed_count"] == 180
    assert honest["ai_provisional_count"] == 60
    assert honest["blocked_count"] == 69
    assert honest["coverage_ratio"] == pytest.approx(240 / 309)
    assert honest["coverage_sufficient"] is False
    assert honest["actor_provenance_residual"] is True
    assert honest["credits_status"] == "NOT_APPLICABLE_BY_CURRENT_SCOPE"
    assert len(honest["paper_coverage"]) == 1
    assert honest["paper_coverage"][0]["coverage_ratio"] == pytest.approx(2 / 3)
    assert honest["paper_coverage"][0]["coverage_sufficient"] is False
    assert [row["status"] for row in honest["gap_registry"]] == ["BLOCKED"]
    assert honest["gap_registry"][0]["value"] is None
    assert honest["gap_registry"][0]["gap_reason"] == "PDF 仅给出 generic R-group"

    provisional = next(row for row in payload["completion_queue"] if row["molecule_index"] == 0)
    assert provisional["resolved_smiles_status"] == "AI_PROVISIONAL"
    assert provisional["resolved_smiles"] == "CCO"
    assert provisional["confidence"] == pytest.approx(0.72)
    assert provisional["provenance"] == {
        "source": "structure_figure",
        "pdf_locator": {"page": 3, "figure_label": "Scheme 1"},
    }
    blocked = next(row for row in payload["completion_queue"] if row["molecule_index"] == 1)
    assert blocked["resolved_smiles_status"] == "BLOCKED"
    assert blocked["resolved_smiles"] is None
    assert blocked["confidence"] is None
    assert blocked["provenance"] is None
    assert blocked["gap_reason"] == "PDF 仅给出 generic R-group"

    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    for forbidden in (
        "/private/",
        "sha256",
        "RAW JSON SHOULD NOT LEAK",
        "SECRET-BLOCKED-VALUE",
        "private-session",
        "evidence_excerpt",
    ):
        assert forbidden not in encoded


def test_dual_parse_api_fails_closed_when_honest_state_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from view import serve_review_dashboard as dashboard

    review_root = tmp_path / "review-root"
    (review_root / "review-projects" / "project").mkdir(parents=True)
    monkeypatch.setattr(dashboard, "dual_parse_dashboard_projection", lambda _: _base_projection())

    def unavailable(_: Path) -> dict[str, object]:
        raise ValueError("CHEMICAL_COMPLETION_NOT_AVAILABLE")

    monkeypatch.setattr(
        dashboard, "project_chemical_completion_state", unavailable, raising=False
    )

    status, _, body = _http_request(
        review_root,
        b"GET /api/project/project/dual-parse HTTP/1.1\r\nHost: localhost\r\n\r\n",
    )

    assert status == 200
    payload = json.loads(body)
    honest = payload["honest_progressive"]
    assert payload["route"] == "honest_progressive"
    assert honest["availability"] in {"unknown", "unavailable"}
    assert honest["status"] == "unknown"
    assert honest["core_molecule_count"] is None
    assert honest["coverage_denominator"] is None
    assert honest["coverage_threshold"] == pytest.approx(0.8)
    assert honest["confirmed_count"] is None
    assert honest["ai_provisional_count"] is None
    assert honest["blocked_count"] is None
    assert honest["coverage_ratio"] is None
    assert honest["coverage_sufficient"] is None
    assert honest["paper_coverage"] == []
    assert honest["gap_registry"] == []
    assert honest["actor_provenance_residual"] is None
    assert honest["credits_status"] == "NOT_APPLICABLE_BY_CURRENT_SCOPE"
    assert payload["completion_queue"] == _base_projection()["completion_queue"]


def test_dual_parse_api_keeps_missing_chemical_import_unknown_instead_of_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from view import serve_review_dashboard as dashboard

    review_root = tmp_path / "review-root"
    (review_root / "review-projects" / "project").mkdir(parents=True)
    monkeypatch.setattr(dashboard, "dual_parse_dashboard_projection", lambda _: _base_projection())
    monkeypatch.setattr(
        dashboard,
        "project_chemical_completion_state",
        lambda _: _missing_chemical_completion_state(),
        raising=False,
    )
    monkeypatch.setattr(
        dashboard,
        "chemical_paper_projection",
        lambda _: _missing_chemical_projection(),
    )

    status, _, body = _http_request(
        review_root,
        b"GET /api/project/project/dual-parse HTTP/1.1\r\nHost: localhost\r\n\r\n",
    )

    assert status == 200
    payload = json.loads(body)
    honest = payload["honest_progressive"]
    assert payload["route"] == "honest_progressive"
    assert honest["availability"] in {"unknown", "unavailable"}
    assert honest["status"] == "unknown"
    for field in (
        "core_molecule_count",
        "coverage_denominator",
        "confirmed_count",
        "ai_provisional_count",
        "blocked_count",
        "coverage_ratio",
        "coverage_sufficient",
        "workflow_can_continue",
    ):
        assert honest[field] is None, field
    assert honest["gap_registry"] == []
    assert "待 Chemical Paper 导入" in honest["uncertainty_statement"]
    assert honest["credits_status"] == "NOT_APPLICABLE_BY_CURRENT_SCOPE"
    encoded = json.dumps(payload, ensure_ascii=False)
    assert "已完成" not in encoded
    assert "0 个已确认" not in encoded
