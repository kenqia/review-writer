from __future__ import annotations

import json
from pathlib import Path

import pytest

from review_writer.project.chemical_completion import (
    ChemicalCompletionError,
    apply_chemical_completion_batch,
    chemical_completion_state,
    project_chemical_completion_state,
)
from review_writer.delivery.dual_parse_release import preflight_chemical_paper_import
from review_writer.project.chemical_paper import (
    ChemicalPaperError,
    _canonical_state_digest,
    chemical_dependency_state,
    chemical_paper_dependency_currentness,
    chemical_paper_manuscript_bindings,
    chemical_paper_projection,
    correct_chemical_paper_field,
    import_chemical_paper,
    load_chemical_paper_state,
)
from review_writer.project.content_agent_handoff import build_content_task_package
from review_writer.project.parse_quality import write_parse_quality_gate
from review_writer.project.parse_reconciliation import write_parse_reconciliation
from review_writer.project.dual_source import write_dual_source_binding
from review_writer.project.source_truth import canonical_digest, load_source_truth_bundle
from test_chemical_paper_import import (
    ACTOR,
    PDF_SHA,
    snapshot,
    source_truth_project,
    v2000,
    write_chemical_zip,
)
from test_dual_parse_content_package import paper_request
from test_parse_quality import _decide_all, _parse_project
from test_parse_reconciliation import reconciliation_project


def _molecule(
    molecule_id: str,
    *,
    expanded: str = "",
    unexpanded: str = "",
    name: str = "compound",
) -> dict[str, object]:
    return {
        "mol_id": molecule_id,
        "page_idx": 0,
        "bbox_normalized": [0.1, 0.2, 0.3, 0.4],
        "smiles_expanded": expanded,
        "smiles_unexpanded": unexpanded,
        "mol_idt": name,
        "mol_block": v2000(),
    }


def _project_with_molecules(tmp_path: Path, molecules: list[dict[str, object]]) -> Path:
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
    archive = write_chemical_zip(
        tmp_path / "chemical.zip", pages=1, molecules=molecules
    )
    import_chemical_paper(project, "scholarly-a", source_sha, archive, ACTOR)
    return project


def test_projection_resolves_expanded_then_falls_back_and_keeps_candidates(
    tmp_path: Path,
) -> None:
    project = _project_with_molecules(
        tmp_path,
        [
            _molecule("mol-expanded", expanded="CO", unexpanded="C-O"),
            _molecule("mol-fallback", unexpanded="N"),
            _molecule("mol-missing"),
        ],
    )

    state = load_chemical_paper_state(project, "scholarly-a")
    projection = chemical_paper_projection(project)
    study = projection["studies"][0]
    expanded, fallback, missing = study["molecules"]

    assert state["schema_version"] == "chemical-paper-state.v2"
    assert projection["schema_version"] == "chemical-paper-projection.v2"
    assert expanded["resolved_smiles"] == "CO"
    assert expanded["smiles_candidates"] == {
        "expanded": "CO",
        "unexpanded": "C-O",
        "selected_source": "smiles_expanded",
        "candidate_difference": True,
    }
    assert fallback["resolved_smiles"] == "N"
    assert fallback["smiles_candidates"]["selected_source"] == "smiles_unexpanded"
    assert missing["resolved_smiles"] is None
    assert missing["missing_fields"] == ["resolved_smiles"]
    assert "smiles_expanded" not in missing
    assert "smiles_unexpanded" not in missing
    assert study["missing_field_counts"] == {"mol_idt": 0, "resolved_smiles": 1}
    assert any("candidate difference" in item.casefold() for item in study["limitations"])


