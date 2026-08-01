from __future__ import annotations

import copy
import base64
import json
from pathlib import Path

import pytest


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64


def _authority_rows() -> list[dict[str, object]]:
    return [
        {
            "study_id": "study-a",
            "source_tier": "core",
            "generic_status": "current",
            "chemical_status": "current",
            "dual_source_binding_digest": SHA_A,
            "generic_version": SHA_A,
            "chemical_version": SHA_B,
            "chemical_completion_digest": SHA_C,
            "chemical_completion_status": "current",
            "reconciliation_digest": SHA_D,
            "reconciliation_status": "current",
            "content_result_status": "current",
            "missing_name_count": 0,
            "missing_resolved_smiles_count": 0,
            "ai_authored_smiles_count": 0,
            "reaction_data_status": "unavailable_not_provided",
        }
    ]


def _project(tmp_path: Path, bindings: list[dict[str, object]]) -> Path:
    project = tmp_path / "project"
    lineage_dir = project / "04_manuscript"
    lineage_dir.mkdir(parents=True)
    (lineage_dir / "manuscript.md").write_text("# Current manuscript\n", encoding="utf-8")
    (lineage_dir / "manuscript_lineage.v2.json").write_text(
        json.dumps(
            {
                "schema_version": "manuscript-lineage.v2",
                "route": "evidence-to-release.v1",
                "dual_parse_bindings": bindings,
            }
        ),
        encoding="utf-8",
    )
    figures = project / "03_figures"
    figures.mkdir()
    (figures / "synthesis_figure_placeholders.json").write_text(
        json.dumps({"placeholders": [{"status": "awaiting_human_figure"}]}),
        encoding="utf-8",
    )
    return project


def _v2_authority_projections(
    completion_row: dict[str, object] | None = None,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    return (
        {
            "studies": [
                {
                    "study_id": "study-a",
                    "source_tier": "core",
                    "requires_chemical": True,
                    "binding_digest": SHA_A,
                    "generic": {"status": "current", "binding_digest": SHA_B},
                    "chemical": {
                        "status": "current",
                        "state_digest": SHA_C,
                        "reaction_data_status": "unavailable_not_provided",
                    },
                }
            ]
        },
        {
            "schema_version": "chemical-completion-project-state.v2",
            "studies": [
                completion_row
                or {
                    "study_id": "study-a",
                    "status": "current",
                    "molecule_count": 1,
                    "missing_name_count": 0,
                    "missing_resolved_smiles_count": 0,
                    "ai_authored_smiles_count": 0,
                    "gate_digest": SHA_D,
                }
            ],
        },
        {
            "schema_version": "parse-reconciliation-project-state.v2",
            "studies": [
                {
                    "study_id": "study-a",
                    "status": "current",
                    "registry_digest": SHA_A,
                }
            ],
        },
    )


def test_internal_release_requires_current_dual_bindings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from review_writer.delivery import dual_parse_release as release

    rows = _authority_rows()
    bindings = release.build_dual_parse_manuscript_bindings(rows, {"study-a"})
    project = _project(tmp_path, bindings)
    monkeypatch.setattr(release, "_current_authority_rows", lambda _: copy.deepcopy(rows))

    current = release.dual_parse_release_state(project)
    assert current["internal_release_ready"] is True
    assert current["expert_release_ready"] is False
    assert current["hard_fails"] == []

    rows[0]["generic_version"] = "e" * 64
    stale = release.dual_parse_release_state(project)
    assert stale["internal_release_ready"] is False
    assert "DUAL_PARSE_STALE" in stale["hard_fails"]
    assert "CORE_GENERIC_PARSE_MISSING_OR_STALE" in stale["hard_fails"]


def test_nonexact_release_binding_can_disclose_incomplete_chemical_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from review_writer.delivery import dual_parse_release as release

    rows = _authority_rows()
    bindings = release.build_dual_parse_manuscript_bindings(rows, {"study-a"})
    project = _project(tmp_path, bindings)
    rows[0]["missing_resolved_smiles_count"] = 1
    rows[0]["chemical_completion_status"] = "blocked"
    monkeypatch.setattr(release, "_current_authority_rows", lambda _: copy.deepcopy(rows))

    strict = release.validate_dual_parse_release_bindings(
        project, {"dual_parse_bindings": bindings}
    )
    nonexact = release.validate_dual_parse_release_bindings(
        project,
        {"dual_parse_bindings": bindings},
        allow_non_exact=True,
    )

    assert strict["workflow_can_continue"] is False
    assert nonexact["workflow_can_continue"] is True
    assert "CHEMICAL_COMPLETION_INCOMPLETE" not in nonexact["hard_fails"]


def test_reaction_absence_is_unknown_not_zero_or_global_hard_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from review_writer.delivery import dual_parse_release as release

    rows = _authority_rows()
    project = _project(
        tmp_path, release.build_dual_parse_manuscript_bindings(rows, {"study-a"})
    )
    monkeypatch.setattr(release, "_current_authority_rows", lambda _: copy.deepcopy(rows))

    state = release.dual_parse_release_state(project)

    assert state["reaction_data_status"] == "unavailable_not_provided"
    assert state["reaction_count"] is None
    assert "REACTION_ABSENCE_MISREPRESENTED" not in state["hard_fails"]


def test_ai_authored_smiles_is_a_hard_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from review_writer.delivery import dual_parse_release as release

    rows = _authority_rows()
    bindings = release.build_dual_parse_manuscript_bindings(rows, {"study-a"})
    project = _project(tmp_path, bindings)
    rows[0]["ai_authored_smiles_count"] = 1
    monkeypatch.setattr(release, "_current_authority_rows", lambda _: copy.deepcopy(rows))

    state = release.dual_parse_release_state(project)

    assert state["internal_release_ready"] is False
    assert "AI_AUTHORED_SMILES" in state["hard_fails"]


@pytest.mark.parametrize(
    ("counter", "value"),
    [
        ("missing_resolved_smiles_count", 1),
        ("missing_resolved_smiles_count", None),
        ("ai_authored_smiles_count", None),
    ],
)
def test_resolved_smiles_completion_counters_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    counter: str,
    value: object,
) -> None:
    from review_writer.delivery import dual_parse_release as release

    rows = _authority_rows()
    bindings = release.build_dual_parse_manuscript_bindings(rows, {"study-a"})
    project = _project(tmp_path, bindings)
    if value is None:
        rows[0].pop(counter)
    else:
        rows[0][counter] = value
    monkeypatch.setattr(release, "_current_authority_rows", lambda _: copy.deepcopy(rows))

    state = release.dual_parse_release_state(project)

    assert state["internal_release_ready"] is False
    assert "CHEMICAL_COMPLETION_INCOMPLETE" in state["hard_fails"]


