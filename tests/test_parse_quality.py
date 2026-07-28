from __future__ import annotations

import json
from pathlib import Path

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
        state = apply_parse_quality_decision(
            project,
            "scholarly-a",
            {
                "object_id": row["object_id"],
                "gate_digest": state["gate_digest"],
                "object_digest": row["object_digest"],
                "action": action,
                "note": "Compared with the original PDF page.",
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


def test_unrelated_object_change_keeps_object_digests_local_but_stales_gate_decisions(
    tmp_path: Path,
) -> None:
    project = _parse_project(tmp_path)
    write_parse_quality_gate(project, "scholarly-a")
    approved = _decide_all(project)
    approved_digest = approved["gate_digest"]

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

    rebuilt = write_parse_quality_gate(project, "scholarly-a")

    assert rebuilt["status"] == "needs_review"
    assert rebuilt["gate_digest"] != approved_digest
    assert all(row["decision"] is None for row in rebuilt["objects"])


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
    for row in legacy["objects"]:
        row.pop("object_digest")
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
