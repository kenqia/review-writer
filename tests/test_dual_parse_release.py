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
                "studies": [
                    {
                        "study_id": "study-a",
                        "status": "blocked",
                        "missing_name_count": 1,
                        "missing_smiles_expanded_count": 2,
                        "missing_smiles_unexpanded_count": 2,
                        "version_token": "completion-v1.opaque",
                    }
                ]
            },
            {
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
                "studies": [
                    {
                        "study_id": "study-a",
                        "backend": "pipeline",
                        "version": "1.0",
                        "molecule_count": 125,
                        "reaction_data_status": "unavailable_not_provided",
                        "molecules": [{"mol_block": "secret raw block"}],
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
            "completion_status": "blocked",
            "reconciliation_status": "blocked",
            "page_count": 6,
            "molecule_count": 125,
            "missing_name_count": 1,
            "missing_smiles_expanded_count": 2,
            "missing_smiles_unexpanded_count": 2,
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
            "studies": [
                {
                    "study_id": "study-a",
                    "status": "current",
                    "gate_digest": SHA_D,
                    "ai_authored_smiles_count": 0,
                }
            ]
        },
        {
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
            "ai_authored_smiles_count": 0,
            "reaction_data_status": "unavailable_not_provided",
            "reaction_count": None,
            "unreviewed_element_molecule_count": 0,
        }
    ]


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