def test_placeholder_smiles_candidates_survive_preflight_and_import_as_missing_authority(
    tmp_path: Path,
) -> None:
    project = source_truth_project(tmp_path, pages=1)
    archive = write_chemical_zip(
        tmp_path / "chemical-placeholders.zip",
        pages=1,
        molecules=[
            _molecule(
                "mol-placeholder",
                expanded="Rα/Rβ",
                unexpanded="R'2",
            )
        ],
    )

    preflight = preflight_chemical_paper_import(
        project,
        "study-1",
        archive.read_bytes(),
    )
    assert preflight["status"] == "ready_for_confirmation"
    assert preflight["molecule_count"] == 1
    assert not (project / "01_evidence/chemical_paper/study-1/state.json").exists()

    imported = import_chemical_paper(project, "study-1", PDF_SHA, archive, ACTOR)
    assert imported["status"] == "imported"
    state = load_chemical_paper_state(project, "study-1")
    fields = state["molecules"][0]["fields"]
    assert fields["smiles_expanded"] == {
        "status": "candidate",
        "value": "Rα/Rβ",
    }
    assert fields["smiles_unexpanded"] == {
        "status": "candidate",
        "value": "R'2",
    }
    assert fields["resolved_smiles"] == {
        "status": "unresolved",
        "value": None,
    }

    projected = chemical_paper_projection(project)
    study = projected["studies"][0]
    molecule = study["molecules"][0]
    assert molecule["resolved_smiles"] is None
    assert molecule["smiles_candidates"] == {
        "expanded": "Rα/Rβ",
        "unexpanded": "R'2",
        "selected_source": None,
        "candidate_difference": True,
    }
    assert molecule["missing_fields"] == ["resolved_smiles"]
    assert study["missing_field_counts"] == {"mol_idt": 0, "resolved_smiles": 1}
    assert any("provenance candidate" in item.casefold() for item in study["limitations"])

    completion = chemical_completion_state(project, "study-1")
    assert completion["missing_resolved_smiles_count"] == 1
    assert completion["workflow_can_continue"] is False


@pytest.mark.parametrize(
    ("expanded", "unexpanded", "expected", "selected_source"),
    [
        ("CO", "R'2", "CO", "smiles_expanded"),
        ("Rα/Rβ", "N", "N", "smiles_unexpanded"),
    ],
)
def test_initial_resolved_smiles_uses_only_the_first_valid_candidate(
    tmp_path: Path,
    expanded: str,
    unexpanded: str,
    expected: str,
    selected_source: str,
) -> None:
    project = _project_with_molecules(
        tmp_path,
        [_molecule("mol-selection", expanded=expanded, unexpanded=unexpanded)],
    )

    state = load_chemical_paper_state(project, "scholarly-a")
    assert state["molecules"][0]["fields"]["resolved_smiles"]["value"] == expected
    molecule = chemical_paper_projection(project)["studies"][0]["molecules"][0]
    assert molecule["resolved_smiles"] == expected
    assert molecule["smiles_candidates"]["selected_source"] == selected_source


def test_missing_resolved_smiles_keeps_release_and_evidence_fail_closed(
    tmp_path: Path,
) -> None:
    project = source_truth_project(tmp_path, pages=1)
    archive = write_chemical_zip(
        tmp_path / "chemical-placeholders.zip",
        pages=1,
        molecules=[
            _molecule(
                "mol-placeholder",
                expanded="Rα/Rβ",
                unexpanded="R'2",
            )
        ],
    )
    import_chemical_paper(project, "study-1", PDF_SHA, archive, ACTOR)

    binding = chemical_paper_manuscript_bindings(project)
    assert binding["chemical_paper_safe_summary"]["missing_resolved_smiles_count"] == 1
    claims = [
        {
            "claim_id": "claim-placeholder",
            "study_id": "study-1",
            "molecule_index": 0,
            "required_fields": ["resolved_smiles"],
            "requires_element_review": False,
            "requires_reaction_data": False,
        }
    ]
    currentness = chemical_paper_dependency_currentness(
        project,
        import_digests=binding["chemical_paper_import_digests"],
        claim_dependencies=claims,
    )
    assert currentness["can_release"] is False
    assert currentness["claims"][0]["status"] == "needs_review"
    assert currentness["claims"][0]["blocking_reasons"] == [
        "claim-placeholder:resolved_smiles:unresolved"
    ]

    state = load_chemical_paper_state(project, "study-1")
    evidence = chemical_dependency_state(
        project,
        "evidence-placeholder",
        [
            {
                "study_id": "study-1",
                "molecule_id": "mol-placeholder",
                "molecule_digest": state["molecules"][0]["molecule_digest"],
                "chemical_paper_import_digest": state["current_import_digest"],
                "required_fields": ["resolved_smiles"],
            }
        ],
    )
    assert evidence["dependency_status"] == "blocked_unresolved"
    assert evidence["gaps"] == [
        "study-1/mol-placeholder:resolved_smiles:unresolved"
    ]


