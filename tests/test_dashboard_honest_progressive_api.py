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


def _authoritative_study_molecules(
    offset: int, molecule_count: int
) -> list[dict[str, object]]:
    source = _authoritative_molecules()
    return [
        {
            **source[offset + molecule_index],
            "molecule_index": molecule_index,
        }
        for molecule_index in range(molecule_count)
    ]


def _honest_completion_state() -> dict[str, object]:
    study_specs = (
        ("study-a", 0, 125),
        ("study-b", 125, 109),
        ("study-c", 234, 75),
    )
    studies: list[dict[str, object]] = []
    molecules: list[dict[str, object]] = []
    for study_id, offset, molecule_count in study_specs:
        study_molecules = _authoritative_study_molecules(offset, molecule_count)
        counts = {
            status: sum(
                molecule["resolved_smiles_status"] == status
                for molecule in study_molecules
            )
            for status in ("CONFIRMED", "AI_PROVISIONAL", "BLOCKED")
        }
        studies.append(
            {
                "study_id": study_id,
                "source_tier": "core",
                "status": "current",
                "study_molecule_count": molecule_count,
                "study_confirmed_count": counts["CONFIRMED"],
                "study_ai_provisional_count": counts["AI_PROVISIONAL"],
                "study_blocked_count": counts["BLOCKED"],
                "coverage_ratio": (
                    counts["CONFIRMED"] + counts["AI_PROVISIONAL"]
                )
                / molecule_count,
                "coverage_threshold": 0.8,
                "workflow_can_continue": True,
                "uncertainty_statement": "raw study statement",
                "actor_provenance_residual": True,
                "molecules": study_molecules,
            }
        )
        molecules.extend(
            {"study_id": study_id, **molecule} for molecule in study_molecules
        )
    return {
        "schema_version": "chemical-completion-project-state.v2",
        "route": "honest_progressive",
        "core_molecule_count": 309,
        "confirmed_count": 180,
        "ai_provisional_count": 60,
        "blocked_count": 69,
        "coverage_ratio": 240 / 309,
        "coverage_threshold": 0.8,
        "coverage_sufficient": False,
        "workflow_can_continue": False,
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
        "studies": studies,
    }


def _honest_chemical_projection() -> dict[str, object]:
    study_specs = (
        ("study-a", 0, 125, 6),
        ("study-b", 125, 109, 11),
        ("study-c", 234, 75, 11),
    )
    studies: list[dict[str, object]] = []
    for study_id, offset, molecule_count, page_count in study_specs:
        molecules: list[dict[str, object]] = []
        for molecule in _authoritative_study_molecules(offset, molecule_count):
            index = int(molecule["molecule_index"])
            status = molecule["resolved_smiles_status"]
            if study_id == "study-a" and index == 0:
                molecules.append(
                    {
                        "molecule_index": index,
                        "resolved_smiles": "CCO",
                        "resolved_smiles_status": status,
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
                    }
                )
            elif study_id == "study-a" and index == 1:
                molecules.append(
                    {
                        "molecule_index": index,
                        "resolved_smiles": "SECRET-BLOCKED-VALUE",
                        "resolved_smiles_status": status,
                        "confidence": 0.88,
                        "provenance": {
                            "source": "should-not-be-used",
                            "path": "/private/blocked.json",
                        },
                        "pdf_locator": {"page": 4, "figure_label": "Figure 2"},
                        "gap_reason": "PDF 仅给出 generic R-group",
                    }
                )
            else:
                molecules.append(
                    {
                        "molecule_index": index,
                        "resolved_smiles": "CCO" if status != "BLOCKED" else None,
                        "resolved_smiles_status": status,
                        "confidence": 0.7 if status == "AI_PROVISIONAL" else None,
                        "provenance": (
                            {
                                "source": "structure_figure",
                                "pdf_locator": {"page": 5},
                            }
                            if status != "BLOCKED"
                            else None
                        ),
                        "pdf_locator": {"page": 5},
                        "gap_reason": (
                            None
                            if status != "BLOCKED"
                            else "PDF 仅给出 generic R-group"
                        ),
                    }
                )
        studies.append(
            {
                "study_id": study_id,
                "source_tier": "core",
                "status": "needs_review",
                "pdf_binding_status": "bound",
                "page_count": page_count,
                "molecule_count": molecule_count,
                "reaction_data_status": "unavailable_not_provided",
                "molecules": molecules,
            }
        )
    return {
        "schema_version": "chemical-paper-projection.v2",
        "studies": studies,
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
    assert honest["status"] == "needs_more_traceable_candidates"
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
    assert len(honest["paper_coverage"]) == 3
    paper_coverage = {
        row["study_id"]: row for row in honest["paper_coverage"]
    }
    assert {
        row["coverage_denominator"] for row in paper_coverage.values()
    } == {125, 109, 75}
    assert paper_coverage["study-a"]["coverage_denominator"] == 125
    assert paper_coverage["study-b"]["coverage_denominator"] == 109
    assert paper_coverage["study-c"]["coverage_denominator"] == 75
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


@pytest.mark.parametrize(
    "invalid_shape",
    ("single_study", "wrong_page_count", "wrong_molecule_count", "wrong_reaction_status"),
)
def test_honest_authority_requires_exact_three_paper_contract(
    invalid_shape: str,
) -> None:
    from view import serve_review_dashboard as dashboard

    completion = _honest_completion_state()
    chemical = _honest_chemical_projection()
    if invalid_shape == "single_study":
        completion["studies"] = completion["studies"][:1]
        chemical["studies"] = chemical["studies"][:1]
    elif invalid_shape == "wrong_page_count":
        chemical["studies"][0]["page_count"] = 11
    elif invalid_shape == "wrong_molecule_count":
        completion["studies"][0]["study_molecule_count"] = 309
    else:
        chemical["studies"][0]["reaction_data_status"] = "available"

    summary, state_available, _ = dashboard._honest_progressive_summary(
        completion, chemical
    )

    assert state_available is False
    assert summary["status"] == "unknown"
    assert summary["availability"] == "unknown"
    assert summary["gap_registry"] is None


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
    assert honest["gap_registry"] is None
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
    assert honest["gap_registry"] is None
    assert "待 Chemical Paper 导入" in honest["uncertainty_statement"]
    assert honest["credits_status"] == "NOT_APPLICABLE_BY_CURRENT_SCOPE"
    encoded = json.dumps(payload, ensure_ascii=False)
    assert "已完成" not in encoded
    assert "0 个已确认" not in encoded
