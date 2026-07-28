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
from review_writer.project.source_truth import write_source_truth_bundle
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