def test_completion_gate_and_batch_use_one_researcher_owned_smiles_field(
    tmp_path: Path,
) -> None:
    project = _project_with_molecules(
        tmp_path, [_molecule("mol-missing", name="")]
    )
    gate = chemical_completion_state(project, "scholarly-a")

    assert gate["schema_version"] == "chemical-completion-gate.v2"
    assert gate["missing_name_count"] == 1
    assert gate["missing_resolved_smiles_count"] == 1
    assert gate["ai_authored_smiles_count"] == 0
    assert [row["field"] for row in gate["missing_fields"]] == [
        "mol_idt",
        "resolved_smiles",
    ]
    assert "missing_smiles_expanded_count" not in gate
    assert "missing_smiles_unexpanded_count" not in gate

    before = snapshot(project)
    with pytest.raises(ChemicalCompletionError, match="CHEMICAL_COMPLETION_BATCH_INVALID"):
        apply_chemical_completion_batch(
            project,
            "scholarly-a",
            {
                "version_token": gate["version_token"],
                "actor_type": "simulated_researcher_agent",
                "actor_label": "simulated_researcher",
                "corrections": [
                    {
                        "molecule_index": 0,
                        "field": "smiles_expanded",
                        "value": "CO",
                        "reason": "Visible in Scheme 2.",
                        "pdf_locator": {"page": 1, "figure_label": "Scheme 2"},
                    }
                ],
            },
        )
    assert snapshot(project) == before

    applied = apply_chemical_completion_batch(
        project,
        "scholarly-a",
        {
            "version_token": gate["version_token"],
            "actor_type": "simulated_researcher_agent",
            "actor_label": "simulated_researcher",
            "corrections": [
                {
                    "molecule_index": 0,
                    "field": "mol_idt",
                    "value": "compound 3a",
                    "reason": "Label visible in Scheme 2.",
                    "pdf_locator": {"page": 1, "figure_label": "Scheme 2"},
                },
                {
                    "molecule_index": 0,
                    "field": "resolved_smiles",
                    "value": "CO",
                    "reason": "Structure visible in Scheme 2.",
                    "pdf_locator": {"page": 1, "figure_label": "Scheme 2"},
                },
            ],
        },
    )

    assert applied["applied_count"] == 2
    ready = chemical_completion_state(project, "scholarly-a")
    assert ready["workflow_can_continue"] is True
    assert ready["missing_resolved_smiles_count"] == 0
    assert ready["ai_authored_smiles_count"] == 0
    smiles_history = [row for row in ready["history"] if row["field"] == "resolved_smiles"]
    assert len(smiles_history) == 1
    assert smiles_history[0]["value"] == "CO"
    assert smiles_history[0]["reason"] == "Structure visible in Scheme 2."
    assert smiles_history[0]["actor_type"] == "simulated_researcher_agent"
    assert smiles_history[0]["recorded_at"].endswith("Z")


def test_direct_resolved_smiles_correction_requires_locator_and_valid_value(
    tmp_path: Path,
) -> None:
    project = _project_with_molecules(
        tmp_path, [_molecule("mol-a", expanded="CO")]
    )
    version_token = chemical_paper_projection(project)["studies"][0]["version_token"]

    for value, locator, error in (
        ("CN", None, "PDF_LOCATOR_INVALID"),
        ("not a smiles!", {"page": 1, "figure_label": "Scheme 2"}, "SMILES_INVALID"),
        ("C1CC", {"page": 1, "figure_label": "Scheme 2"}, "SMILES_INVALID"),
    ):
        before = snapshot(project)
        with pytest.raises(ChemicalPaperError, match=error):
            correct_chemical_paper_field(
                project,
                study_id="scholarly-a",
                molecule_index=0,
                field="resolved_smiles",
                value=value,
                actor=ACTOR,
                reason="Checked against Scheme 2.",
                pdf_locator=locator,
                version_token=version_token,
            )
        assert snapshot(project) == before

    corrected = correct_chemical_paper_field(
        project,
        study_id="scholarly-a",
        molecule_index=0,
        field="resolved_smiles",
        value="CN",
        actor=ACTOR,
        reason="Checked against Scheme 2.",
        pdf_locator={"page": 1, "figure_label": "Scheme 2"},
        version_token=version_token,
    )

    assert corrected["version_token"] != version_token
    current = load_chemical_paper_state(project, "scholarly-a")
    assert current["field_corrections"][-1]["pdf_locator"] == {
        "page": 1,
        "figure_label": "Scheme 2",
    }
    history = chemical_completion_state(project, "scholarly-a")["history"]
    assert history[-1]["field"] == "resolved_smiles"
    assert history[-1]["pdf_locator"]["page"] == 1