def test_legacy_dual_smiles_counters_do_not_satisfy_resolved_smiles_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from review_writer.delivery import dual_parse_release as release

    rows = _authority_rows()
    rows[0].pop("missing_resolved_smiles_count")
    rows[0]["missing_smiles_expanded_count"] = 0
    rows[0]["missing_smiles_unexpanded_count"] = 0
    project = _project(
        tmp_path, release.build_dual_parse_manuscript_bindings(rows, {"study-a"})
    )
    monkeypatch.setattr(release, "_current_authority_rows", lambda _: copy.deepcopy(rows))

    state = release.dual_parse_release_state(project)

    assert state["internal_release_ready"] is False
    assert "CHEMICAL_COMPLETION_INCOMPLETE" in state["hard_fails"]


@pytest.mark.parametrize(
    ("counter", "value"),
    [
        ("missing_name_count", None),
        ("missing_name_count", -1),
        ("missing_name_count", True),
        ("missing_resolved_smiles_count", True),
        ("ai_authored_smiles_count", True),
    ],
)
def test_v2_authoritative_counters_require_integer_nonnegative_values(
    counter: str, value: object
) -> None:
    from review_writer.delivery import dual_parse_release as release

    row = _v2_authority_projections()[1]["studies"][0]
    assert isinstance(row, dict)
    if value is None:
        row.pop(counter)
    else:
        row[counter] = value

    with pytest.raises(
        release.DualParseReleaseError, match="DUAL_PARSE_AUTHORITY_INVALID"
    ):
        release.authority_rows_from_projections(
            *_v2_authority_projections(row)
        )


