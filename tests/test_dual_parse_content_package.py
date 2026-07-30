from __future__ import annotations

import json
from pathlib import Path

import pytest

from review_writer.project.content_agent_handoff import ContentAgentError, build_content_task_package
from review_writer.project.parse_reconciliation import write_parse_reconciliation
from review_writer.project.dual_source import write_dual_source_binding
from test_dual_source import dual_project
from test_parse_reconciliation import reconciliation_project


def paper_request(project: Path) -> dict[str, object]:
    return {
        "schema_version": "content-agent-request.v1",
        "request_kind": "paper_evidence",
        "project_id": project.name,
        "target_ids": ["scholarly-a"],
        "field_dependencies": ["smiles"],
        "reason": "Generate study-local candidate Evidence from current safe inputs.",
    }


def test_core_package_has_current_dual_safe_inputs_only(tmp_path: Path) -> None:
    project = reconciliation_project(tmp_path, conflict=False)
    write_parse_reconciliation(project, "scholarly-a")

    package = build_content_task_package(project, paper_request(project), tmp_path / "pkg")

    kinds = {row["kind"] for rows in package["inputs"].values() for row in rows}
    assert kinds == {
        "source_asset:pdf", "source_asset:canonical_markdown",
        "source_asset:content_list", "parse_quality_safe_projection",
        "chemical_paper_safe_projection", "reconciliation_safe_projection",
    }
    encoded = json.dumps(package).casefold()
    for forbidden in ("molblock", "archive_sha256", "source_pdf_sha256", "/home/"):
        assert forbidden not in encoded
    assert (tmp_path / "pkg/manifest.json").is_file()


def test_unresolved_core_gate_writes_no_package(tmp_path: Path) -> None:
    project = reconciliation_project(tmp_path)
    write_parse_reconciliation(project, "scholarly-a")
    destination = tmp_path / "pkg"

    with pytest.raises(ContentAgentError, match="PARSE_RECONCILIATION_UNRESOLVED"):
        build_content_task_package(project, paper_request(project), destination)

    assert not destination.exists()


def test_background_generic_only_package_is_valid_without_chemical_projection(
    tmp_path: Path,
) -> None:
    project = dual_project(tmp_path, tier="background", chemical=False)
    write_dual_source_binding(project, "scholarly-a")
    request = paper_request(project)
    request["field_dependencies"] = []

    package = build_content_task_package(project, request)

    assert {row["kind"] for rows in package["inputs"].values() for row in rows} == {
        "source_asset:pdf", "source_asset:canonical_markdown",
        "source_asset:content_list", "parse_quality_safe_projection",
    }
    assert "chemical_paper" not in package["inputs"]
    assert "reconciliation" not in package["inputs"]