@pytest.mark.parametrize(
    "value",
    ["C(", "C1CC", "C..C", "C1.C1", "C11", "C((C))", "[C+0]"],
)
def test_direct_resolved_smiles_rejects_incomplete_or_empty_structures(
    tmp_path: Path, value: str
) -> None:
    project = _project_with_molecules(
        tmp_path, [_molecule("mol-a", expanded="CO")]
    )
    version_token = chemical_paper_projection(project)["studies"][0]["version_token"]
    before = snapshot(project)

    with pytest.raises(ChemicalPaperError, match="SMILES_INVALID"):
        correct_chemical_paper_field(
            project,
            study_id="scholarly-a",
            molecule_index=0,
            field="resolved_smiles",
            value=value,
            actor=ACTOR,
            reason="Checked against Scheme 2.",
            pdf_locator={"page": 1, "figure_label": "Scheme 2"},
            version_token=version_token,
        )

    assert snapshot(project) == before


@pytest.mark.parametrize("value", ["C(", "C1CC", "C..C"])
def test_batch_resolved_smiles_rejects_incomplete_or_empty_structures(
    tmp_path: Path, value: str
) -> None:
    project = _project_with_molecules(tmp_path, [_molecule("mol-a")])
    gate = chemical_completion_state(project, "scholarly-a")
    before = snapshot(project)

    with pytest.raises(ChemicalCompletionError, match="SMILES_INVALID"):
        apply_chemical_completion_batch(
            project,
            "scholarly-a",
            {
                "version_token": gate["version_token"],
                "actor_type": "simulated_researcher_agent",
                "actor_label": "simulated_researcher",
                "corrections": [
                    {
                        "molecule_index": 0,
                        "field": "resolved_smiles",
                        "value": value,
                        "reason": "Structure visible in Scheme 2.",
                        "pdf_locator": {"page": 1, "figure_label": "Scheme 2"},
                    }
                ],
            },
        )

    assert snapshot(project) == before


@pytest.mark.parametrize(
    "value",
    [
        "C",
        "CCO",
        "c1ccccc1",
        "C1CCCCC1",
        "C/C=C\\C",
        "[NH4+]",
        "C.C",
    ],
)
def test_direct_resolved_smiles_accepts_common_complete_structures(
    tmp_path: Path, value: str
) -> None:
    project = _project_with_molecules(
        tmp_path, [_molecule("mol-a", expanded="CO")]
    )
    version_token = chemical_paper_projection(project)["studies"][0]["version_token"]

    correct_chemical_paper_field(
        project,
        study_id="scholarly-a",
        molecule_index=0,
        field="resolved_smiles",
        value=value,
        actor=ACTOR,
        reason="Checked against Scheme 2.",
        pdf_locator={"page": 1, "figure_label": "Scheme 2"},
        version_token=version_token,
    )

    assert load_chemical_paper_state(project, "scholarly-a")["field_corrections"][-1][
        "value"
    ] == value


