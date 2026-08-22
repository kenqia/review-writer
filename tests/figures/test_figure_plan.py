from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from review_writer.project.review_figures import (
    FigurePlanWorkspace,
    ReviewFigureError,
    build_figure_plan,
    figure_plan_digest,
)


HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def _source_figure(*, evidence_ids: list[str] | None = None) -> dict[str, Any]:
    return {
        "figure_id": "SF1",
        "study_id": "ST1",
        "source_id": "SRC1",
        "page": 1,
        "figure_label": "Figure 1",
        "caption": "Source-bound figure caption",
        "asset_path": "01_evidence/figures/figure-1.png",
        "asset_sha256": HASH_A,
        "source_pdf_sha256": HASH_B,
        "evidence_ids": evidence_ids or ["E1"],
        "selection_status": "selected",
        "fragments": [
            {
                "page": 1,
                "block_index": 0,
                "bbox": [0, 0, 100, 100],
                "asset_path": "01_evidence/figures/figure-1.png",
                "asset_sha256": HASH_A,
                "caption_association": "explicit_caption_anchor",
            }
        ],
        "rights_status": "cleared",
        "rights_license": "research-license",
    }


def _placeholder() -> dict[str, Any]:
    return {
        "placeholder_id": "PH1",
        "scientific_question": "How do the reported systems differ?",
        "reader_takeaway": "Compare only after the stated limitations are reviewed.",
        "panels": [
            {
                "panel": "A",
                "task": "Show the source-bound comparison axis.",
                "synthesis_claim_ids": ["C1"],
                "source_figure_ids": ["SF1"],
            }
        ],
        "comparison_axis": "reported outcome",
        "required_labels_units": ["reported outcome"],
        "counter_evidence": ["E1"],
        "forbidden_overclaims": ["Do not claim cross-study equivalence."],
        "unresolved_uncertainties": ["Data scales are not yet comparable."],
        "caption_draft": "Human-owned synthesis figure placeholder.",
        "target_size": "single-column",
        "status": "awaiting_human_figure",
    }


def _evidence(
    *,
    evidence_id: str = "E1",
    status: str = "CONFIRMED",
    source_role: str = "primary",
    lineage_id: str = "L1",
    locator: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "status": status,
        "source_id": "SRC1",
        "study_id": "ST1",
        "source_role": source_role,
        "lineage_id": lineage_id,
        "locator": locator or {"page": 1, "figure_or_table": "Figure 1"},
        "provenance": {"source_id": "SRC1", "source_pdf_sha256": HASH_B},
    }


def _item(
    *,
    figure_id: str = "FP1",
    figure_type: str = "source_figure",
    evidence_ids: list[str] | None = None,
    source_role: str = "primary",
    authorization_status: str = "cleared",
    redraw_status: str = "not_applicable",
    source_figure_id: str | None = "SF1",
    placeholder_id: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "figure_id": figure_id,
        "purpose": "Show the source-bound result relevant to RQ1.",
        "type": figure_type,
        "research_question": "RQ1",
        "section_id": "SEC1",
        "evidence_ids": evidence_ids or ["E1"],
        "synthesis_ids": ["SY1"],
        "claim_ids": ["C1"],
        "draft_ids": ["D1"],
        "caption": "Bound caption for the planned figure.",
        "legend": "Legend and units remain source-bound.",
        "version": {"version_id": "v1", "manuscript_digest": HASH_C},
        "lineage": {"lineage_id": "L1", "parent_lineage_id": "L0"},
        "source_role": source_role,
        "provenance": {"source_id": "SRC1", "source_figure_id": source_figure_id},
        "locator": {"page": 1, "figure_or_table": "Figure 1"},
        "authorization_status": authorization_status,
        "redraw_status": redraw_status,
    }
    if source_figure_id is not None:
        item["source_figure_id"] = source_figure_id
    if placeholder_id is not None:
        item["placeholder_id"] = placeholder_id
    return item


def _records() -> dict[str, Any]:
    return {
        "project_id": "PROJECT1",
        "items": [_item()],
        "source_figures": [_source_figure()],
        "placeholders": [],
        "evidence": [_evidence()],
        "synthesis": [
            {
                "synthesis_id": "SY1",
                "evidence_ids": ["E1"],
                "status": "current",
                "lineage_id": "L1",
            }
        ],
        "claims": [
            {
                "claim_id": "C1",
                "synthesis_ids": ["SY1"],
                "evidence_ids": ["E1"],
                "status": "current",
                "lineage_id": "L1",
            }
        ],
        "drafts": [{"draft_id": "D1", "figure_ids": ["FP1"]}],
        "citations": [{"citation_id": "CIT1", "figure_ids": ["FP1"]}],
        "exports": [{"export_id": "EXP1", "figure_ids": ["FP1"]}],
        "releases": [{"release_id": "REL1", "figure_ids": ["FP1"]}],
    }