@pytest.mark.parametrize(
    "counter",
    [
        "missing_name_count",
        "missing_resolved_smiles_count",
        "ai_authored_smiles_count",
    ],
)
def test_v2_authoritative_counters_cannot_exceed_molecule_count(counter: str) -> None:
    from review_writer.delivery import dual_parse_release as release

    row = _v2_authority_projections()[1]["studies"][0]
    assert isinstance(row, dict)
    row[counter] = 2

    with pytest.raises(
        release.DualParseReleaseError, match="DUAL_PARSE_AUTHORITY_INVALID"
    ):
        release.authority_rows_from_projections(
            *_v2_authority_projections(row)
        )


@pytest.mark.parametrize(
    "legacy_counter",
    [
        "unresolved_field_count",
        "missing_smiles_expanded_count",
        "missing_smiles_unexpanded_count",
    ],
)
def test_v2_completion_rejects_legacy_counters_even_with_new_counters(
    legacy_counter: str,
) -> None:
    from review_writer.delivery import dual_parse_release as release

    row = _v2_authority_projections()[1]["studies"][0]
    assert isinstance(row, dict)
    row[legacy_counter] = 0

    with pytest.raises(
        release.DualParseReleaseError, match="DUAL_PARSE_AUTHORITY_INVALID"
    ):
        release.authority_rows_from_projections(
            *_v2_authority_projections(row)
        )


def test_authority_adapter_rejects_missing_v2_completion_row() -> None:
    from review_writer.delivery import dual_parse_release as release

    dual, _, reconciliation = _v2_authority_projections()
    completion = {
        "schema_version": "chemical-completion-project-state.v2",
        "studies": [],
    }

    with pytest.raises(
        release.DualParseReleaseError, match="DUAL_PARSE_AUTHORITY_INVALID"
    ):
        release.authority_rows_from_projections(dual, completion, reconciliation)


def test_nonchemical_row_missing_v2_counters_cannot_be_release_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from review_writer.delivery import dual_parse_release as release

    rows = _authority_rows()
    rows[0]["source_tier"] = "background"
    rows[0]["requires_chemical"] = False
    rows[0].pop("missing_resolved_smiles_count")
    rows[0].pop("ai_authored_smiles_count")
    project = _project(
        tmp_path, release.build_dual_parse_manuscript_bindings(rows, {"study-a"})
    )
    monkeypatch.setattr(release, "_current_authority_rows", lambda _: copy.deepcopy(rows))

    state = release.dual_parse_release_state(project)

    assert state["internal_release_ready"] is False
    assert "CHEMICAL_COMPLETION_INCOMPLETE" in state["hard_fails"]


def test_credits_are_not_applicable_and_never_projected_as_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from review_writer.delivery import dual_parse_release as release

    rows = _authority_rows()
    project = _project(
        tmp_path, release.build_dual_parse_manuscript_bindings(rows, {"study-a"})
    )
    monkeypatch.setattr(release, "_current_authority_rows", lambda _: copy.deepcopy(rows))

    state = release.dual_parse_release_state(project)

    assert state["credits_status"] == "NOT_APPLICABLE_BY_CURRENT_SCOPE"
    assert "credits" not in state
    assert "credit_count" not in state


def test_validate_dual_parse_bindings_is_fail_closed_on_unknown_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from review_writer.delivery import dual_parse_release as release

    rows = _authority_rows()
    project = _project(tmp_path, [])
    monkeypatch.setattr(release, "_current_authority_rows", lambda _: copy.deepcopy(rows))
    bindings = release.build_dual_parse_manuscript_bindings(rows, {"study-a"})
    bindings[0]["unexpected"] = True

    with pytest.raises(release.DualParseReleaseError, match="DUAL_PARSE_BINDING_INVALID"):
        release.validate_dual_parse_release_bindings(
            project, {"dual_parse_bindings": bindings}
        )


def test_http_completion_adapter_rejects_non_researcher_actor(
    tmp_path: Path,
) -> None:
    from review_writer.delivery import dual_parse_release as release

    project = tmp_path / "project"
    project.mkdir()
    with pytest.raises(
        release.DualParseReleaseError,
        match="CHEMICAL_COMPLETION_RESEARCHER_REQUIRED",
    ):
        release.apply_chemical_completion_http(
            project,
            {
                "study_id": "study-a",
                "version_token": "opaque",
                "actor_type": "content_agent",
                "actor_label": "writer",
                "corrections": [],
            },
        )


