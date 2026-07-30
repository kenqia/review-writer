from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest

from review_writer.project.parse_quality import (
    PARSE_OBJECT_KINDS,
    ParseQualityError,
    apply_parse_quality_decision,
    parse_quality_state,
    require_parse_quality_ready,
    write_parse_quality_gate,
)
from review_writer.project.source_truth import canonical_digest, write_source_truth_bundle
from test_source_truth import _source_truth_project, _write_json


def _parse_project(tmp_path: Path, *, incomplete_table: bool = False) -> Path:
    project = _source_truth_project(tmp_path)
    if incomplete_table:
        content_path = (
            project
            / "01_evidence/parses/extracted/10_1000_example/parse_content_list.json"
        )
        content = json.loads(content_path.read_text(encoding="utf-8"))
        content.append(
            {
                "type": "table",
                "page_idx": 0,
                "bbox": [1, 2, 3, 4],
                "table_body": "",
                "table_caption": ["Broken table"],
            }
        )
        _write_json(content_path, content)
    write_source_truth_bundle(project, "scholarly-a")
    return project


def _decide_all(
    project: Path,
    *,
    target_object_id: str | None = None,
    target_action: str = "approve_candidate_extraction",
) -> dict[str, object]:
    state = parse_quality_state(project, "scholarly-a")
    for row in state["objects"]:
        if row["status"] == "usable":
            continue
        action = target_action if row["object_id"] == target_object_id else (
            "pdf_locator_only"
            if row["status"] in {"incomplete", "failed"}
            else "approve_candidate_extraction"
        )
        pdf_resolution = (
            {
                "pages": [1],
                "source_scope": "The relevant content is readable on the original PDF page.",
                "limitations": "Parsed content is excluded from downstream use.",
            }
            if action == "pdf_locator_only"
            else None
        )
        state = apply_parse_quality_decision(
            project,
            "scholarly-a",
            {
                "object_id": row["object_id"],
                "gate_digest": state["gate_digest"],
                "object_digest": row["object_digest"],
                "action": action,
                "note": "Compared with the original PDF page.",
                **(
                    {"pdf_resolution": pdf_resolution}
                    if pdf_resolution is not None
                    else {}
                ),
            },
        )
    return state


@pytest.mark.parametrize(
    ("action", "workflow", "automatic"),
    (
        ("approve_candidate_extraction", True, True),
        ("pdf_locator_only", True, False),
        ("reparse_required", False, False),
    ),
)
def test_review_action_has_separate_workflow_and_extraction_projection(
    tmp_path: Path,
    action: str,
    workflow: bool,
    automatic: bool,
) -> None:
    project = _parse_project(tmp_path)
    gate = write_parse_quality_gate(project, "scholarly-a")
    target = next(row for row in gate["objects"] if row["status"] == "usable_with_review")

    updated = _decide_all(
        project,
        target_object_id=target["object_id"],
        target_action=action,
    )

    assert updated["workflow_can_continue"] is workflow
    assert updated["automatic_extraction_allowed"] is automatic


def test_gate_contains_all_required_object_kinds(tmp_path: Path) -> None:
    project = _parse_project(tmp_path)

    gate = write_parse_quality_gate(project, "scholarly-a")

    assert {row["kind"] for row in gate["objects"]} == set(PARSE_OBJECT_KINDS)
    assert gate["status"] == "needs_review"
    assert gate["workflow_can_continue"] is False
    assert gate["automatic_extraction_allowed"] is False
    assert all(len(row["object_digest"]) == 64 for row in gate["objects"])


def test_object_digest_is_stable_and_changes_only_with_its_assessment(
    tmp_path: Path,
) -> None:
    project = _parse_project(tmp_path)
    before = write_parse_quality_gate(project, "scholarly-a")

    content_path = (
        project
        / "01_evidence/parses/extracted/10_1000_example/parse_content_list.json"
    )
    content = json.loads(content_path.read_text(encoding="utf-8"))
    content.append(
        {
            "type": "table",
            "page_idx": 0,
            "bbox": [1, 2, 3, 4],
            "table_body": "condition | yield",
            "table_caption": ["Optimization"],
        }
    )
    _write_json(content_path, content)
    write_source_truth_bundle(project, "scholarly-a")

    after = write_parse_quality_gate(project, "scholarly-a")
    before_by_kind = {row["kind"]: row["object_digest"] for row in before["objects"]}
    after_by_kind = {row["kind"]: row["object_digest"] for row in after["objects"]}

    assert before_by_kind["table_structure"] != after_by_kind["table_structure"]
    assert {
        kind
        for kind in PARSE_OBJECT_KINDS
        if before_by_kind[kind] == after_by_kind[kind]
    } == set(PARSE_OBJECT_KINDS) - {"table_structure"}


