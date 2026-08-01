from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from review_writer.project.chemical_completion import (
    ChemicalCompletionError,
    _validate_gate,
    apply_chemical_completion_batch,
    chemical_completion_state,
    project_chemical_completion_state,
)
from review_writer.project.chemical_paper import import_chemical_paper
from review_writer.project.source_truth import canonical_digest, load_source_truth_bundle
from test_chemical_paper_import import (
    ACTOR,
    expand_source_truth_studies,
    source_truth_project,
    v2000,
    write_chemical_zip,
)


def _mark_receipt(project: Path, *, corpus_kind: str, variable_n: bool) -> None:
    receipt_path = project / "00_sources/acquisition_final_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt.update(
        {
            "corpus_kind": corpus_kind,
            "variable_n": variable_n,
            "study_count": len(receipt["studies"]),
        }
    )
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")


def _scaled_core_project(
    tmp_path: Path,
    *,
    core_count: int = 2,
    missing_fields: bool = False,
) -> Path:
    project = source_truth_project(tmp_path, pages=1)
    study_ids = expand_source_truth_studies(project, 20)
    (project / "00_discovery").mkdir(parents=True, exist_ok=True)
    (project / "00_discovery/candidate_pool.json").write_text(
        json.dumps(
            {
                "schema_version": "candidate-pool.v1",
                "candidates": [
                    {
                        "candidate_id": study_id,
                        "study_id": study_id,
                        "tier": "core" if index < core_count else "background",
                    }
                    for index, study_id in enumerate(study_ids)
                ],
            }
        ),
        encoding="utf-8",
    )
    for index, study_id in enumerate(study_ids[:core_count]):
        source_sha = load_source_truth_bundle(project, study_id)["sources"][0]["pdf"]["sha256"]
        archive = write_chemical_zip(
            tmp_path / f"chemical-{index}.zip",
            pages=1,
            molecules=[
                {
                    "mol_id": f"mol-{index}",
                    "page_idx": 0,
                    "bbox_normalized": [0.1, 0.2, 0.3, 0.4],
                    "smiles_expanded": "" if missing_fields else "CO",
                    "smiles_unexpanded": "",
                    "mol_idt": "" if missing_fields else f"compound-{index}",
                    "mol_block": v2000(),
                }
            ],
        )
        import_chemical_paper(project, study_id, source_sha, archive, ACTOR)
    _mark_receipt(
        project,
        corpus_kind="authoritative_variable_n",
        variable_n=True,
    )
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

    schema = json.loads(
        (
            Path(__file__).parents[1]
            / "schemas/evidence/chemical_completion_gate.v2.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert list(Draft202012Validator(schema).iter_errors(study_view)) == []


def test_single_core_background_current_variable_n_uses_only_core_denominator(
    tmp_path: Path,
) -> None:
    project = _scaled_core_project(tmp_path, core_count=1)

    gate = chemical_completion_state(project, "study-1")

    assert gate["project_molecule_count"] == 1
    assert gate["core_molecule_count"] == 1
    assert gate["coverage_denominator"] == 1
    assert gate["compatibility_aggregation"]["mode"] == "project_core_current"
    assert gate["coverage_ratio"] == 1.0


def test_current_variable_n_marker_missing_fails_closed(tmp_path: Path) -> None:
    project = _scaled_core_project(tmp_path)
    receipt_path = project / "00_sources/acquisition_final_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    for key in ("corpus_kind", "variable_n", "study_count"):
        receipt.pop(key)
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(
        ChemicalCompletionError,
        match="CHEMICAL_COMPLETION_PROJECT_MARKER_REQUIRED",
    ):
        chemical_completion_state(project, "study-1")


def test_current_variable_n_declared_count_out_of_range_fails_closed(
    tmp_path: Path,
) -> None:
    project = _scaled_core_project(tmp_path)
    receipt_path = project / "00_sources/acquisition_final_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["studies"] = receipt["studies"][:-1]
    receipt["study_count"] = 19
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(
        ChemicalCompletionError,
        match="CHEMICAL_COMPLETION_PROJECT_MARKER_INVALID",
    ):
        chemical_completion_state(project, "study-1")


@pytest.mark.parametrize(
    ("marker_mutation", "error_code"),
    [
        (
            lambda receipt: [
                receipt.pop(key)
                for key in ("corpus_kind", "variable_n", "study_count")
            ],
            "CHEMICAL_COMPLETION_PROJECT_MARKER_REQUIRED",
        ),
        (
            lambda receipt: receipt.update({"study_count": 19}),
            "CHEMICAL_COMPLETION_PROJECT_MARKER_INVALID",
        ),
    ],
)
def test_batch_marker_rejection_is_zero_write(
    tmp_path: Path,
    marker_mutation,
    error_code: str,
) -> None:
    project = _scaled_core_project(tmp_path, core_count=1, missing_fields=True)
    gate = chemical_completion_state(project, "study-1")
    state_path = project / "01_evidence/chemical_paper/study-1/state.json"
    before = state_path.read_bytes()
    before_hash = hashlib.sha256(before).hexdigest()

    receipt_path = project / "00_sources/acquisition_final_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    marker_mutation(receipt)
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(ChemicalCompletionError, match=error_code):
        apply_chemical_completion_batch(
            project,
            "study-1",
            {
                "version_token": gate["version_token"],
                "actor_type": "human_researcher",
                "actor_label": "researcher",
                "corrections": [
                    {
                        "molecule_index": 0,
                        "field": "mol_idt",
                        "value": "compound-0",
                        "reason": "Label visible in Scheme 2.",
                        "pdf_locator": {"page": 1},
                    }
                ],
            },
        )

    after = state_path.read_bytes()
    assert hashlib.sha256(after).hexdigest() == before_hash
    assert after == before


def test_current_gate_schema_mismatch_fails_closed(tmp_path: Path) -> None:
    project = _scaled_core_project(tmp_path, core_count=1)
    gate = chemical_completion_state(project, "study-1")
    invalid = dict(gate)
    invalid["core_molecule_count"] = 0
    body = {key: value for key, value in invalid.items() if key != "gate_digest"}
    invalid["gate_digest"] = canonical_digest(body)

    with pytest.raises(ChemicalCompletionError, match="CHEMICAL_COMPLETION_STATE_INVALID"):
        _validate_gate(invalid)
