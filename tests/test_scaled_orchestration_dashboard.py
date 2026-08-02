from __future__ import annotations

import json
from pathlib import Path

import pytest


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


def _tiered_project(tmp_path: Path, study_tiers: list[tuple[str, str]]) -> Path:
    project = _declared_project(tmp_path, [study_id for study_id, _ in study_tiers])
    discovery = project / "00_discovery"
    discovery.mkdir()
    (discovery / "candidate_pool.json").write_text(
        json.dumps(
            {
                "schema_version": "candidate-pool.v1",
                "candidates": [
                    {
                        "candidate_id": study_id,
                        "study_id": study_id,
                        "tier": tier,
                    }
                    for study_id, tier in study_tiers
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return project


def _tiered_completion(
    study_specs: list[tuple[str, str, list[str]]],
) -> dict[str, object]:
    studies = []
    for study_id, _tier, statuses in study_specs:
        counts = {
            status: statuses.count(status)
            for status in ("CONFIRMED", "AI_PROVISIONAL", "BLOCKED")
        }
        studies.append(
            {
                "study_id": study_id,
                "status": "blocked",
                "study_molecule_count": len(statuses),
                "study_confirmed_count": counts["CONFIRMED"],
                "study_ai_provisional_count": counts["AI_PROVISIONAL"],
                "study_blocked_count": counts["BLOCKED"],
                "molecules": [
                    {
                        "molecule_index": index,
                        "resolved_smiles_status": status,
                    }
                    for index, status in enumerate(statuses)
                ],
            }
        )
    core_statuses = [
        status
        for _study_id, tier, statuses in study_specs
        for status in statuses
        if tier == "core"
    ]
    counts = {
        status: core_statuses.count(status)
        for status in ("CONFIRMED", "AI_PROVISIONAL", "BLOCKED")
    }
    denominator = len(core_statuses)
    return {
        "schema_version": "chemical-completion-project-state.v2",
        "route": "honest_progressive",
        "core_molecule_count": denominator,
        "coverage_denominator": denominator,
        "confirmed_count": counts["CONFIRMED"],
        "ai_provisional_count": counts["AI_PROVISIONAL"],
        "blocked_count": counts["BLOCKED"],
        "coverage_ratio": (
            (counts["CONFIRMED"] + counts["AI_PROVISIONAL"]) / denominator
            if denominator
            else None
        ),
        "coverage_sufficient": False,
        "workflow_can_continue": False,
        "compatibility_aggregation": {"mode": "project_core"},
        "studies": studies,
    }


def _tiered_chemical(
    study_specs: list[tuple[str, str, list[str]]],
) -> dict[str, object]:
    return {
        "schema_version": "chemical-paper-projection.v2",
        "studies": [
            {
                "study_id": study_id,
                "status": "ready",
                "pdf_binding_status": "bound",
                "page_count": 1,
                "molecule_count": len(statuses),
                "reaction_data_status": "unavailable_not_provided",
                "molecules": [
                    {"molecule_index": index}
                    for index in range(len(statuses))
                ],
            }
            for study_id, _tier, statuses in study_specs
        ],
    }


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


def _legacy_authoritative_completion() -> dict[str, object]:
    study_specs = [
        ("study-a", "core", ["CONFIRMED"] * 125),
        ("study-b", "core", ["CONFIRMED"] * 109),
        ("study-c", "core", ["CONFIRMED"] * 75),
    ]
    completion = _tiered_completion(study_specs)
    completion["compatibility_aggregation"] = {"mode": "project_core_309"}
    return completion


def _legacy_authoritative_chemical() -> dict[str, object]:
    study_specs = (
        ("study-a", 125, 6),
        ("study-b", 109, 11),
        ("study-c", 75, 11),
    )
    return {
        "schema_version": "chemical-paper-projection.v2",
        "studies": [
            {
                "study_id": study_id,
                "status": "ready",
                "pdf_binding_status": "bound",
                "page_count": page_count,
                "molecule_count": molecule_count,
                "reaction_data_status": "unavailable_not_provided",
                "molecules": [
                    {"molecule_index": index}
                    for index in range(molecule_count)
                ],
            }
            for study_id, molecule_count, page_count in study_specs
        ],
    }


def test_dashboard_projection_uses_declared_studies_and_hides_internal_values(
    tmp_path: Path, monkeypatch
) -> None:
    from view import serve_review_dashboard as dashboard

    study_ids = ["study-a", "study-b", "study-c", "study-d"]
    project = _tiered_project(tmp_path, [(study_id, "core") for study_id in study_ids])
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


def test_dashboard_projection_excludes_background_from_core_gate_but_keeps_visible_coverage(
    tmp_path: Path, monkeypatch
) -> None:
    from view import serve_review_dashboard as dashboard

    study_specs = [
        ("core-a", "core", ["CONFIRMED", "BLOCKED"]),
        ("background-a", "background", ["AI_PROVISIONAL", "BLOCKED"]),
    ]
    project = _tiered_project(
        tmp_path,
        [("core-a", "core"), ("background-a", "background")],
    )
    monkeypatch.setattr(
        dashboard,
        "project_chemical_completion_state",
        lambda _project: _tiered_completion(study_specs),
    )
    monkeypatch.setattr(
        dashboard,
        "chemical_paper_projection",
        lambda _project: _tiered_chemical(study_specs),
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
            "studies": [
                {"study_id": "core-a", "source_tier": "core"},
                {"study_id": "background-a", "source_tier": "background"},
            ],
            "completion_queue": [
                {"study_id": "core-a", "molecule_index": 0, "field": "resolved_smiles"},
                {"study_id": "background-a", "molecule_index": 0, "field": "resolved_smiles"},
            ],
        },
    )

    honest = payload["honest_progressive"]
    assert honest["availability"] == "available"
    assert honest["coverage_denominator"] == 2
    assert honest["confirmed_count"] == 1
    assert honest["ai_provisional_count"] == 0
    assert honest["blocked_count"] == 1
    assert honest["coverage_ratio"] == 0.5
    assert honest["workflow_can_continue"] is False
    assert "项目级 2 个 core molecules" in honest["uncertainty_statement"]

    coverage = {row["study_id"]: row for row in honest["paper_coverage"]}
    assert set(coverage) == {"core-a", "background-a"}
    assert coverage["core-a"]["source_tier"] == "core"
    assert coverage["background-a"]["source_tier"] == "background"
    assert coverage["core-a"]["coverage_denominator"] == 2
    assert coverage["background-a"]["coverage_denominator"] == 2
    assert coverage["background-a"]["coverage_ratio"] == 0.5
    assert "background molecules" in coverage["background-a"]["uncertainty_statement"]

    visible = {row["study_id"]: row for row in payload["studies"]}
    assert visible["core-a"]["source_tier"] == "core"
    assert visible["background-a"]["source_tier"] == "background"
    assert visible["background-a"]["coverage_denominator"] == 2
    assert [row["study_id"] for row in payload["completion_queue"]] == ["core-a"]


def test_dashboard_projection_uses_only_core_rows_for_variable_n_tiered_denominator(
    tmp_path: Path, monkeypatch
) -> None:
    from view import serve_review_dashboard as dashboard

    study_specs = [
        ("core-a", "core", ["CONFIRMED", "BLOCKED"]),
        ("core-b", "core", ["AI_PROVISIONAL", "BLOCKED", "BLOCKED"]),
        ("background-a", "background", ["CONFIRMED", "AI_PROVISIONAL", "BLOCKED", "BLOCKED"]),
    ]
    project = _tiered_project(
        tmp_path,
        [
            ("core-a", "core"),
            ("core-b", "core"),
            ("background-a", "background"),
        ],
    )
    monkeypatch.setattr(
        dashboard,
        "project_chemical_completion_state",
        lambda _project: _tiered_completion(study_specs),
    )
    monkeypatch.setattr(
        dashboard,
        "chemical_paper_projection",
        lambda _project: _tiered_chemical(study_specs),
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
            "studies": [
                {"study_id": study_id, "source_tier": tier}
                for study_id, tier in (
                    ("core-a", "core"),
                    ("core-b", "core"),
                    ("background-a", "background"),
                )
            ],
            "completion_queue": [],
        },
    )

    honest = payload["honest_progressive"]
    assert honest["coverage_denominator"] == 5
    assert honest["core_molecule_count"] == 5
    assert honest["confirmed_count"] == 1
    assert honest["ai_provisional_count"] == 1
    assert honest["blocked_count"] == 3
    assert honest["coverage_ratio"] == 0.4
    assert honest["workflow_can_continue"] is False
    assert "项目级 5 个 core molecules" in honest["uncertainty_statement"]
    assert {
        row["study_id"]: row["coverage_denominator"]
        for row in honest["paper_coverage"]
    } == {"core-a": 2, "core-b": 3, "background-a": 4}


@pytest.mark.parametrize("invalid_authority", ("receipt", "tier"))
def test_dashboard_projection_fails_closed_for_invalid_current_authority(
    tmp_path: Path, monkeypatch, invalid_authority: str
) -> None:
    from view import serve_review_dashboard as dashboard

    study_ids = ["study-a", "study-b", "study-c"]
    project = _declared_project(tmp_path, study_ids)
    receipt_path = project / "00_sources/acquisition_final_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if invalid_authority == "receipt":
        receipt["studies"] = [
            {"study_id": "study-a"},
            {"study_id": "study-a"},
            {"study_id": "study-c"},
        ]
    else:
        receipt.update(
            {
                "corpus_kind": "authoritative_variable_n",
                "variable_n": True,
                "study_count": len(study_ids),
            }
        )
        discovery = project / "00_discovery"
        discovery.mkdir()
        (discovery / "candidate_pool.json").write_text(
            json.dumps(
                {
                    "schema_version": "candidate-pool.v1",
                    "candidates": [
                        {
                            "candidate_id": study_id,
                            "study_id": study_id,
                            "tier": "not-a-tier" if index == 0 else "core",
                        }
                        for index, study_id in enumerate(study_ids)
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )
    receipt_path.write_text(json.dumps(receipt) + "\n", encoding="utf-8")

    monkeypatch.setattr(
        dashboard,
        "project_chemical_completion_state",
        lambda _project: _legacy_authoritative_completion(),
    )
    monkeypatch.setattr(
        dashboard,
        "chemical_paper_projection",
        lambda _project: _legacy_authoritative_chemical(),
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
    assert honest["availability"] == "unknown"
    assert honest["status"] == "unknown"
    assert honest["core_molecule_count"] is None
    assert honest["coverage_denominator"] is None
    assert honest["confirmed_count"] is None
    assert honest["ai_provisional_count"] is None
    assert honest["blocked_count"] is None
    assert honest["coverage_ratio"] is None
    assert honest["coverage_sufficient"] is None
    assert honest["workflow_can_continue"] is None
    assert honest["paper_coverage"] == []
    assert payload["completion_queue"] == []


@pytest.mark.parametrize(
    "invalid_tier_map",
    ("extra_stale", "missing", "duplicate", "wrong_binding"),
)
def test_dashboard_projection_fails_closed_for_non_exact_current_tier_map(
    tmp_path: Path, monkeypatch, invalid_tier_map: str
) -> None:
    from view import serve_review_dashboard as dashboard

    study_ids = ["study-a", "study-b", "study-c"]
    study_specs = [(study_id, "core", ["BLOCKED"]) for study_id in study_ids]
    project = _tiered_project(
        tmp_path, [(study_id, "core") for study_id in study_ids]
    )
    tier_manifest = project / "00_discovery/candidate_pool.json"
    tier_payload = json.loads(tier_manifest.read_text(encoding="utf-8"))
    candidates = tier_payload["candidates"]
    if invalid_tier_map == "extra_stale":
        candidates.append(
            {
                "candidate_id": "stale-study",
                "study_id": "stale-study",
                "tier": "core",
            }
        )
    elif invalid_tier_map == "missing":
        candidates.pop()
    elif invalid_tier_map == "duplicate":
        candidates.extend(
            [
                {
                    "candidate_id": "stale-study",
                    "study_id": "stale-study",
                    "tier": "core",
                },
                {
                    "candidate_id": "stale-study",
                    "study_id": "stale-study",
                    "tier": "background",
                },
            ]
        )
    else:
        candidates[0]["study_id"] = "stale-study"
    tier_manifest.write_text(
        json.dumps(tier_payload) + "\n", encoding="utf-8"
    )

    monkeypatch.setattr(
        dashboard,
        "project_chemical_completion_state",
        lambda _project: _tiered_completion(study_specs),
    )
    monkeypatch.setattr(
        dashboard,
        "chemical_paper_projection",
        lambda _project: _tiered_chemical(study_specs),
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
    assert honest["availability"] == "unknown"
    assert honest["status"] == "unknown"
    assert honest["core_molecule_count"] is None
    assert honest["coverage_denominator"] is None
    assert honest["confirmed_count"] is None
    assert honest["ai_provisional_count"] is None
    assert honest["blocked_count"] is None
    assert honest["coverage_ratio"] is None
    assert honest["coverage_sufficient"] is None
    assert honest["workflow_can_continue"] is None
    assert honest["paper_coverage"] == []
    assert payload["completion_queue"] == []


def test_dashboard_projection_fails_closed_for_current_variable_n_without_tier_map(
    tmp_path: Path, monkeypatch
) -> None:
    from view import serve_review_dashboard as dashboard

    study_ids = ["study-a", "study-b", "study-c", "study-d"]
    project = _declared_project(tmp_path, study_ids)
    receipt_path = project / "00_sources/acquisition_final_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt.update(
        {
            "corpus_kind": "authoritative_variable_n",
            "variable_n": True,
            "study_count": len(study_ids),
        }
    )
    receipt_path.write_text(json.dumps(receipt) + "\n", encoding="utf-8")

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
    assert honest["availability"] == "unknown"
    assert honest["status"] == "unknown"
    assert honest["core_molecule_count"] is None
    assert honest["coverage_denominator"] is None
    assert honest["confirmed_count"] is None
    assert honest["ai_provisional_count"] is None
    assert honest["blocked_count"] is None
    assert honest["coverage_sufficient"] is None
    assert honest["workflow_can_continue"] is None
    assert honest["paper_coverage"] == []
    assert payload["completion_queue"] == []


def test_dashboard_projection_keeps_explicit_legacy_compatibility_without_tier_map(
    tmp_path: Path, monkeypatch
) -> None:
    from view import serve_review_dashboard as dashboard

    study_ids = ["legacy-a", "legacy-b", "legacy-c"]
    project = _declared_project(tmp_path, study_ids)
    receipt_path = project / "00_sources/acquisition_final_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt.update(
        {
            "corpus_kind": "legacy_three_paper",
            "variable_n": False,
            "study_count": len(study_ids),
        }
    )
    receipt_path.write_text(json.dumps(receipt) + "\n", encoding="utf-8")

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
    assert honest["coverage_denominator"] == 6
    assert honest["core_molecule_count"] == 6
    assert honest["confirmed_count"] == 0
    assert honest["blocked_count"] == 6