def test_dashboard_projection_whitelists_researcher_safe_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from review_writer.delivery import dual_parse_release as release

    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(
        release,
        "_dashboard_authority_payloads",
        lambda _: (
            {
                "project_status": "needs_review",
                "studies": [
                    {
                        "study_id": "study-a",
                        "source_tier": "core",
                        "status": "current",
                        "generic_status": "current",
                        "chemical_status": "missing",
                        "page_count": 6,
                        "source_pdf_sha256": SHA_A,
                        "binding_digest": SHA_B,
                        "local_path": "/private/project/source.pdf",
                    }
                ],
            },
            {
                "schema_version": "chemical-completion-project-state.v2",
                "studies": [
                    {
                        "study_id": "study-a",
                        "status": "blocked",
                        "missing_name_count": 1,
                        "missing_resolved_smiles_count": 2,
                        "ai_authored_smiles_count": 0,
                        "version_token": "completion-v1.opaque",
                        "missing_fields": [
                            {
                                "molecule_index": 0,
                                "field": "smiles_expanded",
                                "page": 3,
                            },
                            {
                                "molecule_index": 0,
                                "field": "resolved_smiles",
                                "page": 3,
                            },
                        ],
                    }
                ]
            },
            {
                "schema_version": "parse-reconciliation-project-state.v2",
                "studies": [
                    {
                        "study_id": "study-a",
                        "status": "blocked",
                        "unresolved_count": 1,
                        "registry_digest": SHA_C,
                    }
                ]
            },
            {
                "schema_version": "chemical-paper-projection.v2",
                "studies": [
                    {
                        "study_id": "study-a",
                        "backend": "pipeline",
                        "version": "1.0",
                        "molecule_count": 125,
                        "reaction_data_status": "unavailable_not_provided",
                        "molecules": [
                            {
                                "molecule_index": 0,
                                "mol_block": "secret raw block",
                                "pdf_page_url": "/api/project/case/pdf/study?page=3",
                            }
                        ],
                    }
                ]
            },
            {"unique_next_action": "Import Chemical Paper for study-a."},
        ),
    )

    projection = release.dual_parse_dashboard_projection(project)

    assert projection["studies"] == [
        {
            "study_id": "study-a",
            "source_tier": "core",
            "dual_source_status": "current",
            "pdf_status": "unknown",
            "generic_parse_status": "current",
            "chemical_import_status": "missing",
            "chemical_binding_status": "missing",
            "completion_status": "blocked",
            "reconciliation_status": "blocked",
            "page_count": 6,
            "molecule_count": 125,
            "missing_name_count": 1,
            "missing_resolved_smiles_count": 2,
            "unresolved_reconciliation_count": 1,
            "backend": "pipeline",
            "version": "1.0",
                "reaction_data_status": "unavailable_not_provided",
                "paper_evidence_status": "blocked",
                "completion_version_token": "completion-v1.opaque",
                "reconciliation_version_token": "rcv1."
                + base64.urlsafe_b64encode(bytes.fromhex(SHA_C))
                .decode("ascii")
                .rstrip("="),
            }
        ]
    encoded = json.dumps(projection, sort_keys=True)
    for forbidden in (SHA_A, SHA_B, SHA_C, "/private/", "mol_block", "credits"):
        assert forbidden not in encoded
    assert projection["completion_queue"] == [
        {
            "study_id": "study-a",
            "molecule_index": 0,
            "version_token": "completion-v1.opaque",
            "field": "resolved_smiles",
            "page": 3,
            "pdf_page_url": "/api/project/case/pdf/study?page=3",
        }
    ]


@pytest.mark.parametrize("mutation", ["missing_name", "legacy_counter"])
def test_dashboard_projection_rejects_invalid_v2_completion_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    from review_writer.delivery import dual_parse_release as release

    project = tmp_path / "project"
    project.mkdir()
    dual, completion, reconciliation = _v2_authority_projections()
    row = completion["studies"][0]
    assert isinstance(row, dict)
    if mutation == "missing_name":
        row.pop("missing_name_count")
    else:
        row["unresolved_field_count"] = 0
    monkeypatch.setattr(
        release,
        "_dashboard_authority_payloads",
        lambda _: (
            dual,
            completion,
            reconciliation,
            {
                "schema_version": "chemical-paper-projection.v2",
                "studies": [
                    {
                        "study_id": "study-a",
                        "status": "missing",
                    }
                ],
            },
            {},
        ),
    )

    with pytest.raises(
        release.DualParseReleaseError, match="DUAL_PARSE_AUTHORITY_INVALID"
    ):
        release.dual_parse_dashboard_projection(project)


