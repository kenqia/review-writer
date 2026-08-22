from __future__ import annotations

import copy
import hashlib
import json

import pytest

from review_writer.draft import (
    DraftWorkspace,
    DraftHistoryError,
    DraftValidationError,
)


HASH = hashlib.sha256(b"non-sensitive fixture").hexdigest()


def _evidence(
    evidence_id: str,
    *,
    status: str,
    source_role: str,
    lineage_id: str,
    current: bool = True,
) -> dict[str, object]:
    return {
        "evidence_id": evidence_id,
        "source_id": f"source-{evidence_id}",
        "study_id": f"study-{evidence_id}",
        "source_role": source_role,
        "status": status,
        "lineage": {"lineage_id": lineage_id, "source_digest": HASH},
        "locator": {"page": 2, "section_or_item": "results"},
        "current": current,
    }


def _records() -> dict[str, list[dict[str, object]]]:
    evidence = [
        _evidence(
            "e-main",
            status="AI_PROVISIONAL",
            source_role="MAIN",
            lineage_id="line-main",
        ),
        _evidence(
            "e-si",
            status="GAP",
            source_role="SI",
            lineage_id="line-si",
        ),
        _evidence(
            "e-comparator",
            status="NON_COMPARABLE",
            source_role="COMPARATOR",
            lineage_id="line-comparator",
        ),
    ]
    claims = [
        {
            "claim_id": "claim-1",
            "claim_text": "The fixture keeps a provisional observation bound to its source.",
            "evidence_ids": ["e-main", "e-si"],
            "status": "AI_PROVISIONAL",
            "lineage": {"lineage_id": "claim-line-1", "parents": ["line-main", "line-si"]},
        },
        {
            "claim_id": "claim-2",
            "claim_text": "The comparator is retained without comparison promotion.",
            "evidence_ids": ["e-comparator"],
            "status": "NON_COMPARABLE",
            "lineage": {"lineage_id": "claim-line-2", "parents": ["line-comparator"]},
        },
    ]
    drafts = [
        {
            "draft_id": "draft-current",
            "status": "DRAFT",
            "current": True,
            "historical": False,
            "lineage": {"lineage_id": "draft-line-current", "parents": ["claim-line-1"]},
            "blocks": [
                {
                    "block_id": "block-1",
                    "claim_refs": ["claim-1"],
                    "evidence_refs": ["e-main", "e-si"],
                    "pdf_locator": {"page": 4, "section": "discussion"},
                    "pdf_hash": HASH,
                },
                {
                    "block_id": "block-2",
                    "claim_refs": ["claim-2"],
                    "evidence_refs": ["e-comparator"],
                    "pdf_locator": {"page": 5, "section": "limitations"},
                    "pdf_hash": HASH,
                },
            ],
        },
    ]
    pdfs = [
        {
            "pdf_id": "pdf-current",
            "draft_id": "draft-current",
            "status": "METADATA_ONLY",
            "descriptor": {"sha256": HASH, "media_type": "application/pdf"},
        }
    ]
    return {"evidence": evidence, "claims": claims, "drafts": drafts, "pdfs": pdfs}


def _history_records() -> dict[str, list[dict[str, object]]]:
    records = _records()
    records["drafts"].append(
        {
            "draft_id": "draft-history",
            "status": "HISTORICAL_DRAFT",
            "current": False,
            "historical": True,
            "lineage": {"lineage_id": "draft-line-history", "parents": ["claim-line-1"]},
            "blocks": [
                {
                    "block_id": "block-history",
                    "claim_refs": ["claim-1"],
                    "evidence_refs": ["e-main"],
                    "pdf_locator": {"page": 3, "section": "results"},
                    "pdf_hash": HASH,
                }
            ],
        }
    )
    records["pdfs"].append(
        {
            "pdf_id": "pdf-history",
            "draft_id": "draft-history",
            "status": "HISTORICAL_METADATA",
            "historical": True,
            "current": False,
            "descriptor": {"sha256": HASH, "media_type": "application/pdf"},
        }
    )
    return records