@pytest.mark.parametrize("tamper", ["value", "locator"])
def test_load_revalidates_correction_value_and_bound_import_page(
    tmp_path: Path, tamper: str
) -> None:
    project = _project_with_molecules(
        tmp_path, [_molecule("mol-a", expanded="CO")]
    )
    version_token = chemical_paper_projection(project)["studies"][0]["version_token"]
    correct_chemical_paper_field(
        project,
        study_id="scholarly-a",
        molecule_index=0,
        field="resolved_smiles",
        value="CN",
        actor=ACTOR,
        reason="Checked against Scheme 2.",
        pdf_locator={"page": 1, "figure_label": "Scheme 2"},
        version_token=version_token,
    )

    path = project / "01_evidence/chemical_paper/scholarly-a/state.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    correction = state["field_corrections"][-1]
    if tamper == "value":
        correction["value"] = "C("
    else:
        correction["pdf_locator"]["page"] = 2
    correction["event_digest"] = canonical_digest(
        {key: value for key, value in correction.items() if key != "event_digest"}
    )
    state["field_correction_head_digest"] = correction["event_digest"]
    state["state_digest"] = canonical_digest(
        {key: value for key, value in state.items() if key != "state_digest"}
    )
    path.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ChemicalPaperError, match="CHEMICAL_PAPER_STATE_INVALID"):
        load_chemical_paper_state(project, "scholarly-a")


@pytest.mark.parametrize("tamper", ["bound_digest", "orphan_molecule"])
def test_load_rebinds_correction_event_to_current_molecule(
    tmp_path: Path, tamper: str
) -> None:
    project = _project_with_molecules(
        tmp_path, [_molecule("mol-a", expanded="CO")]
    )
    correct_chemical_paper_field(
        project,
        study_id="scholarly-a",
        molecule_index=0,
        field="resolved_smiles",
        value="CN",
        actor=ACTOR,
        reason="Checked against Scheme 2.",
        pdf_locator={"page": 1, "figure_label": "Scheme 2"},
        version_token=chemical_paper_projection(project)["studies"][0][
            "version_token"
        ],
    )

    state_path = project / "01_evidence/chemical_paper/scholarly-a/state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    correction = state["field_corrections"][0]
    if tamper == "bound_digest":
        correction["bound_molecule_digest"] = "f" * 64
    else:
        correction["molecule_id"] = "orphan-molecule"
    correction["event_digest"] = canonical_digest(
        {key: value for key, value in correction.items() if key != "event_digest"}
    )
    state["field_correction_head_digest"] = correction["event_digest"]
    _reseal_state(state_path, state)

    with pytest.raises(ChemicalPaperError, match="CHEMICAL_PAPER_STATE_INVALID"):
        load_chemical_paper_state(project, "scholarly-a")


def test_load_rejects_forged_correction_prior_value_history(tmp_path: Path) -> None:
    project = _project_with_molecules(
        tmp_path, [_molecule("mol-a", expanded="CO")]
    )
    first = correct_chemical_paper_field(
        project,
        study_id="scholarly-a",
        molecule_index=0,
        field="resolved_smiles",
        value="CN",
        actor=ACTOR,
        reason="First PDF check.",
        pdf_locator={"page": 1},
        version_token=chemical_paper_projection(project)["studies"][0][
            "version_token"
        ],
    )
    correct_chemical_paper_field(
        project,
        study_id="scholarly-a",
        molecule_index=0,
        field="resolved_smiles",
        value="CCN",
        actor=ACTOR,
        reason="Second PDF check.",
        pdf_locator={"page": 1},
        version_token=first["version_token"],
    )

    state_path = project / "01_evidence/chemical_paper/scholarly-a/state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    correction = state["field_corrections"][1]
    correction["prior_value"] = "CO"
    correction["event_digest"] = canonical_digest(
        {key: value for key, value in correction.items() if key != "event_digest"}
    )
    state["field_correction_head_digest"] = correction["event_digest"]
    _reseal_state(state_path, state)

    with pytest.raises(ChemicalPaperError, match="CHEMICAL_PAPER_STATE_INVALID"):
        load_chemical_paper_state(project, "scholarly-a")