def _build(records: dict[str, Any]) -> FigurePlanWorkspace:
    return FigurePlanWorkspace.from_records(**records)


def test_figure_plan_binds_all_refs_and_has_deterministic_digest() -> None:
    records = _records()
    before = copy.deepcopy(records)

    plan = build_figure_plan(**records)

    item = plan["items"][0]
    assert {
        "purpose",
        "type",
        "research_question",
        "section_id",
        "evidence_ids",
        "synthesis_ids",
        "claim_ids",
        "draft_ids",
        "caption",
        "legend",
        "version",
        "lineage",
        "source_role",
        "provenance",
        "locator",
        "authorization_status",
        "redraw_status",
    } <= set(item)
    assert plan["plan_digest"] == figure_plan_digest(plan)
    assert plan["promotion"] == "NONE"
    assert plan["acceptance"] == {
        "human_acceptance": "UNKNOWN",
        "scientific_validity": "UNKNOWN",
    }
    assert records == before

    reversed_records = copy.deepcopy(records)
    reversed_records["items"] = list(reversed(reversed_records["items"]))
    assert build_figure_plan(**reversed_records)["plan_digest"] == plan["plan_digest"]


def test_figure_types_are_distinct_and_missing_truth_stays_explicit() -> None:
    records = _records()
    records["items"] = [
        _item(figure_id="SOURCE", figure_type="source_figure"),
        _item(
            figure_id="REDRAW",
            figure_type="redrawn_figure",
            authorization_status="pending",
            redraw_status="requested",
        ),
        _item(
            figure_id="SYNTH",
            figure_type="new_synthesis_figure",
            authorization_status="pending",
            redraw_status="not_applicable",
            source_figure_id=None,
        ),
        _item(
            figure_id="PLACEHOLDER",
            figure_type="placeholder",
            authorization_status="pending",
            redraw_status="not_applicable",
            source_figure_id=None,
            placeholder_id="PH1",
        ),
    ]
    records["placeholders"] = [_placeholder()]

    plan = build_figure_plan(**records)

    by_type = {item["type"]: item for item in plan["items"]}
    assert set(by_type) == {
        "source_figure",
        "redrawn_figure",
        "new_synthesis_figure",
        "placeholder",
    }
    assert "GAP" in by_type["redrawn_figure"]["status_flags"]
    assert {"GAP", "AI_PROVISIONAL"} <= set(
        by_type["new_synthesis_figure"]["status_flags"]
    )
    assert {"GAP", "AI_PROVISIONAL"} <= set(
        by_type["placeholder"]["status_flags"]
    )
    assert "asset_bytes" not in plan
    assert "pdf_bytes" not in plan


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda records: records["items"][0].update(evidence_ids=["MISSING"]), "FIGURE_EVIDENCE_NOT_FOUND"),
        (lambda records: records["evidence"][0].update(locator={}), "FIGURE_LOCATOR_REQUIRED"),
        (lambda records: records["evidence"][0].update(source_role=""), "FIGURE_SOURCE_ROLE_REQUIRED"),
        (lambda records: records["evidence"][0].pop("lineage_id"), "FIGURE_LINEAGE_REQUIRED"),
        (lambda records: records["evidence"][0].update(status="STALE"), "FIGURE_EVIDENCE_STALE"),
    ],
)
def test_missing_or_stale_bindings_fail_closed_without_mutating_input(
    mutate: Any, code: str
) -> None:
    records = _records()
    mutate(records)
    before = copy.deepcopy(records)

    with pytest.raises(ReviewFigureError) as error:
        build_figure_plan(**records)

    assert error.value.code == code
    assert records == before