def test_simulated_agent_decision_records_actor_without_impersonating_owner(
    tmp_path: Path,
) -> None:
    project = _parse_project(tmp_path)
    gate = write_parse_quality_gate(project, "scholarly-a")
    target = next(row for row in gate["objects"] if row["status"] == "usable_with_review")

    updated = apply_parse_quality_decision(
        project,
        "scholarly-a",
        {
            "object_id": target["object_id"],
            "object_digest": target["object_digest"],
            "gate_digest": gate["gate_digest"],
            "action": "approve_candidate_extraction",
            "note": "Compared the candidate with the original PDF.",
            "actor_type": "simulated_researcher_agent",
            "actor_label": "playwright-reviewer-round-1",
        },
    )
    saved = next(row for row in updated["objects"] if row["object_id"] == target["object_id"])

    assert saved["decision"]["actor_type"] == "simulated_researcher_agent"
    assert saved["decision"]["actor_label"] == "playwright-reviewer-round-1"
    assert saved["decision"]["bound_object_digest"] == target["object_digest"]
    assert "kenqia" not in json.dumps(saved["decision"]).casefold()


def test_pdf_locator_decision_requires_source_backed_resolution_without_partial_write(
    tmp_path: Path,
) -> None:
    project = _parse_project(tmp_path)
    gate = write_parse_quality_gate(project, "scholarly-a")
    target = next(
        row
        for row in gate["objects"]
        if row["kind"] == "figure_caption_links"
    )
    gate_path = project / "01_evidence/source_truth/scholarly-a/parse_quality.json"
    before = gate_path.read_bytes()

    with pytest.raises(ParseQualityError, match="PDF_RESOLUTION_REQUIRED"):
        apply_parse_quality_decision(
            project,
            "scholarly-a",
            {
                "object_id": target["object_id"],
                "object_digest": target["object_digest"],
                "gate_digest": gate["gate_digest"],
                "action": "pdf_locator_only",
                "note": "The parsed figure locator is not scientifically reliable.",
                "actor_type": "simulated_researcher_agent",
                "actor_label": "playwright-reviewer-round-2",
            },
        )

    assert gate_path.read_bytes() == before

    updated = apply_parse_quality_decision(
        project,
        "scholarly-a",
        {
            "object_id": target["object_id"],
            "object_digest": target["object_digest"],
            "gate_digest": gate["gate_digest"],
            "action": "pdf_locator_only",
            "note": "Use only the original PDF locator for this object.",
            "actor_type": "simulated_researcher_agent",
            "actor_label": "playwright-reviewer-round-2",
            "pdf_resolution": {
                "pages": [1],
                "source_scope": "Scheme 1 and its caption are readable on the original PDF page.",
                "limitations": "Parsed crops and parsed captions remain excluded from downstream use.",
            },
        },
    )
    saved = next(
        row for row in updated["objects"] if row["object_id"] == target["object_id"]
    )["decision"]
    bundle = json.loads(
        (project / "01_evidence/source_truth/scholarly-a/bundle.json").read_text(
            encoding="utf-8"
        )
    )
    expected_pdf_sha256 = next(
        source["pdf"]["sha256"]
        for source in bundle["sources"]
        if source["source_id"] == target["source_id"]
    )

    assert saved["pdf_resolution"] == {
        "pages": [1],
        "source_scope": "Scheme 1 and its caption are readable on the original PDF page.",
        "limitations": "Parsed crops and parsed captions remain excluded from downstream use.",
        "source_pdf_sha256": expected_pdf_sha256,
    }
    assert saved["actor_type"] == "simulated_researcher_agent"
    assert saved["decided_at"]