def test_source_bound_four_way_mapping_preserves_status_and_divergent_lineage() -> None:
    workspace = DraftWorkspace.from_records(**_records())

    snapshot = workspace.snapshot()
    linkage = snapshot["linkage"]

    assert snapshot["schema_version"] == "review-writer.evidence-aware-draft.v1"
    assert snapshot["digest"] == hashlib.sha256(
        json.dumps(
            {key: value for key, value in snapshot.items() if key != "digest"},
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert {row["evidence_id"]: row["status"] for row in snapshot["evidence"]} == {
        "e-main": "AI_PROVISIONAL",
        "e-si": "GAP",
        "e-comparator": "NON_COMPARABLE",
    }
    assert linkage["claim_refs"] == ["claim-1", "claim-2"]
    assert linkage["draft_refs"] == ["draft-current"]
    assert linkage["pdf_refs"] == ["pdf-current"]
    assert linkage["divergent_lineage"] is True
    assert linkage["source_roles"] == ["COMPARATOR", "MAIN", "SI"]


def test_missing_or_stale_evidence_is_rejected_without_mutating_inputs() -> None:
    records = _records()
    before = copy.deepcopy(records)
    records["claims"][0]["evidence_ids"] = ["missing-evidence"]

    with pytest.raises(DraftValidationError) as missing:
        DraftWorkspace.from_records(**records)

    assert missing.value.code == "CLAIM_EVIDENCE_NOT_FOUND"
    assert records["evidence"] == before["evidence"]

    stale_records = _records()
    stale_records["evidence"][0]["status"] = "STALE"
    stale_before = copy.deepcopy(stale_records)

    with pytest.raises(DraftValidationError) as stale:
        DraftWorkspace.from_records(**stale_records)

    assert stale.value.code == "CLAIM_EVIDENCE_STALE"
    assert stale_records == stale_before


def test_impact_preview_lists_claim_draft_pdf_refs_without_mutating_current() -> None:
    workspace = DraftWorkspace.from_records(**_records())
    before = workspace.snapshot()
    replacement = copy.deepcopy(_records()["evidence"][0])
    replacement["status"] = "GAP"

    preview = workspace.impact_preview(
        "evidence",
        "e-main",
        replacement=replacement,
    )

    assert preview["mode"] == "PREVIEW_ONLY"
    assert preview["target"] == {"kind": "evidence", "id": "e-main"}
    assert preview["claim_refs"] == ["claim-1"]
    assert preview["draft_refs"] == ["draft-current"]
    assert preview["pdf_refs"] == ["pdf-current"]
    assert "EVIDENCE_STATUS_GAP" in preview["blocking_reasons"]
    assert workspace.snapshot() == before


def test_history_view_compare_download_do_not_change_current_or_snapshot() -> None:
    workspace = DraftWorkspace.from_records(**_history_records())
    before = workspace.snapshot()

    view = workspace.view_node("draft", "draft-history")
    comparison = workspace.compare_nodes("draft", "draft-history", "draft-current")
    artifact = workspace.download_node("draft", "draft-history")
    view["blocks"][0]["claim_refs"].append("tampered")

    assert view["historical"] is True
    assert comparison["left_id"] == "draft-history"
    assert "status" in comparison["changed_fields"]
    assert json.loads(artifact.content.decode("utf-8"))["node"]["draft_id"] == "draft-history"
    assert workspace.current_ids("draft") == ["draft-current"]
    assert workspace.snapshot() == before


def test_branch_from_here_then_explicit_activate_is_the_only_writable_transition() -> None:
    workspace = DraftWorkspace.from_records(**_history_records())
    before = workspace.snapshot()

    with pytest.raises(DraftHistoryError):
        workspace.replace_current(
            "draft",
            "draft-history",
            workspace.view_node("draft", "draft-history"),
        )
    assert workspace.snapshot() == before

    branched = workspace.branch_from_here(
        "draft",
        "draft-history",
        branch_id="draft-branch",
    )

    branch = branched.view_node("draft", "draft-branch")
    assert branch["branch_from_id"] == "draft-history"
    assert branch["historical"] is False
    assert branch["current"] is False
    assert branch["writable"] is False
    assert branched.current_ids("draft") == ["draft-current"]
    assert workspace.snapshot() == before

    activated = branched.activate_branch("draft", "draft-branch")
    assert activated.current_ids("draft") == ["draft-branch"]
    assert activated.view_node("draft", "draft-branch")["writable"] is True
    assert activated.view_node("draft", "draft-current")["historical"] is True

    updated = activated.replace_current(
        "draft",
        "draft-branch",
        {**activated.view_node("draft", "draft-branch"), "status": "EDITED"},
    )
    assert updated.view_node("draft", "draft-branch")["status"] == "EDITED"
    assert activated.view_node("draft", "draft-branch")["status"] == "HISTORICAL_DRAFT"