@pytest.mark.parametrize(
    ("completion_version", "reconciliation_version", "chemical_version"),
    [
        (
            None,
            "parse-reconciliation-project-state.v2",
            "chemical-paper-projection.v2",
        ),
        (
            "chemical-completion-project-state.v2",
            None,
            "chemical-paper-projection.v2",
        ),
        (
            "chemical-completion-project-state.v2",
            "parse-reconciliation-project-state.v2",
            None,
        ),
        (
            "chemical-completion-project-state.v1",
            "parse-reconciliation-project-state.v2",
            "chemical-paper-projection.v2",
        ),
        (
            "chemical-completion-project-state.v2",
            "parse-reconciliation-project-state.v1",
            "chemical-paper-projection.v2",
        ),
        (
            "chemical-completion-project-state.v2",
            "parse-reconciliation-project-state.v2",
            "chemical-paper-projection.v1",
        ),
    ],
)
def test_dashboard_projection_rejects_legacy_scientific_authority_versions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    completion_version: str | None,
    reconciliation_version: str | None,
    chemical_version: str | None,
) -> None:
    from review_writer.delivery import dual_parse_release as release

    project = tmp_path / "project"
    project.mkdir()
    completion: dict[str, object] = {"studies": []}
    reconciliation: dict[str, object] = {"studies": []}
    chemical: dict[str, object] = {"studies": []}
    if completion_version is not None:
        completion["schema_version"] = completion_version
    if reconciliation_version is not None:
        reconciliation["schema_version"] = reconciliation_version
    if chemical_version is not None:
        chemical["schema_version"] = chemical_version
    monkeypatch.setattr(
        release,
        "_dashboard_authority_payloads",
        lambda _: (
            {"studies": []},
            completion,
            reconciliation,
            chemical,
            {},
        ),
    )

    with pytest.raises(
        release.DualParseReleaseError, match="DUAL_PARSE_AUTHORITY_INVALID"
    ):
        release.dual_parse_dashboard_projection(project)


def test_candidate_smiles_difference_is_not_projected_as_reaction_or_zero() -> None:
    from review_writer.delivery import dual_parse_release as release

    rows = release.authority_rows_from_projections(
        {
            "studies": [
                {
                    "study_id": "study-a",
                    "source_tier": "core",
                    "requires_chemical": True,
                    "binding_digest": SHA_A,
                    "generic": {"status": "current", "binding_digest": SHA_B},
                    "chemical": {
                        "status": "current",
                        "state_digest": SHA_C,
                        "reaction_data_status": "unavailable_not_provided",
                        "candidate_smiles_differ_count": 1,
                    },
                }
            ]
        },
        {
            "schema_version": "chemical-completion-project-state.v2",
            "studies": [
                {
                    "study_id": "study-a",
                    "status": "current",
                    "gate_digest": SHA_D,
                    "missing_name_count": 0,
                    "missing_resolved_smiles_count": 0,
                    "ai_authored_smiles_count": 0,
                }
            ]
        },
        {
            "schema_version": "parse-reconciliation-project-state.v2",
            "studies": [
                {
                    "study_id": "study-a",
                    "status": "current",
                    "registry_digest": SHA_A,
                }
            ]
        },
    )

    assert rows[0]["reaction_data_status"] == "unavailable_not_provided"
    assert rows[0]["reaction_count"] is None
    assert "candidate_smiles_differ_count" not in rows[0]


