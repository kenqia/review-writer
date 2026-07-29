from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from review_writer.project.manuscript_v2 import (
    ManuscriptV2Error,
    approve_section,
    build_manuscript_workspace,
    merge_authoritative_manuscript,
    register_section_draft,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "new-route"
    (root / "01_evidence/source_truth/study-a").mkdir(parents=True)
    contract = {
        "section_id": "section-one",
        "research_question": "What was established?",
        "contract_digest": SHA_D,
        "status": "approved",
        "decision": {"action": "approve", "bound_object_digest": SHA_D},
    }
    monkeypatch.setattr(
        "review_writer.project.manuscript_v2.section_contract_state",
        lambda _: {
            "workflow_can_continue": True,
            "projection_digest": SHA_C,
            "rows": [contract],
        },
    )
    monkeypatch.setattr(
        "review_writer.project.manuscript_v2.paper_evidence_state",
        lambda _: {
            "workflow_can_continue": True,
            "projection_digest": SHA_A,
            "rows": [
                {
                    "evidence_id": "evidence-low",
                    "study_id": "study-a",
                    "status": "approved",
                    "risk_classes": [],
                },
                {
                    "evidence_id": "evidence-high",
                    "study_id": "study-a",
                    "status": "approved",
                    "risk_classes": ["MECHANISM_CAUSALITY"],
                },
            ],
        },
    )
    monkeypatch.setattr(
        "review_writer.project.manuscript_v2.synthesis_state",
        lambda _: {
            "workflow_can_continue": True,
            "projection_digest": SHA_B,
            "rows": [
                {
                    "synthesis_id": "synthesis-one",
                    "status": "approved",
                    "risk_class": "scope",
                }
            ],
        },
    )
    monkeypatch.setattr(
        "review_writer.project.manuscript_v2.project_parse_quality_state",
        lambda _: {
            "workflow_can_continue": True,
            "studies": [{"objects": [{"object_digest": SHA_E}]}],
        },
    )
    monkeypatch.setattr(
        "review_writer.project.manuscript_v2.workflow_state",
        lambda _: {"route": "evidence-to-release.v1", "workflow_digest": "f" * 64},
    )
    return root


def _draft(body: str, **extra: object) -> dict:
    return {
        "section_id": "section-one",
        "heading": "Evidence summary",
        "body": body,
        "content_agent_result_digest": hashlib.sha256(b"content-result").hexdigest(),
        **extra,
    }


def _actor() -> dict:
    return {
        "actor_type": "simulated_researcher_agent",
        "actor_label": "playwright-researcher-round-1",
    }


def test_new_route_draft_never_reads_legacy_first_draft(project: Path) -> None:
    legacy = project / "04_first_draft/first_draft.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("LEGACY SENTINEL", encoding="utf-8")

    payload = build_manuscript_workspace(project)

    assert "LEGACY SENTINEL" not in json.dumps(payload)
    assert payload["route"] == "evidence-to-release.v1"
    assert payload["sections"] == []


def test_section_generation_requires_approved_contract(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "review_writer.project.manuscript_v2.section_contract_state",
        lambda _: {
            "workflow_can_continue": False,
            "projection_digest": SHA_C,
            "rows": [{"section_id": "section-one", "status": "needs_review"}],
        },
    )

    with pytest.raises(ManuscriptV2Error, match="SECTION_CONTRACT_NOT_APPROVED"):
        register_section_draft(
            project,
            _draft("The experiment reported the product. [evidence:evidence-low]"),
        )


def test_unapproved_or_missing_claim_marker_is_rejected(project: Path) -> None:
    with pytest.raises(ManuscriptV2Error, match="CLAIM_NOT_APPROVED"):
        register_section_draft(
            project,
            _draft("The experiment reported the product. [evidence:unknown-evidence]"),
        )
    with pytest.raises(ManuscriptV2Error, match="SCIENTIFIC_CLAIM_UNMARKED"):
        register_section_draft(project, _draft("The reaction delivered 82% yield."))
    with pytest.raises(ManuscriptV2Error, match="SCIENTIFIC_CLAIM_UNMARKED"):
        register_section_draft(project, _draft("Visible-light catalysis enables this transformation."))


def test_narrow_transition_sentence_may_remain_unmarked(project: Path) -> None:
    draft = register_section_draft(
        project,
        _draft(
            "The next section compares these studies.\n\n"
            "The experiment reported the product. [evidence:evidence-low]"
        ),
    )
    assert draft["status"] == "needs_review"


def test_high_risk_claim_requires_simulated_human_edit_decision(project: Path) -> None:
    draft = register_section_draft(
        project,
        _draft("The evidence proves a radical mechanism. [evidence:evidence-high]"),
    )
    assert draft["status"] == "needs_human_edit"
    with pytest.raises(ManuscriptV2Error, match="HIGH_RISK_EDIT_PENDING"):
        approve_section(project, draft["section_id"], actor=None)
    with pytest.raises(ManuscriptV2Error, match="HIGH_RISK_EDIT_PENDING"):
        approve_section(project, draft["section_id"], actor=_actor(), reason="Checked evidence.")


def test_quantitative_claim_is_high_risk_even_when_source_risk_list_is_empty(project: Path) -> None:
    draft = register_section_draft(
        project,
        _draft("The reaction delivered 82% yield. [evidence:evidence-low]"),
    )
    assert draft["status"] == "needs_human_edit"


def test_high_risk_edit_records_original_replacement_actor_and_upstream(project: Path) -> None:
    original = "The evidence proves a radical mechanism. [evidence:evidence-high]"
    draft = register_section_draft(project, _draft(original))
    replacement = (
        "The authors proposed a radical mechanism, with indirect support. "
        "[evidence:evidence-high]"
    )

    approved = approve_section(
        project,
        draft["section_id"],
        actor=_actor(),
        edited_body=replacement,
        reason="Narrowed the causal wording after source comparison.",
        expected_draft_digest=draft["draft_digest"],
    )

    assert approved["status"] == "approved"
    assert approved["decision"]["actor_type"] == "simulated_researcher_agent"
    assert approved["decision"]["original_expression"] == original
    assert approved["decision"]["edited_expression"] == replacement
    assert approved["decision"]["upstream_digest"]


def test_approved_sections_merge_to_authoritative_manuscript_and_lineage(project: Path) -> None:
    draft = register_section_draft(
        project,
        _draft("The experiment reported the product. [evidence:evidence-low]"),
    )
    approve_section(
        project,
        draft["section_id"],
        actor=_actor(),
        reason="Compared against the approved evidence.",
    )

    result = merge_authoritative_manuscript(project)

    manuscript = project / "04_manuscript/manuscript.md"
    lineage_path = project / "04_manuscript/manuscript_lineage.v2.json"
    assert manuscript.is_file()
    assert lineage_path.is_file()
    assert "04_first_draft" not in result["manuscript_path"]
    lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    assert lineage["route"] == "evidence-to-release.v1"
    assert lineage["parse_object_digests"] == [SHA_E]
    assert lineage["paper_evidence_projection_digest"] == SHA_A
    assert lineage["synthesis_projection_digest"] == SHA_B
    assert lineage["section_contract_projection_digest"] == SHA_C
    assert lineage["sections"][0]["generation_content_agent_result_digest"]
    assert lineage["claim_bindings"][0]["paper_evidence_ids"] == ["evidence-low"]


def test_merge_failure_does_not_overwrite_existing_authoritative_pair(project: Path) -> None:
    target = project / "04_manuscript"
    target.mkdir(parents=True)
    manuscript = target / "manuscript.md"
    lineage = target / "manuscript_lineage.v2.json"
    manuscript.write_bytes(b"existing manuscript")
    lineage.write_bytes(b"existing lineage")
    before = (manuscript.read_bytes(), lineage.read_bytes())

    with pytest.raises(ManuscriptV2Error, match="SECTION_DRAFT_NOT_APPROVED"):
        merge_authoritative_manuscript(project)

    assert (manuscript.read_bytes(), lineage.read_bytes()) == before


def test_manuscript_output_directory_cannot_be_a_symlink(project: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (project / "04_manuscript").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ManuscriptV2Error, match="PROJECT_PATH_INVALID"):
        register_section_draft(
            project,
            _draft("The experiment reported the product. [evidence:evidence-low]"),
        )
    assert list(outside.iterdir()) == []