def test_pdf_resolution_with_wrong_source_binding_cannot_authorize_workflow(
    tmp_path: Path,
) -> None:
    project = _parse_project(tmp_path)
    gate = write_parse_quality_gate(project, "scholarly-a")
    target = next(
        row for row in gate["objects"] if row["kind"] == "figure_caption_links"
    )
    closed = _decide_all(
        project,
        target_object_id=target["object_id"],
        target_action="pdf_locator_only",
    )
    assert closed["workflow_can_continue"] is True
    gate_path = project / "01_evidence/source_truth/scholarly-a/parse_quality.json"
    stored = json.loads(gate_path.read_text(encoding="utf-8"))
    stored_target = next(
        row for row in stored["objects"] if row["object_id"] == target["object_id"]
    )
    stored_target["decision"]["pdf_resolution"]["source_pdf_sha256"] = "0" * 64
    _write_json(gate_path, stored)

    state = parse_quality_state(project, "scholarly-a")

    assert state["workflow_can_continue"] is False
    assert state["automatic_extraction_allowed"] is False


def test_concurrent_object_decisions_do_not_overwrite_each_other(tmp_path: Path) -> None:
    import review_writer.project.parse_quality as parse_quality_module

    project = _parse_project(tmp_path)
    gate = write_parse_quality_gate(project, "scholarly-a")
    targets = [row for row in gate["objects"] if row["status"] == "usable_with_review"]
    assert len(targets) >= 2
    original_atomic_json = parse_quality_module._atomic_json

    def delayed_atomic_json(path: Path, payload: object) -> None:
        time.sleep(0.05)
        original_atomic_json(path, payload)

    def decide(row: dict[str, object]) -> None:
        apply_parse_quality_decision(
            project,
            "scholarly-a",
            {
                "object_id": row["object_id"],
                "object_digest": row["object_digest"],
                "gate_digest": gate["gate_digest"],
                "action": "approve_candidate_extraction",
                "note": f"Checked {row['kind']} against the PDF.",
            },
        )

    with patch.object(parse_quality_module, "_atomic_json", side_effect=delayed_atomic_json):
        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(decide, targets[:2]))

    saved = parse_quality_state(project, "scholarly-a")
    decisions = {
        row["object_id"]
        for row in saved["objects"]
        if isinstance(row.get("decision"), dict)
    }
    assert decisions.issuperset(row["object_id"] for row in targets[:2])


def test_legacy_decision_without_object_digest_is_stale_not_upgraded(
    tmp_path: Path,
) -> None:
    project = _parse_project(tmp_path)
    write_parse_quality_gate(project, "scholarly-a")
    approved = _decide_all(project)
    target = next(row for row in approved["objects"] if isinstance(row["decision"], dict))
    gate_path = project / "01_evidence/source_truth/scholarly-a/parse_quality.json"
    stored = json.loads(gate_path.read_text(encoding="utf-8"))
    stored_target = next(row for row in stored["objects"] if row["object_id"] == target["object_id"])
    stored_target["decision"].pop("bound_object_digest")
    _write_json(gate_path, stored)

    state = parse_quality_state(project, "scholarly-a")
    stale_target = next(row for row in state["objects"] if row["object_id"] == target["object_id"])

    assert state["status"] == "needs_review"
    assert state["workflow_can_continue"] is False
    assert "bound_object_digest" not in stale_target["decision"]


def test_unattributed_decision_cannot_authorize_parse_quality(
    tmp_path: Path,
) -> None:
    project = _parse_project(tmp_path)
    write_parse_quality_gate(project, "scholarly-a")
    approved = _decide_all(project)
    target = next(row for row in approved["objects"] if isinstance(row["decision"], dict))
    gate_path = project / "01_evidence/source_truth/scholarly-a/parse_quality.json"
    stored = json.loads(gate_path.read_text(encoding="utf-8"))
    stored_target = next(row for row in stored["objects"] if row["object_id"] == target["object_id"])
    stored_target["decision"].pop("actor_type")
    stored_target["decision"].pop("actor_label")
    _write_json(gate_path, stored)

    state = parse_quality_state(project, "scholarly-a")

    assert state["status"] == "needs_review"
    assert state["workflow_can_continue"] is False