def test_load_rejects_locator_page_that_does_not_locate_current_molecule(
    tmp_path: Path,
) -> None:
    project = source_truth_project(tmp_path, pages=2)
    source_sha = load_source_truth_bundle(project, "study-1")["sources"][0][
        "pdf"
    ]["sha256"]
    import_chemical_paper(
        project,
        "study-1",
        source_sha,
        write_chemical_zip(
            tmp_path / "chemical-pages-2.zip",
            pages=2,
            molecules=[_molecule("mol-a", expanded="CO")],
        ),
        ACTOR,
    )
    correct_chemical_paper_field(
        project,
        study_id="study-1",
        molecule_index=0,
        field="resolved_smiles",
        value="CN",
        actor=ACTOR,
        reason="Checked against page 1.",
        pdf_locator={"page": 1},
        version_token=chemical_paper_projection(project)["studies"][0][
            "version_token"
        ],
    )

    state_path = project / "01_evidence/chemical_paper/study-1/state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    correction = state["field_corrections"][0]
    correction["pdf_locator"]["page"] = 2
    correction["event_digest"] = canonical_digest(
        {key: value for key, value in correction.items() if key != "event_digest"}
    )
    state["field_correction_head_digest"] = correction["event_digest"]
    _reseal_state(state_path, state)

    with pytest.raises(ChemicalPaperError, match="CHEMICAL_PAPER_STATE_INVALID"):
        load_chemical_paper_state(project, "study-1")


def test_import_history_uses_prior_chain_not_sorted_mapping_order(tmp_path: Path) -> None:
    project = _project_with_molecules(
        tmp_path, [_molecule("mol-a", expanded="CO")]
    )
    source_sha = load_source_truth_bundle(project, "scholarly-a")["sources"][0][
        "pdf"
    ]["sha256"]
    import_chemical_paper(
        project,
        "scholarly-a",
        source_sha,
        write_chemical_zip(
            tmp_path / "chemical-second.zip",
            pages=1,
            molecules=[_molecule("mol-b", expanded="CC")],
        ),
        ACTOR,
    )

    path = project / "01_evidence/chemical_paper/scholarly-a/state.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    state["imports"] = dict(reversed(list(state["imports"].items())))
    path.write_text(json.dumps(state, sort_keys=False) + "\n", encoding="utf-8")

    loaded = load_chemical_paper_state(project, "scholarly-a")
    assert loaded["molecules"][0]["molecule_id"] == "mol-b"


def test_manuscript_binding_uses_resolved_completion_counters_only(
    tmp_path: Path,
) -> None:
    project = _project_with_molecules(
        tmp_path, [_molecule("mol-a", expanded="", name="")]
    )

    summary = chemical_paper_manuscript_bindings(project)["chemical_paper_safe_summary"]

    assert set(summary) == {
        "schema_version",
        "route",
        "study_count",
        "molecule_count",
        "missing_name_count",
        "missing_resolved_smiles_count",
        "ai_authored_smiles_count",
        "element_review_counts",
        "reaction_data_status",
    }
    assert summary["missing_name_count"] == 1
    assert summary["missing_resolved_smiles_count"] == 1
    assert summary["ai_authored_smiles_count"] == 0
    assert "unresolved_field_count" not in summary


def test_import_preserves_invalid_provenance_smiles_as_unresolved(tmp_path: Path) -> None:
    project = _project_with_molecules(
        tmp_path,
        [_molecule("mol-invalid", expanded="C1CC", unexpanded="R'2")],
    )

    state = load_chemical_paper_state(project, "scholarly-a")
    fields = state["molecules"][0]["fields"]
    assert fields["smiles_expanded"]["value"] == "C1CC"
    assert fields["smiles_unexpanded"]["value"] == "R'2"
    assert fields["resolved_smiles"]["value"] is None


def _reseal_state(path: Path, state: dict[str, object]) -> None:
    state["state_digest"] = _canonical_state_digest(state)
    path.write_text(json.dumps(state), encoding="utf-8")


