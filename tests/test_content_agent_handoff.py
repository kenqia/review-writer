from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from review_writer.project.content_agent_handoff import (
    ContentAgentError,
    build_content_task_package,
    import_content_agent_result,
)
from review_writer.project.parse_quality import apply_parse_quality_decision, write_parse_quality_gate
from review_writer.project.source_truth import canonical_digest, write_source_truth_bundle
from test_source_truth import _source_truth_project


def _project(tmp_path: Path) -> Path:
    project = _source_truth_project(tmp_path)
    write_source_truth_bundle(project, "scholarly-a")
    gate = write_parse_quality_gate(project, "scholarly-a")
    for row in gate["objects"]:
        if row["status"] == "usable":
            continue
        gate = apply_parse_quality_decision(
            project,
            "scholarly-a",
            {
                "object_id": row["object_id"],
                "object_digest": row["object_digest"],
                "gate_digest": gate["gate_digest"],
                "action": "approve_candidate_extraction",
                "note": "Compared with the source PDF.",
            },
        )
    return project


def _request(project: Path, kind: str = "paper_evidence", targets: list[str] | None = None) -> dict:
    return {
        "schema_version": "content-agent-request.v1",
        "request_kind": kind,
        "project_id": project.name,
        "target_ids": targets or ["scholarly-a"],
        "reason": "Visible candidate content is missing or insufficient for review",
    }


def _candidate() -> dict:
    return {
        "evidence_id": "EVIDENCE-CONTENT-001",
        "source_id": "stud-a",
        "epistemic_type": "experimental_observation",
        "statement": "The reported intervention produced the measured outcome.",
        "locator": {
            "source_mode": "parsed_candidate",
            "page": 1,
            "section_or_item": "Results",
            "figure_or_table": None,
            "exact_quote": "The measured outcome was observed.",
        },
        "reported_conditions": ["Synthetic condition"],
        "quantitative_results": ["Synthetic result"],
        "limitations": ["Single-study observation"],
        "mechanism_grade": "not_applicable",
        "risk_classes": ["MECHANISM_CAUSALITY"],
    }


def _result(project: Path, package: dict, *, candidate: dict | None = None) -> dict:
    value = {
        "schema_version": "content-agent-result.v1",
        "request_kind": package["request_kind"],
        "project_id": project.name,
        "target_ids": package["target_ids"],
        "task_package_digest": package["task_package_digest"],
        "agent_label": "content-agent-test",
        "content": {"evidence_candidates": [candidate or _candidate()]},
    }
    value["result_digest"] = canonical_digest(value)
    return value


def _snapshot(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def test_content_task_package_contains_only_bound_project_artifacts(tmp_path: Path) -> None:
    project = _project(tmp_path)
    package = build_content_task_package(project, _request(project))

    assert package["project_id"] == project.name
    assert set(package["inputs"]) <= {
        "source_truth", "parse_quality", "paper_evidence", "comparison_protocol", "section_contract"
    }
    serialized = json.dumps(package, ensure_ascii=False).casefold()
    assert "auth" not in serialized
    assert "04_first_draft" not in serialized
    assert "prompt" not in serialized
    assert all(not str(item["path"]).startswith(("/", "\\")) for rows in package["inputs"].values() for item in rows)


def test_package_can_copy_only_hash_bound_inputs_to_task_directory(tmp_path: Path) -> None:
    project = _project(tmp_path)
    destination = tmp_path / "task-package"
    package = build_content_task_package(project, _request(project), destination)
    assert (destination / "manifest.json").is_file()
    for rows in package["inputs"].values():
        for item in rows:
            copied = destination / item["path"]
            assert copied.is_file()
            assert hashlib.sha256(copied.read_bytes()).hexdigest() == item["sha256"]


def test_import_rejects_unrequested_objects_without_project_change(tmp_path: Path) -> None:
    project = _project(tmp_path)
    package = build_content_task_package(project, _request(project))
    result = _result(project, package)
    result["content"]["evidence_candidates"][0]["study_id"] = "unrequested-study"
    result["result_digest"] = canonical_digest({k: v for k, v in result.items() if k != "result_digest"})
    before = _snapshot(project)
    with pytest.raises(ContentAgentError, match="RESULT_OUT_OF_SCOPE"):
        import_content_agent_result(project, result)
    assert _snapshot(project) == before


def test_import_rejects_content_agent_approval_without_project_change(tmp_path: Path) -> None:
    project = _project(tmp_path)
    package = build_content_task_package(project, _request(project))
    candidate = _candidate()
    candidate["decision"] = {"action": "approve"}
    result = _result(project, package, candidate=candidate)
    before = _snapshot(project)
    with pytest.raises(ContentAgentError, match="CONTENT_AGENT_CANNOT_APPROVE"):
        import_content_agent_result(project, result)
    assert _snapshot(project) == before


def test_import_is_hash_bound_and_writes_candidate_only(tmp_path: Path) -> None:
    project = _project(tmp_path)
    package = build_content_task_package(project, _request(project))
    imported = import_content_agent_result(project, _result(project, package))
    assert imported["status"] == "imported"
    candidate_path = project / "01_evidence/scholarly-a/paper_evidence_candidates.json"
    assert candidate_path.is_file()
    rows = json.loads(candidate_path.read_text(encoding="utf-8"))
    assert rows["candidates"][0]["decision"] is None


def test_import_rejects_stale_task_package_without_project_change(tmp_path: Path) -> None:
    project = _project(tmp_path)
    package = build_content_task_package(project, _request(project))
    result = _result(project, package)
    result["task_package_digest"] = "0" * 64
    result["result_digest"] = canonical_digest({k: v for k, v in result.items() if k != "result_digest"})
    before = _snapshot(project)
    with pytest.raises(ContentAgentError, match="TASK_PACKAGE_STALE"):
        import_content_agent_result(project, result)
    assert _snapshot(project) == before
