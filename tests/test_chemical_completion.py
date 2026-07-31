from __future__ import annotations

import json
from pathlib import Path

import pytest

from review_writer.project.chemical_completion import (
    ChemicalCompletionError,
    apply_chemical_completion_batch,
    chemical_completion_state,
    require_chemical_completion_ready,
)
from review_writer.project.chemical_paper import import_chemical_paper
from review_writer.project.source_truth import load_source_truth_bundle
from test_chemical_paper_import import ACTOR, snapshot, v2000, write_chemical_zip
from test_parse_quality import _parse_project


def completion_project(tmp_path: Path) -> Path:
    project = _parse_project(tmp_path)
    (project / "00_discovery").mkdir(parents=True, exist_ok=True)
    (project / "00_discovery/candidate_pool.json").write_text(json.dumps({
        "schema_version": "candidate-pool.v1",
        "candidates": [{"candidate_id": "scholarly-a", "study_id": "scholarly-a", "tier": "core"}],
    }), encoding="utf-8")
    source_sha = load_source_truth_bundle(project, "scholarly-a")["sources"][0]["pdf"]["sha256"]
    archive = write_chemical_zip(tmp_path / "chemical.zip", pages=1, molecules=[{
        "mol_id": "mol-a", "page_idx": 0, "bbox_normalized": [0.1, 0.2, 0.3, 0.4],
        "smiles_expanded": "", "smiles_unexpanded": "", "mol_idt": "", "mol_block": v2000(),
    }])
    import_chemical_paper(project, "scholarly-a", source_sha, archive, ACTOR)
    return project


def test_core_requires_name_and_one_resolved_smiles_for_every_molecule(tmp_path: Path) -> None:
    gate = chemical_completion_state(completion_project(tmp_path), "scholarly-a")

    assert gate["missing_name_count"] == 1
    assert gate["missing_resolved_smiles_count"] == 1
    assert gate["ai_authored_smiles_count"] == 0
    assert gate["workflow_can_continue"] is False


def test_batch_is_atomic_and_researcher_attributed(tmp_path: Path) -> None:
    project = completion_project(tmp_path)
    gate = chemical_completion_state(project, "scholarly-a")

    result = apply_chemical_completion_batch(project, "scholarly-a", {
        "version_token": gate["version_token"],
        "actor_type": "simulated_researcher_agent", "actor_label": "simulated_researcher",
        "corrections": [
            {"molecule_index": 0, "field": "mol_idt", "value": "compound 3a", "reason": "Label visible in Scheme 2.", "pdf_locator": {"page": 1, "figure_label": "Scheme 2"}},
            {"molecule_index": 0, "field": "resolved_smiles", "value": "CO", "reason": "Structure visible in Scheme 2.", "pdf_locator": {"page": 1, "figure_label": "Scheme 2"}},
        ],
    })

    assert result["applied_count"] == 2
    ready = chemical_completion_state(project, "scholarly-a")
    assert ready["workflow_can_continue"] is True
    assert require_chemical_completion_ready(project, "scholarly-a") == ready["gate_digest"]
    assert all(row["actor_type"] == "simulated_researcher_agent" for row in ready["history"])
    assert all(row["pdf_locator"]["page"] == 1 for row in ready["history"])


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update({"actor_type": "system"}),
        lambda payload: payload["corrections"][0].update({"reason": ""}),
        lambda payload: payload["corrections"][0].update({"pdf_locator": {"figure_label": "Scheme 2"}}),
        lambda payload: payload["corrections"][0].update({"value": "not smiles !", "field": "resolved_smiles"}),
        lambda payload: payload.update({"version_token": "0" * 64}),
    ],
)
def test_invalid_batch_is_zero_write(tmp_path: Path, mutation) -> None:
    project = completion_project(tmp_path)
    gate = chemical_completion_state(project, "scholarly-a")
    payload = {
        "version_token": gate["version_token"],
        "actor_type": "simulated_researcher_agent", "actor_label": "simulated_researcher",
        "corrections": [{"molecule_index": 0, "field": "mol_idt", "value": "compound 3a", "reason": "Visible in PDF.", "pdf_locator": {"page": 1}}],
    }
    mutation(payload)
    before = snapshot(project)

    with pytest.raises(ChemicalCompletionError):
        apply_chemical_completion_batch(project, "scholarly-a", payload)

    assert snapshot(project) == before