def test_load_revalidates_serialized_correction_value_and_locator_page(
    tmp_path: Path,
) -> None:
    project = _project_with_molecules(
        tmp_path, [_molecule("mol-a", expanded="CO")]
    )
    state_path = project / "01_evidence/chemical_paper/scholarly-a/state.json"
    imported = load_chemical_paper_state(project, "scholarly-a")
    corrected = correct_chemical_paper_field(
        project,
        study_id="scholarly-a",
        molecule_index=0,
        field="resolved_smiles",
        value="CN",
        actor=ACTOR,
        reason="Checked against Scheme 2.",
        pdf_locator={"page": 1, "figure_label": "Scheme 2"},
        version_token=chemical_paper_projection(project)["studies"][0]["version_token"],
    )
    assert corrected["status"] == "corrected"

    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["field_corrections"][0]["value"] = "C1CC"
    state["field_corrections"][0]["event_digest"] = canonical_digest(
        {
            key: value
            for key, value in state["field_corrections"][0].items()
            if key != "event_digest"
        }
    )
    state["field_correction_head_digest"] = state["field_corrections"][0]["event_digest"]
    _reseal_state(state_path, state)
    with pytest.raises(ChemicalPaperError, match="CHEMICAL_PAPER_STATE_INVALID"):
        load_chemical_paper_state(project, "scholarly-a")

    state = imported
    state_path.write_text(json.dumps(state), encoding="utf-8")
    state = load_chemical_paper_state(project, "scholarly-a")
    state_path.write_text(json.dumps(state), encoding="utf-8")
    # Add a valid correction, then forge only its locator page while preserving digests.
    corrected = correct_chemical_paper_field(
        project,
        study_id="scholarly-a",
        molecule_index=0,
        field="resolved_smiles",
        value="CN",
        actor=ACTOR,
        reason="Checked against Scheme 2.",
        pdf_locator={"page": 1, "figure_label": "Scheme 2"},
        version_token=chemical_paper_projection(project)["studies"][0]["version_token"],
    )
    assert corrected["status"] == "corrected"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["field_corrections"][0]["pdf_locator"]["page"] = 2
    state["field_corrections"][0]["event_digest"] = canonical_digest(
        {
            key: value
            for key, value in state["field_corrections"][0].items()
            if key != "event_digest"
        }
    )
    state["field_correction_head_digest"] = state["field_corrections"][0]["event_digest"]
    _reseal_state(state_path, state)
    with pytest.raises(ChemicalPaperError, match="CHEMICAL_PAPER_STATE_INVALID"):
        load_chemical_paper_state(project, "scholarly-a")


