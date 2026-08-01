from __future__ import annotations

import json
from pathlib import Path


def _declared_project(tmp_path: Path, study_ids: list[str]) -> Path:
    project = tmp_path / "review-projects" / "synthetic-scaled"
    sources = project / "00_sources"
    sources.mkdir(parents=True)
    (sources / "acquisition_final_receipt.json").write_text(
        json.dumps(
            {
                "schema_version": "synthetic-acquisition-receipt.v1",
                "studies": [{"study_id": study_id} for study_id in study_ids],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return project


def _scaled_completion(study_ids: list[str]) -> dict[str, object]:
    studies = []
    for study_id in study_ids:
        studies.append(
            {
                "study_id": study_id,
                "source_tier": "core",
                "status": "blocked",
                "study_molecule_count": 2,
                "study_confirmed_count": 0,
                "study_ai_provisional_count": 0,
                "study_blocked_count": 2,
                "molecules": [
                    {
                        "molecule_index": 0,
                        "resolved_smiles_status": "BLOCKED",
                        "resolved_smiles": "SECRET-BLOCKED-VALUE",
                        "molblock": "M  END",
                        "private_path": "/private/synthetic.json",
                    },
                    {
                        "molecule_index": 1,
                        "resolved_smiles_status": "BLOCKED",
                        "resolved_smiles": None,
                    },
                ],
            }
        )
    return {
        "schema_version": "chemical-completion-project-state.v2",
        "route": "honest_progressive",
        "core_molecule_count": len(study_ids) * 2,
        "coverage_denominator": len(study_ids) * 2,
        "confirmed_count": 0,
        "ai_provisional_count": 0,
        "blocked_count": len(study_ids) * 2,
        "coverage_ratio": 0,
        "coverage_sufficient": False,
        "workflow_can_continue": False,
        "compatibility_aggregation": {"mode": "project_core"},
        "studies": studies,
    }


def _scaled_chemical(study_ids: list[str]) -> dict[str, object]:
    return {
        "schema_version": "chemical-paper-projection.v2",
        "studies": [
            {
                "study_id": study_id,
                "source_tier": "core",
                "status": "ready",
                "pdf_binding_status": "bound",
                "page_count": 2,
                "molecule_count": 2,
                "reaction_data_status": "unavailable_not_provided",
                "molecules": [
                    {"molecule_index": 0},
                    {"molecule_index": 1},
                ],
            }
            for study_id in study_ids
        ],
    }


def test_dashboard_projection_uses_declared_studies_and_hides_internal_values(
    tmp_path: Path, monkeypatch
) -> None:
    from view import serve_review_dashboard as dashboard

    study_ids = ["study-a", "study-b", "study-c", "study-d"]
    project = _declared_project(tmp_path, study_ids)
    monkeypatch.setattr(
        dashboard,
        "project_chemical_completion_state",
        lambda _project: _scaled_completion(study_ids),
    )
    monkeypatch.setattr(
        dashboard,
        "chemical_paper_projection",
        lambda _project: _scaled_chemical(study_ids),
    )
    monkeypatch.setattr(
        dashboard,
        "project_chemical_completion_candidates",
        lambda _project, _study_id: {},
    )

    payload = dashboard.project_honest_progressive_dashboard_projection(
        project,
        {
            "schema_version": "dual-parse-projection.v2",
            "status": "ready",
            "studies": [],
            "completion_queue": [],
        },
    )

    honest = payload["honest_progressive"]
    assert honest["availability"] == "available"
    assert honest["coverage_denominator"] == 8
    assert honest["core_molecule_count"] == 8
    assert len(honest["paper_coverage"]) == len(study_ids)
    assert {row["coverage_denominator"] for row in honest["paper_coverage"]} == {2}

    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    for forbidden in (
        "SECRET-BLOCKED-VALUE",
        "M  END",
        "/private/synthetic.json",
        "private_path",
    ):
        assert forbidden not in encoded
