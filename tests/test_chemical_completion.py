from __future__ import annotations

import json
from pathlib import Path

import pytest

from review_writer.project.chemical_completion import (
    ChemicalCompletionError,
    apply_chemical_completion_batch,
    chemical_completion_state,
    project_chemical_completion_state,
    require_chemical_completion_ready,
)
from review_writer.project.chemical_paper import import_chemical_paper
from review_writer.project.chemical_paper import (
    chemical_paper_projection,
    correct_chemical_paper_field,
    load_chemical_paper_state,
)
from review_writer.project.source_truth import load_source_truth_bundle
from test_chemical_paper_import import (
    ACTOR,
    PDF_SHA,
    expand_source_truth_studies,
    snapshot,
    source_truth_project,
    v2000,
    write_chemical_zip,
)
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
    assert gate["compatibility_aggregation"]["mode"] == "legacy_subset"


def test_batch_is_atomic_and_researcher_attributed(tmp_path: Path) -> None:
    project = completion_project(tmp_path)
    gate = chemical_completion_state(project, "scholarly-a")

    result = apply_chemical_completion_batch(project, "scholarly-a", {
        "version_token": gate["version_token"],
        "actor_type": "simulated_researcher_agent", "actor_label": "simulated_researcher",
        "corrections": [
            {"molecule_index": 0, "field": "mol_idt", "value": "compound 3a", "reason": "Label visible in Scheme 2.", "pdf_locator": {"page": 1, "figure_label": "Scheme 2"}},
            {
                "molecule_index": 0,
                "field": "resolved_smiles",
                "value": "CO",
                "resolution_status": "AI_PROVISIONAL",
                "confidence": 0.8,
                "provenance": {"kind": "ai_candidate", "source": "pdf"},
                "reason": "Structure visible in Scheme 2.",
                "pdf_locator": {"page": 1, "figure_label": "Scheme 2"},
            },
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


def _large_completion_project(tmp_path: Path, *, candidate_count: int = 218) -> Path:
    project = _parse_project(tmp_path)
    (project / "00_discovery").mkdir(parents=True, exist_ok=True)
    (project / "00_discovery/candidate_pool.json").write_text(
        json.dumps(
            {
                "schema_version": "candidate-pool.v1",
                "candidates": [
                    {
                        "candidate_id": "scholarly-a",
                        "study_id": "scholarly-a",
                        "tier": "core",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    source_sha = load_source_truth_bundle(project, "scholarly-a")["sources"][0][
        "pdf"
    ]["sha256"]
    molecules = [
        {
            "mol_id": f"mol-{index + 1}",
            "page_idx": 0,
            "bbox_normalized": [0.01, 0.01, 0.1, 0.1],
            "smiles_expanded": "CO" if index < candidate_count else "",
            "smiles_unexpanded": "",
            "mol_idt": f"compound {index + 1}",
            "mol_block": v2000(),
        }
        for index in range(309)
    ]
    archive = write_chemical_zip(
        tmp_path / "chemical-large.zip", pages=1, molecules=molecules
    )
    import_chemical_paper(project, "scholarly-a", source_sha, archive, ACTOR)
    return project


def test_honest_progressive_uses_309_core_coverage_and_legacy_candidates_without_rewrite(
    tmp_path: Path,
) -> None:
    project = _large_completion_project(tmp_path)
    before = load_chemical_paper_state(project, "scholarly-a")
    before_history = before["field_corrections"]

    initial = chemical_completion_state(project, "scholarly-a")

    assert initial["route"] == "honest_progressive"
    assert initial["confirmed_count"] == 0
    assert initial["ai_provisional_count"] == 218
    assert initial["blocked_count"] == 91
    assert initial["coverage_ratio"] == pytest.approx(218 / 309)
    assert initial["coverage_threshold"] == pytest.approx(0.8)
    assert initial["workflow_can_continue"] is False
    assert initial["actor_provenance_residual"] is False
    assert all(
        row["resolved_smiles_status"] == "AI_PROVISIONAL"
        for row in initial["molecules"][:218]
    )
    assert all(
        row["resolved_smiles_status"] == "BLOCKED"
        and row["resolved_smiles"] is None
        and row["gap_reason"]
        for row in initial["molecules"][218:]
    )

    result = apply_chemical_completion_batch(
        project,
        "scholarly-a",
        {
            "version_token": initial["version_token"],
            "actor_type": "simulated_researcher_agent",
            "actor_label": "offline-ai",
            "corrections": [
                {
                    "molecule_index": index,
                    "field": "resolved_smiles",
                    "value": "CO",
                    "resolution_status": "AI_PROVISIONAL",
                    "confidence": 0.82,
                    "provenance": {
                        "kind": "ai_candidate",
                        "source": "offline-structure-review",
                    },
                    "reason": "Candidate is visible in the original PDF.",
                    "pdf_locator": {"page": 1},
                }
                for index in range(218, 248)
            ],
        },
    )

    assert result["applied_count"] == 30
    ready = chemical_completion_state(project, "scholarly-a")
    assert ready["confirmed_count"] == 0
    assert ready["ai_provisional_count"] == 248
    assert ready["blocked_count"] == 61
    assert ready["coverage_ratio"] == pytest.approx(248 / 309)
    assert ready["workflow_can_continue"] is True
    assert len(ready["gap_registry"]) == 61
    assert all(row["status"] == "BLOCKED" for row in ready["gap_registry"])
    assert all(
        row["status"] == "AI_PROVISIONAL"
        for row in ready["uncertainty_registry"]
    )
    assert len(ready["uncertainty_registry"]) == 248

    after = load_chemical_paper_state(project, "scholarly-a")
    assert after["field_corrections"] == before_history + [
        after["field_corrections"][index]
        for index in range(30)
    ]


def test_resolution_status_requires_metadata_and_human_confirmation(
    tmp_path: Path,
) -> None:
    project = completion_project(tmp_path)
    gate = chemical_completion_state(project, "scholarly-a")
    invalid = {
        "version_token": gate["version_token"],
        "actor_type": "simulated_researcher_agent",
        "actor_label": "offline-ai",
        "corrections": [
            {
                "molecule_index": 0,
                "field": "resolved_smiles",
                "value": "CO",
                "resolution_status": "AI_PROVISIONAL",
                "reason": "Candidate from the PDF.",
                "pdf_locator": {"page": 1},
            }
        ],
    }
    before = snapshot(project)

    with pytest.raises(ChemicalCompletionError, match="RESOLUTION_METADATA_REQUIRED"):
        apply_chemical_completion_batch(project, "scholarly-a", invalid)
    assert snapshot(project) == before

    applied = apply_chemical_completion_batch(
        project,
        "scholarly-a",
        {
            **invalid,
            "corrections": [
                {
                    **invalid["corrections"][0],
                    "confidence": 0.74,
                    "provenance": {"kind": "ai_candidate", "source": "pdf"},
                }
            ],
        },
    )
    assert applied["applied_count"] == 1
    provisional = chemical_paper_projection(project)["studies"][0]["molecules"][0]
    assert provisional["resolved_smiles_status"] == "AI_PROVISIONAL"
    assert provisional["confidence"] == pytest.approx(0.74)
    assert provisional["provenance"]["kind"] == "ai_candidate"
    assert provisional["pdf_locator"]["page"] == 1

    confirmed_project = completion_project(tmp_path / "confirmed")
    confirmed_gate = chemical_completion_state(confirmed_project, "scholarly-a")
    with pytest.raises(ChemicalCompletionError, match="RESEARCHER_CONFIRMATION_REQUIRED"):
        apply_chemical_completion_batch(
            confirmed_project,
            "scholarly-a",
            {
                "version_token": confirmed_gate["version_token"],
                "actor_type": "simulated_researcher_agent",
                "actor_label": "offline-ai",
                "corrections": [
                    {
                        "molecule_index": 0,
                        "field": "resolved_smiles",
                        "value": "CO",
                        "resolution_status": "CONFIRMED",
                        "reason": "Candidate from the PDF.",
                        "pdf_locator": {"page": 1},
                    }
                ],
            },
        )

    confirmed = apply_chemical_completion_batch(
        confirmed_project,
        "scholarly-a",
        {
            "version_token": confirmed_gate["version_token"],
            "actor_type": "human_researcher",
            "actor_label": "researcher",
            "corrections": [
                {
                    "molecule_index": 0,
                    "field": "resolved_smiles",
                    "value": "CO",
                    "resolution_status": "CONFIRMED",
                    "reason": "Researcher confirmed against the original PDF.",
                    "pdf_locator": {"page": 1},
                }
            ],
        },
    )
    assert confirmed["applied_count"] == 1
    confirmed_view = chemical_completion_state(confirmed_project, "scholarly-a")
    assert confirmed_view["confirmed_count"] == 1
    assert confirmed_view["ai_provisional_count"] == 0
    assert confirmed_view["molecules"][0]["resolved_smiles_status"] == "CONFIRMED"


def test_new_batch_resolved_smiles_requires_explicit_resolution_status(
    tmp_path: Path,
) -> None:
    project = completion_project(tmp_path)
    gate = chemical_completion_state(project, "scholarly-a")
    payload = {
        "version_token": gate["version_token"],
        "actor_type": "simulated_researcher_agent",
        "actor_label": "offline-ai",
        "corrections": [
            {
                "molecule_index": 0,
                "field": "resolved_smiles",
                "value": "CO",
                "reason": "Candidate from the PDF.",
                "pdf_locator": {"page": 1},
            }
        ],
    }
    before = snapshot(project)

    with pytest.raises(ChemicalCompletionError, match="RESOLUTION_STATUS_REQUIRED"):
        apply_chemical_completion_batch(project, "scholarly-a", payload)

    assert snapshot(project) == before


def test_project_completion_filters_background_and_keeps_309_denominator(
    tmp_path: Path,
) -> None:
    project = source_truth_project(tmp_path, pages=2)
    study_ids = expand_source_truth_studies(project, 2)
    (project / "00_discovery").mkdir(parents=True, exist_ok=True)
    (project / "00_discovery/candidate_pool.json").write_text(
        json.dumps(
            {
                "schema_version": "candidate-pool.v1",
                "candidates": [
                    {"candidate_id": study_ids[0], "study_id": study_ids[0], "tier": "core"},
                    {"candidate_id": study_ids[1], "study_id": study_ids[1], "tier": "background"},
                ],
            }
        ),
        encoding="utf-8",
    )
    for index, study_id in enumerate(study_ids):
        archive = write_chemical_zip(
            tmp_path / f"chemical-{index}.zip",
            pages=2,
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
        import_chemical_paper(project, study_id, PDF_SHA, archive, ACTOR)

    gate = chemical_completion_state(project, study_ids[0])
    project_gate = project_chemical_completion_state(project)

    assert gate["project_molecule_count"] == 1
    assert gate["ai_provisional_count"] == 1
    assert gate["coverage_denominator"] == 309
    assert gate["coverage_ratio"] == pytest.approx(1 / 309)
    assert gate["compatibility_aggregation"]["mode"] == "project_core_309"
    assert project_gate["project_molecule_count"] == 1
    assert project_gate["ai_provisional_count"] == 1
    assert project_gate["coverage_denominator"] == 309
    assert project_gate["coverage_ratio"] == pytest.approx(1 / 309)
    assert project_gate["compatibility_aggregation"]["mode"] == "project_core_309"
    assert project_gate["workflow_can_continue"] is False
    assert len(project_gate["uncertainty_registry"]) == 1


def test_researcher_safe_provenance_is_allowlisted_in_projection(
    tmp_path: Path,
) -> None:
    project = completion_project(tmp_path)
    gate = chemical_completion_state(project, "scholarly-a")

    apply_chemical_completion_batch(
        project,
        "scholarly-a",
        {
            "version_token": gate["version_token"],
            "actor_type": "simulated_researcher_agent",
            "actor_label": "offline-ai",
            "corrections": [
                {
                    "molecule_index": 0,
                    "field": "resolved_smiles",
                    "value": "CO",
                    "resolution_status": "AI_PROVISIONAL",
                    "confidence": 0.8,
                    "provenance": {
                        "kind": "ai_candidate",
                        "source": "pdf",
                        "path": "/private/fixture.pdf",
                        "sha256": "a" * 64,
                        "token": "opaque-fixture-token",
                    },
                    "reason": "Candidate from the PDF.",
                    "pdf_locator": {"page": 1},
                }
            ],
        },
    )

    projected = chemical_paper_projection(project)["studies"][0]["molecules"][0]
    safe_provenance = projected["provenance"]
    assert safe_provenance == {"kind": "ai_candidate", "source": "pdf"}
    completion = chemical_completion_state(project, "scholarly-a")
    assert completion["uncertainty_registry"][0]["provenance"] == safe_provenance


def test_actor_mismatch_is_a_safe_residual_and_history_is_unchanged(
    tmp_path: Path,
) -> None:
    project = completion_project(tmp_path)
    gate = chemical_completion_state(project, "scholarly-a")
    correct_chemical_paper_field(
        project,
        study_id="scholarly-a",
        molecule_index=0,
        field="resolved_smiles",
        value="CO",
        actor=ACTOR,
        reason="Legacy first-batch correction.",
        pdf_locator={"page": 1},
        version_token=gate["version_token"],
    )
    state = load_chemical_paper_state(project, "scholarly-a")
    history = list(state["field_corrections"])

    view = chemical_completion_state(project, "scholarly-a")

    assert view["actor_provenance_residual"] is True
    assert view["history"][-1]["actor_type"] == "simulated_researcher_agent"
    assert load_chemical_paper_state(project, "scholarly-a")["field_corrections"] == history


def test_human_type_with_simulated_label_is_residual_and_projection_stays_tristate(
    tmp_path: Path,
) -> None:
    project = completion_project(tmp_path)
    gate = chemical_completion_state(project, "scholarly-a")
    correct_chemical_paper_field(
        project,
        study_id="scholarly-a",
        molecule_index=0,
        field="resolved_smiles",
        value="CO",
        actor={
            "actor_type": "human_researcher",
            "actor_label": "simulated_researcher_agent",
        },
        reason="Legacy actor mismatch fixture.",
        pdf_locator={"page": 1},
        version_token=gate["version_token"],
    )

    view = chemical_completion_state(project, "scholarly-a")

    assert view["actor_provenance_residual"] is True
    assert view["molecules"][0]["resolved_smiles_status"] == "BLOCKED"
    assert view["molecules"][0]["resolved_smiles"] is None
    assert view["legacy_unclassified_count"] == 1
    assert view["legacy_unclassified_registry"][0]["legacy_unclassified"] is True
    assert "status" not in view["legacy_unclassified_registry"][0]
    assert all(row["status"] == "BLOCKED" for row in view["gap_registry"])
    assert set(row["resolved_smiles_status"] for row in view["molecules"]) <= {
        "CONFIRMED",
        "AI_PROVISIONAL",
        "BLOCKED",
    }