def test_history_chain_order_not_dict_or_list_order(tmp_path: Path) -> None:
    project = _project_with_molecules(
        tmp_path, [_molecule("mol-a", expanded="CO")]
    )
    state_path = project / "01_evidence/chemical_paper/scholarly-a/state.json"
    first = chemical_paper_projection(project)["studies"][0]["version_token"]
    second = correct_chemical_paper_field(
        project,
        study_id="scholarly-a",
        molecule_index=0,
        field="resolved_smiles",
        value="CN",
        actor=ACTOR,
        reason="First correction.",
        pdf_locator={"page": 1},
        version_token=first,
    )
    correct_chemical_paper_field(
        project,
        study_id="scholarly-a",
        molecule_index=0,
        field="resolved_smiles",
        value="CCN",
        actor=ACTOR,
        reason="Second correction.",
        pdf_locator={"page": 1},
        version_token=second["version_token"],
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["field_corrections"].reverse()
    state["imports"] = dict(reversed(list(state["imports"].items())))
    _reseal_state(state_path, state)
    loaded = load_chemical_paper_state(project, "scholarly-a")
    assert [row["value"] for row in loaded["field_corrections"]] == ["CN", "CCN"]
    assert chemical_paper_projection(project)["studies"][0]["molecules"][0][
        "resolved_smiles"
    ] == "CCN"


def test_currentness_and_impact_bind_only_resolved_smiles(tmp_path: Path) -> None:
    project = _project_with_molecules(
        tmp_path, [_molecule("mol-a", expanded="CO", unexpanded="CN")]
    )
    state = load_chemical_paper_state(project, "scholarly-a")
    molecule = state["molecules"][0]
    dependencies = [
        {
            "study_id": "scholarly-a",
            "molecule_id": "mol-a",
            "molecule_digest": molecule["molecule_digest"],
            "chemical_paper_import_digest": state["current_import_digest"],
            "required_fields": ["resolved_smiles"],
        }
    ]

    impact = chemical_dependency_state(project, "evidence-a", dependencies)
    assert impact["dependency_status"] == "ready"
    assert impact["dependencies"][0]["required_fields"] == ["resolved_smiles"]

    bindings = chemical_paper_manuscript_bindings(project)
    currentness = chemical_paper_dependency_currentness(
        project,
        import_digests=bindings["chemical_paper_import_digests"],
        claim_dependencies=[
            {
                "claim_id": "claim-a",
                "study_id": "scholarly-a",
                "molecule_index": 0,
                "required_fields": ["resolved_smiles"],
                "requires_element_review": False,
                "requires_reaction_data": False,
            }
        ],
    )
    assert currentness["schema_version"] == "chemical-paper-dependency-currentness.v2"
    assert currentness["claims"][0]["dependencies"][0][
        "required_field_statuses"
    ] == {"resolved_smiles": "resolved"}

    dependencies[0]["required_fields"] = ["smiles_expanded"]
    with pytest.raises(ChemicalPaperError, match="CHEMICAL_DEPENDENCY_INVALID"):
        chemical_dependency_state(project, "evidence-a", dependencies)


def test_content_package_and_reconciliation_publish_only_resolved_smiles(
    tmp_path: Path,
) -> None:
    project = reconciliation_project(tmp_path, conflict=False)
    registry = write_parse_reconciliation(project, "scholarly-a")

    assert registry["schema_version"] == "parse-reconciliation.v2"
    assert registry["objects"][0]["chemical_candidate"] == {
        "mol_idt": "compound 1",
        "resolved_smiles": "CO",
    }
    assert set(registry["objects"][0]["generic_candidate"]) == {
        "mol_idt",
        "resolved_smiles",
    }

    package = build_content_task_package(project, paper_request(project))
    chemical = next(
        item["content"]
        for item in package["inputs"]["chemical_paper"]
        if item["kind"] == "chemical_paper_safe_projection"
    )
    molecule = chemical["molecules"][0]
    assert molecule["resolved_smiles"] == "CO"
    assert "smiles_candidates" in molecule
    assert "smiles_expanded" not in molecule
    assert "smiles_unexpanded" not in molecule
    assert "resolved_smiles" in json.dumps(package, sort_keys=True)


def test_old_authoritative_state_cannot_bypass_v2_contract(tmp_path: Path) -> None:
    project = _project_with_molecules(tmp_path, [_molecule("mol-a", expanded="CO")])
    path = project / "01_evidence/chemical_paper/scholarly-a/state.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    state["schema_version"] = "chemical-paper-state.v1"
    path.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(ChemicalPaperError, match="CHEMICAL_PAPER_STATE_INVALID"):
        load_chemical_paper_state(project, "scholarly-a")


def test_project_completion_producer_always_emits_release_counters(
    tmp_path: Path,
) -> None:
    project = _project_with_molecules(tmp_path, [_molecule("mol-a", name="")])
    current = project_chemical_completion_state(project)

    assert current["schema_version"] == "chemical-completion-project-state.v2"
    assert current["studies"][0]["missing_name_count"] == 1
    assert current["studies"][0]["missing_resolved_smiles_count"] == 1
    assert current["studies"][0]["ai_authored_smiles_count"] == 0

    path = project / "01_evidence/chemical_paper/scholarly-a/state.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    state["schema_version"] = "chemical-paper-state.v1"
    path.write_text(json.dumps(state), encoding="utf-8")
    invalid = project_chemical_completion_state(project)
    invalid_row = invalid["studies"][0]
    assert invalid_row["reason_code"] == "CHEMICAL_PAPER_STATE_INVALID"
    assert invalid_row["missing_name_count"] == 0
    assert invalid_row["missing_resolved_smiles_count"] == 0
    assert invalid_row["ai_authored_smiles_count"] == 0


def test_rerun6_realistic_completion_distribution_is_88_names_plus_3_smiles(
    tmp_path: Path,
) -> None:
    molecules = [
        _molecule(
            f"mol-{index + 1}",
            expanded="" if index < 3 else "C",
            unexpanded="",
            name="",
        )
        for index in range(88)
    ]
    project = _project_with_molecules(tmp_path, molecules)

    gate = chemical_completion_state(project, "scholarly-a")

    assert gate["molecule_count"] == 88
    assert gate["missing_name_count"] == 88
    assert gate["missing_resolved_smiles_count"] == 3
    assert len(gate["missing_fields"]) == 91
    assert sum(row["field"] == "mol_idt" for row in gate["missing_fields"]) == 88
    assert sum(
        row["field"] == "resolved_smiles" for row in gate["missing_fields"]
    ) == 3