def test_impact_preview_is_read_only_and_does_not_merge_non_comparable_data() -> None:
    records = _records()
    workspace = _build(records)
    state_before = workspace.state()

    preview = workspace.impact_preview("FP1")

    assert preview["mutation"] == "NONE"
    assert preview["promotion"] == "NONE"
    assert preview["draft_refs"] == ["D1"]
    assert preview["citation_refs"] == ["CIT1"]
    assert preview["export_refs"] == ["EXP1"]
    assert preview["release_refs"] == ["REL1"]
    assert preview["would_invalidate"] == [
        {"kind": "citation", "id": "CIT1", "reason": "FIGURE_PLAN_CHANGED"},
        {"kind": "draft", "id": "D1", "reason": "FIGURE_PLAN_CHANGED"},
        {"kind": "export", "id": "EXP1", "reason": "FIGURE_PLAN_CHANGED"},
        {"kind": "release", "id": "REL1", "reason": "FIGURE_PLAN_CHANGED"},
    ]
    assert workspace.state() == state_before

    non_comparable = _records()
    non_comparable["evidence"].append(
        _evidence(evidence_id="E2", status="NON_COMPARABLE", lineage_id="L2")
    )
    nc_item = _item(
        figure_id="NC1",
        figure_type="new_synthesis_figure",
        evidence_ids=["E1", "E2"],
        source_figure_id=None,
        authorization_status="pending",
    )
    nc_item["draft_ids"] = []
    non_comparable["items"] = [nc_item]
    non_comparable["drafts"] = []
    non_comparable["citations"] = []
    non_comparable["exports"] = []
    non_comparable["releases"] = []
    plan = build_figure_plan(**non_comparable)
    item = plan["items"][0]
    assert "NON_COMPARABLE" in item["status_flags"]
    assert item["comparison"]["merge"] == "NONE"


def test_history_is_immutable_and_requires_explicit_confirmation_and_activation() -> None:
    workspace = _build(_records())
    initial_state = workspace.state()

    view = workspace.view_snapshot("v1")
    view["plan"]["items"][0]["caption"] = "mutated outside"
    assert workspace.view_snapshot("v1")["plan"]["items"][0]["caption"] != "mutated outside"

    download = workspace.download_snapshot("v1")
    downloaded = json.loads(download.content.decode("utf-8"))
    assert download.media_type == "application/json"
    assert downloaded["snapshot_id"] == "v1"
    assert "image_bytes" not in downloaded
    assert workspace.state() == initial_state

    changed_items = copy.deepcopy(_records()["items"])
    changed_items[0]["caption"] = "Updated caption"
    proposal = workspace.propose_change(
        {"items": changed_items},
        base_snapshot_id="v1",
        branch_id="edit-1",
        snapshot_id="v2",
    )
    assert workspace.state() == initial_state

    with pytest.raises(ReviewFigureError) as error:
        workspace.confirm_change(proposal)
    assert error.value.code == "FIGURE_CONFIRMATION_REQUIRED"

    confirmed = workspace.confirm_change(proposal, confirm=True)
    assert confirmed["snapshot_id"] == "v2"
    assert workspace.state() == initial_state

    with pytest.raises(ReviewFigureError) as error:
        workspace.propose_change(
            {"items": changed_items},
            base_snapshot_id="v2",
            branch_id="edit-2",
            snapshot_id="v3",
        )
    assert error.value.code == "FIGURE_NON_HEAD_WRITE"

    with pytest.raises(ReviewFigureError) as error:
        workspace.activate_snapshot("v2")
    assert error.value.code == "FIGURE_CONFIRMATION_REQUIRED"

    activated = workspace.activate_snapshot("v2", confirm=True)
    assert activated["current_snapshot_id"] == "v2"
    assert activated["active_head_id"] == "v2"
    assert workspace.view_snapshot("v1")["read_only"] is True
    assert workspace.view_snapshot("v2")["can_write"] is True

    comparison = workspace.compare_snapshots("v1", "v2")
    assert "plan" in comparison["changed_fields"]
    assert workspace.state()["current_snapshot_id"] == "v2"


def test_branch_from_historical_snapshot_never_moves_current_without_activation() -> None:
    workspace = _build(_records())

    with pytest.raises(ReviewFigureError) as error:
        workspace.branch_from_here(
            "v1", branch_id="from-history", snapshot_id="v2"
        )
    assert error.value.code == "FIGURE_CONFIRMATION_REQUIRED"

    branch = workspace.branch_from_here(
        "v1",
        branch_id="from-history",
        snapshot_id="v2",
        confirm=True,
    )
    assert branch["branch_id"] == "from-history"
    assert workspace.state()["current_snapshot_id"] == "v1"

    activated = workspace.activate_branch("from-history", confirm=True)
    assert activated["current_snapshot_id"] == "v2"
    assert activated["active_branch_id"] == "from-history"
