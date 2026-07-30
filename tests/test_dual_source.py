from __future__ import annotations

import json
from pathlib import Path

import pytest

from review_writer.project.chemical_paper import import_chemical_paper
from review_writer.project.dual_source import (
    DualSourceError,
    require_dual_source_ready,
    write_dual_source_binding,
)
from review_writer.project.parse_quality import write_parse_quality_gate
from review_writer.project.source_truth import load_source_truth_bundle
from test_chemical_paper_import import ACTOR, write_chemical_zip
from test_parse_quality import _decide_all, _parse_project


def dual_project(tmp_path: Path, *, tier: str = "core", chemical: bool = True) -> Path:
    project = _parse_project(tmp_path)
    (project / "00_discovery").mkdir(parents=True, exist_ok=True)
    (project / "00_discovery/candidate_pool.json").write_text(json.dumps({
        "schema_version": "candidate-pool.v1",
        "candidates": [{
            "candidate_id": "scholarly-a", "study_id": "scholarly-a",
            "source_id": "stud-a", "tier": tier,
            "doi": "10.1000/example", "title": "Example", "document_role": "MAIN",
        }],
    }), encoding="utf-8")
    write_parse_quality_gate(project, "scholarly-a")
    _decide_all(project)
    if chemical:
        bundle = load_source_truth_bundle(project, "scholarly-a")
        source_sha = bundle["sources"][0]["pdf"]["sha256"]
        archive = write_chemical_zip(tmp_path / "chemical.zip", pages=1, molecules=[{
            "mol_id": "mol-a", "page_idx": 0,
            "bbox_normalized": [0.1, 0.2, 0.3, 0.4],
            "smiles_expanded": "CO", "smiles_unexpanded": "CO",
            "mol_idt": "compound 1", "mol_block": "fixture\n  review-writer\n\n  1  0  0  0  0  0            999 V2000\n    0.0000    0.0000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0\nM  END\n",
        }])
        import_chemical_paper(project, "scholarly-a", source_sha, archive, ACTOR)
    return project


def test_core_requires_current_generic_and_chemical_lanes(tmp_path: Path) -> None:
    project = dual_project(tmp_path)

    binding = write_dual_source_binding(project, "scholarly-a")

    assert binding["source_tier"] == "core"
    assert binding["status"] == "current"
    assert binding["generic"]["source_pdf_sha256"] == binding["chemical"]["source_pdf_sha256"]
    assert binding["reaction_data_status"] == "unavailable_not_provided"
    assert "reaction_count" not in binding
    assert require_dual_source_ready(project, "scholarly-a", requires_chemical=False) == binding["binding_digest"]


def test_background_allows_generic_only_until_claim_requires_chemical(tmp_path: Path) -> None:
    project = dual_project(tmp_path, tier="background", chemical=False)

    binding = write_dual_source_binding(project, "scholarly-a")

    assert binding["status"] == "current_generic_only"
    assert require_dual_source_ready(project, "scholarly-a", requires_chemical=False) == binding["binding_digest"]
    with pytest.raises(DualSourceError, match="CHEMICAL_ENHANCEMENT_REQUIRED"):
        require_dual_source_ready(project, "scholarly-a", requires_chemical=True)


def test_core_missing_chemical_lane_fails_closed_without_binding(tmp_path: Path) -> None:
    project = dual_project(tmp_path, chemical=False)

    with pytest.raises(DualSourceError, match="CORE_CHEMICAL_IMPORT_REQUIRED"):
        write_dual_source_binding(project, "scholarly-a")

    assert not (project / "01_evidence/dual_source/scholarly-a/binding.json").exists()