def test_explicit_actor_fields_must_be_valid_strings(tmp_path: Path) -> None:
    project = _parse_project(tmp_path)
    gate = write_parse_quality_gate(project, "scholarly-a")
    target = next(row for row in gate["objects"] if row["status"] == "usable_with_review")

    with pytest.raises(ParseQualityError, match="DECISION_INVALID"):
        apply_parse_quality_decision(
            project,
            "scholarly-a",
            {
                "object_id": target["object_id"],
                "object_digest": target["object_digest"],
                "gate_digest": gate["gate_digest"],
                "action": "approve_candidate_extraction",
                "note": "Compared with the original PDF.",
                "actor_type": "simulated_researcher_agent",
                "actor_label": "",
            },
        )


def test_reparse_rebuild_invalidates_only_requested_objects_and_preserves_history(
    tmp_path: Path,
) -> None:
    project = _parse_project(tmp_path)
    gate = write_parse_quality_gate(project, "scholarly-a")
    reviewable = [row for row in gate["objects"] if row["status"] == "usable_with_review"]
    assert len(reviewable) >= 2
    reparse_target = reviewable[0]
    state = _decide_all(
        project,
        target_object_id=reparse_target["object_id"],
        target_action="reparse_required",
    )
    before_by_id = {row["object_id"]: row for row in state["objects"]}
    prior_reparse = before_by_id[reparse_target["object_id"]]["decision"]
    stable_decisions = {
        object_id: row["decision"]
        for object_id, row in before_by_id.items()
        if object_id != reparse_target["object_id"] and isinstance(row["decision"], dict)
    }

    markdown = project / "01_evidence/mineru/markdown/10_1000_example.md"
    markdown.write_text("# Canonical\nBody after successful reparse\n", encoding="utf-8")
    write_source_truth_bundle(project, "scholarly-a")
    rebuilt = write_parse_quality_gate(project, "scholarly-a")
    rebuilt_by_id = {row["object_id"]: row for row in rebuilt["objects"]}
    affected = rebuilt_by_id[reparse_target["object_id"]]

    assert rebuilt["gate_digest"] != state["gate_digest"]
    assert {
        (row["object_id"], row["object_digest"]) for row in rebuilt["objects"]
    } == {
        (row["object_id"], row["object_digest"]) for row in state["objects"]
    }
    assert affected["decision"] is None
    assert affected["review_state"] == "needs_re_review"
    assert affected["re_review_reason"] == "reparse_completed"
    assert affected["prior_decisions"] == [prior_reparse]
    assert all(
        rebuilt_by_id[object_id]["decision"] == decision
        for object_id, decision in stable_decisions.items()
    )
    assert rebuilt["status"] == "needs_review"
    assert rebuilt["workflow_can_continue"] is False

    rereviewed = apply_parse_quality_decision(
        project,
        "scholarly-a",
        {
            "object_id": affected["object_id"],
            "object_digest": affected["object_digest"],
            "gate_digest": rebuilt["gate_digest"],
            "action": "approve_candidate_extraction",
            "note": "Rechecked the completed reparse against the original PDF.",
            "actor_type": "simulated_researcher_agent",
            "actor_label": "playwright-reviewer-round-2",
        },
    )
    rereviewed_object = next(
        row for row in rereviewed["objects"] if row["object_id"] == affected["object_id"]
    )

    assert rereviewed_object["decision"]["action"] == "approve_candidate_extraction"
    assert rereviewed_object["decision"]["actor_type"] == "simulated_researcher_agent"
    assert rereviewed_object["prior_decisions"] == [prior_reparse]
    assert rereviewed_object["review_state"] == "decided"
    assert rereviewed_object["re_review_reason"] is None
    assert rereviewed["workflow_can_continue"] is True

    revised = apply_parse_quality_decision(
        project,
        "scholarly-a",
        {
            "object_id": affected["object_id"],
            "object_digest": affected["object_digest"],
            "gate_digest": rereviewed["gate_digest"],
            "action": "pdf_locator_only",
            "note": "A second review narrowed this object to original-PDF location only.",
            "actor_type": "simulated_researcher_agent",
            "actor_label": "playwright-reviewer-round-2",
            "pdf_resolution": {
                "pages": [1],
                "source_scope": "The relevant content is readable on the original PDF page.",
                "limitations": "Parsed content is excluded from downstream use.",
            },
        },
    )
    revised_object = next(
        row for row in revised["objects"] if row["object_id"] == affected["object_id"]
    )
    assert revised_object["prior_decisions"] == [
        prior_reparse,
        rereviewed_object["decision"],
    ]
    assert revised_object["decision"]["action"] == "pdf_locator_only"


