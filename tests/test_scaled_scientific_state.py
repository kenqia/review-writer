from __future__ import annotations

import json
from pathlib import Path

from review_writer.project.chemical_completion import (
    chemical_completion_state,
    project_chemical_completion_state,
)
from review_writer.project.chemical_paper import import_chemical_paper
from review_writer.project.source_truth import load_source_truth_bundle
from test_chemical_paper_import import (
    ACTOR,
    expand_source_truth_studies,
    source_truth_project,
    v2000,
    write_chemical_zip,
)


def _scaled_core_project(tmp_path: Path) -> Path:
    project = source_truth_project(tmp_path, pages=1)
    study_ids = expand_source_truth_studies(project, 3)
    (project / "00_discovery").mkdir(parents=True, exist_ok=True)
    (project / "00_discovery/candidate_pool.json").write_text(
        json.dumps(
            {
                "schema_version": "candidate-pool.v1",
                "candidates": [
                    {"candidate_id": study_ids[0], "study_id": study_ids[0], "tier": "core"},
                    {"candidate_id": study_ids[1], "study_id": study_ids[1], "tier": "core"},
                    {"candidate_id": study_ids[2], "study_id": study_ids[2], "tier": "background"},
                ],
            }
        ),
        encoding="utf-8",
    )
    for index, study_id in enumerate(study_ids):
        source_sha = load_source_truth_bundle(project, study_id)["sources"][0]["pdf"]["sha256"]
        archive = write_chemical_zip(
            tmp_path / f"chemical-{index}.zip",
            pages=1,
            molecules=[
                {
                    "mol_id": f"mol-{index}",
                    "page_idx": 0,
                    "bbox_normalized": [0.1, 0.2, 0.3, 0.4],
                    "smiles_expanded": "CO",
                    "smiles_unexpanded": "",
                    "mol_idt": f"compound-{index}",
                    "mol_block": v2000(),
                }
            ],
        )
        import_chemical_paper(project, study_id, source_sha, archive, ACTOR)
    return project


def test_scaled_core_denominator_uses_current_core_states_not_309(tmp_path: Path) -> None:
    project = _scaled_core_project(tmp_path)

    study_view = chemical_completion_state(project, "study-1")
    project_view = project_chemical_completion_state(project)

    for view in (study_view, project_view):
        assert view["project_molecule_count"] == 2
        assert view["core_molecule_count"] == 2
        assert view["coverage_denominator"] == 2
        assert view["confirmed_count"] == 0
        assert view["ai_provisional_count"] == 2
        assert view["blocked_count"] == 0
        assert view["coverage_ratio"] == 1.0
        assert view["workflow_can_continue"] is True