def test_scientific_projection_adapter_accepts_nested_public_contracts() -> None:
    from review_writer.delivery import dual_parse_release as release

    rows = release.authority_rows_from_projections(
        {
            "studies": [
                {
                    "study_id": "study-a",
                    "source_tier": "core",
                    "status": "current",
                    "binding_digest": SHA_A,
                    "generic": {"status": "current", "binding_digest": SHA_B},
                    "chemical": {
                        "status": "current",
                        "state_digest": SHA_C,
                        "reaction_data_status": "unavailable_not_provided",
                    },
                }
            ]
        },
        {
            "schema_version": "chemical-completion-project-state.v2",
            "studies": [
                {
                    "study_id": "study-a",
                    "status": "current",
                    "gate_digest": SHA_D,
                    "missing_name_count": 0,
                    "missing_resolved_smiles_count": 0,
                    "ai_authored_smiles_count": 0,
                }
            ]
        },
        {
            "schema_version": "parse-reconciliation-project-state.v2",
            "studies": [
                {
                    "study_id": "study-a",
                    "status": "current",
                    "registry_digest": "e" * 64,
                }
            ]
        },
    )

    assert rows == [
        {
            "study_id": "study-a",
            "source_tier": "core",
            "requires_chemical": False,
            "dual_source_binding_digest": SHA_A,
            "generic_status": "current",
            "generic_version": SHA_B,
            "chemical_status": "current",
            "chemical_version": SHA_C,
            "chemical_completion_status": "current",
            "chemical_completion_digest": SHA_D,
            "reconciliation_status": "current",
            "reconciliation_digest": "e" * 64,
            "content_result_status": "current",
            "missing_name_count": 0,
            "missing_resolved_smiles_count": 0,
            "ai_authored_smiles_count": 0,
            "reaction_data_status": "unavailable_not_provided",
            "reaction_count": None,
            "unreviewed_element_molecule_count": 0,
        }
    ]


@pytest.mark.parametrize(
    ("completion_version", "reconciliation_version"),
    [
        (None, "parse-reconciliation-project-state.v2"),
        ("chemical-completion-project-state.v2", None),
        ("chemical-completion-project-state.v1", "parse-reconciliation-project-state.v2"),
        ("chemical-completion-project-state.v2", "parse-reconciliation-project-state.v1"),
    ],
)
def test_scientific_projection_adapter_rejects_legacy_authority_versions(
    completion_version: str | None, reconciliation_version: str | None
) -> None:
    from review_writer.delivery import dual_parse_release as release

    completion: dict[str, object] = {"studies": []}
    reconciliation: dict[str, object] = {"studies": []}
    if completion_version is not None:
        completion["schema_version"] = completion_version
    if reconciliation_version is not None:
        reconciliation["schema_version"] = reconciliation_version
    with pytest.raises(
        release.DualParseReleaseError, match="DUAL_PARSE_AUTHORITY_INVALID"
    ):
        release.authority_rows_from_projections(
            {"studies": []},
            completion,
            reconciliation,
        )


@pytest.mark.parametrize(
    "completion_row",
    [
        {
            "study_id": "study-a",
            "missing_smiles_expanded_count": 0,
            "missing_smiles_unexpanded_count": 0,
            "ai_authored_smiles_count": 0,
        },
        {
            "study_id": "study-a",
            "missing_resolved_smiles_count": 0,
        },
    ],
)
def test_scientific_projection_adapter_rejects_legacy_or_missing_smiles_counters(
    completion_row: dict[str, object],
) -> None:
    from review_writer.delivery import dual_parse_release as release

    with pytest.raises(
        release.DualParseReleaseError, match="DUAL_PARSE_AUTHORITY_INVALID"
    ):
        release.authority_rows_from_projections(
            {"studies": []},
            {
                "schema_version": "chemical-completion-project-state.v2",
                "studies": [completion_row],
            },
            {
                "schema_version": "parse-reconciliation-project-state.v2",
                "studies": [],
            },
        )


def test_release_state_fails_closed_when_authority_projection_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from review_writer.delivery import dual_parse_release as release

    rows = _authority_rows()
    project = _project(
        tmp_path, release.build_dual_parse_manuscript_bindings(rows, {"study-a"})
    )

    def unavailable(_: Path) -> list[dict[str, object]]:
        raise release.DualParseReleaseError("DUAL_PARSE_AUTHORITY_UNAVAILABLE")

    monkeypatch.setattr(release, "_current_authority_rows", unavailable)

    state = release.dual_parse_release_state(project)

    assert state["internal_release_ready"] is False
    assert state["dual_parse_status"] == "stale"
    assert state["hard_fails"] == ["DUAL_PARSE_STALE"]