def test_changed_object_binding_fails_closed_without_invalidating_stable_objects(
    tmp_path: Path,
) -> None:
    project = _parse_project(tmp_path, incomplete_table=True)
    write_parse_quality_gate(project, "scholarly-a")
    reviewed = _decide_all(project)
    before_by_kind = {row["kind"]: row for row in reviewed["objects"]}
    prior_table_decision = before_by_kind["table_structure"]["decision"]

    content_path = (
        project
        / "01_evidence/parses/extracted/10_1000_example/parse_content_list.json"
    )
    content = json.loads(content_path.read_text(encoding="utf-8"))
    table = next(row for row in content if row.get("type") == "table")
    table["table_body"] = "condition | yield"
    _write_json(content_path, content)
    write_source_truth_bundle(project, "scholarly-a")
    rebuilt = write_parse_quality_gate(project, "scholarly-a")
    after_by_kind = {row["kind"]: row for row in rebuilt["objects"]}
    changed = after_by_kind["table_structure"]

    assert changed["object_id"] == before_by_kind["table_structure"]["object_id"]
    assert changed["object_digest"] != before_by_kind["table_structure"]["object_digest"]
    assert changed["decision"] is None
    assert changed["review_state"] == "needs_re_review"
    assert changed["re_review_reason"] == "object_changed"
    assert changed["prior_decisions"] == [prior_table_decision]
    assert all(
        after_by_kind[kind]["decision"] == before_by_kind[kind]["decision"]
        for kind in set(PARSE_OBJECT_KINDS) - {"table_structure"}
        if isinstance(before_by_kind[kind]["decision"], dict)
    )
    assert rebuilt["workflow_can_continue"] is False


def test_changed_object_that_now_looks_usable_still_requires_re_review(
    tmp_path: Path,
) -> None:
    project = _parse_project(tmp_path)
    write_parse_quality_gate(project, "scholarly-a")
    reviewed = _decide_all(project)
    previous = next(row for row in reviewed["objects"] if row["kind"] == "reference_boundary")
    assert previous["status"] == "usable_with_review"

    markdown = project / "01_evidence/mineru/markdown/10_1000_example.md"
    markdown.write_text(
        "# Canonical\nBody\n# References\n1. Synthetic reference.\n",
        encoding="utf-8",
    )
    write_source_truth_bundle(project, "scholarly-a")
    rebuilt = write_parse_quality_gate(project, "scholarly-a")
    changed = next(row for row in rebuilt["objects"] if row["kind"] == "reference_boundary")

    assert changed["status"] == "usable"
    assert changed["decision"] is None
    assert changed["prior_decisions"] == [previous["decision"]]
    assert changed["review_state"] == "needs_re_review"
    assert rebuilt["workflow_can_continue"] is False

    rereviewed = apply_parse_quality_decision(
        project,
        "scholarly-a",
        {
            "object_id": changed["object_id"],
            "object_digest": changed["object_digest"],
            "gate_digest": rebuilt["gate_digest"],
            "action": "approve_candidate_extraction",
            "note": "Rechecked the changed reference boundary against the original PDF.",
        },
    )
    assert rereviewed["workflow_can_continue"] is True


def test_decision_with_wrong_bound_gate_digest_cannot_authorize(
    tmp_path: Path,
) -> None:
    project = _parse_project(tmp_path)
    write_parse_quality_gate(project, "scholarly-a")
    approved = _decide_all(project)
    gate_path = project / "01_evidence/source_truth/scholarly-a/parse_quality.json"
    stored = json.loads(gate_path.read_text(encoding="utf-8"))
    target = next(row for row in stored["objects"] if isinstance(row["decision"], dict))
    target["decision"]["bound_gate_digest"] = "0" * 64
    _write_json(gate_path, stored)

    state = parse_quality_state(project, "scholarly-a")

    assert approved["workflow_can_continue"] is True
    assert state["status"] == "needs_review"
    assert state["workflow_can_continue"] is False


def test_persisted_illegal_action_status_pair_cannot_authorize(
    tmp_path: Path,
) -> None:
    project = _parse_project(tmp_path, incomplete_table=True)
    write_parse_quality_gate(project, "scholarly-a")
    reviewed = _decide_all(project)
    gate_path = project / "01_evidence/source_truth/scholarly-a/parse_quality.json"
    stored = json.loads(gate_path.read_text(encoding="utf-8"))
    target = next(row for row in stored["objects"] if row["status"] == "incomplete")
    target["decision"]["action"] = "approve_candidate_extraction"
    _write_json(gate_path, stored)

    state = parse_quality_state(project, "scholarly-a")

    assert reviewed["workflow_can_continue"] is True
    assert state["workflow_can_continue"] is False
    assert state["automatic_extraction_allowed"] is False


def test_rebuild_upgrades_legacy_gate_objects_without_reusing_old_decisions(
    tmp_path: Path,
) -> None:
    project = _parse_project(tmp_path)
    write_parse_quality_gate(project, "scholarly-a")
    approved = _decide_all(project)
    gate_path = project / "01_evidence/source_truth/scholarly-a/parse_quality.json"
    legacy = json.loads(gate_path.read_text(encoding="utf-8"))
    legacy.pop("prior_gate_digests")
    for row in legacy["objects"]:
        row.pop("object_digest")
        row.pop("prior_decisions")
        row.pop("review_state")
        row.pop("re_review_reason")
        if isinstance(row.get("decision"), dict):
            row["decision"] = {
                key: row["decision"][key]
                for key in ("action", "note", "decided_at", "bound_gate_digest")
            }
    legacy["gate_digest"] = canonical_digest(
        {
            "schema_version": legacy["schema_version"],
            "study_id": legacy["study_id"],
            "bundle_digest": legacy["bundle_digest"],
            "objects": [
                {key: value for key, value in row.items() if key != "decision"}
                for row in legacy["objects"]
            ],
        }
    )
    _write_json(gate_path, legacy)

    rebuilt = write_parse_quality_gate(project, "scholarly-a")

    assert all(len(row["object_digest"]) == 64 for row in rebuilt["objects"])
    assert all(row["decision"] is None for row in rebuilt["objects"])
    assert rebuilt["gate_digest"] == approved["gate_digest"]


def test_incomplete_object_cannot_be_approved_for_automatic_extraction(
    tmp_path: Path,
) -> None:
    project = _parse_project(tmp_path, incomplete_table=True)
    gate = write_parse_quality_gate(project, "scholarly-a")
    target = next(row for row in gate["objects"] if row["status"] == "incomplete")

    with pytest.raises(ParseQualityError, match="ACTION_NOT_ALLOWED"):
        apply_parse_quality_decision(
            project,
            "scholarly-a",
            {
                "object_id": target["object_id"],
                "gate_digest": gate["gate_digest"],
                "action": "approve_candidate_extraction",
                "note": "Not valid for incomplete content.",
            },
        )


def test_bundle_change_makes_decisions_stale(tmp_path: Path) -> None:
    project = _parse_project(tmp_path)
    write_parse_quality_gate(project, "scholarly-a")
    approved = _decide_all(project)
    assert approved["automatic_extraction_allowed"] is True

    markdown = project / "01_evidence/mineru/markdown/10_1000_example.md"
    markdown.write_text("# Canonical changed\nBody\n", encoding="utf-8")
    write_source_truth_bundle(project, "scholarly-a")

    state = parse_quality_state(project, "scholarly-a")
    assert state["status"] == "stale"
    assert state["workflow_can_continue"] is False
    assert state["automatic_extraction_allowed"] is False


def test_decisions_persist_and_ready_returns_current_gate_digest(tmp_path: Path) -> None:
    project = _parse_project(tmp_path)
    write_parse_quality_gate(project, "scholarly-a")
    approved = _decide_all(project)

    restored = parse_quality_state(project, "scholarly-a")

    assert restored == approved
    assert require_parse_quality_ready(project, "scholarly-a") == approved["gate_digest"]


def test_pdf_locator_only_never_allows_provider_packet(tmp_path: Path) -> None:
    project = _parse_project(tmp_path)
    gate = write_parse_quality_gate(project, "scholarly-a")
    target = next(row for row in gate["objects"] if row["status"] == "usable_with_review")
    state = _decide_all(
        project,
        target_object_id=target["object_id"],
        target_action="pdf_locator_only",
    )
    assert state["workflow_can_continue"] is True

    with pytest.raises(ParseQualityError, match="PARSE_PDF_LOCATOR_ONLY"):
        require_parse_quality_ready(project, "scholarly-a")
