from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from review_writer.delivery.dual_parse_release import honest_progressive_release_projection
from review_writer.project.chemical_completion import (
    ChemicalCompletionError,
    apply_chemical_completion_batch,
    chemical_completion_state,
    require_honest_progressive_projection,
)
from review_writer.project.content_agent_handoff import (
    ContentAgentError,
    build_content_task_package,
    import_content_agent_result,
)
from review_writer.project.dual_source import write_dual_source_binding
from review_writer.project.paper_evidence import (
    PaperEvidenceError,
    apply_paper_evidence_decision,
    paper_evidence_state,
    register_paper_evidence_candidates,
)
from review_writer.project.parse_quality import write_parse_quality_gate
from review_writer.project.parse_reconciliation import write_parse_reconciliation
from review_writer.project.source_truth import canonical_digest, load_source_truth_bundle
from review_writer.project.synthesis import SynthesisError, register_synthesis_candidates
from test_chemical_completion import _large_completion_project
from test_content_agent_handoff import _project as content_agent_project
from test_parse_quality import _decide_all
from test_paper_evidence import _add_study_with_parse_action


def _snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }


def _incomplete_dual_project(tmp_path: Path) -> Path:
    project = _large_completion_project(tmp_path, candidate_count=210)
    write_parse_quality_gate(project, "scholarly-a")
    _decide_all(project)
    write_dual_source_binding(project, "scholarly-a")

    # Stage the current reconciliation registry so the RED run reaches the
    # downstream Chemical gate. The implementation must make this binding
    # use the honest-progressive projection itself.
    with patch(
        "review_writer.project.parse_reconciliation.require_chemical_completion_ready",
        lambda root, study_id: str(chemical_completion_state(root, study_id)["gate_digest"]),
    ):
        write_parse_reconciliation(project, "scholarly-a")
    return project


def _paper_request(project: Path, *, targets: list[str] | None = None) -> dict[str, object]:
    return {
        "schema_version": "content-agent-request.v1",
        "request_kind": "paper_evidence",
        "project_id": project.name,
        "target_ids": targets or ["scholarly-a"],
        "field_dependencies": ["smiles"],
        "reason": "Generate study-local candidate Evidence from current safe inputs.",
    }


def _candidate(project: Path, evidence_id: str = "EVIDENCE-PROGRESSIVE-001") -> dict[str, object]:
    bundle = load_source_truth_bundle(project, "scholarly-a")
    source_id = next(row["source_id"] for row in bundle["sources"] if row["document_role"] == "MAIN")
    return {
        "evidence_id": evidence_id,
        "source_id": source_id,
        "epistemic_type": "experimental_observation",
        "statement": "The reported intervention produced the measured outcome.",
        "locator": {
            "source_mode": "parsed_candidate",
            "page": 1,
            "section_or_item": "Results",
            "figure_or_table": None,
            "exact_quote": "The measured outcome was observed.",
        },
        "reported_conditions": ["Current PDF-bound condition"],
        "quantitative_results": ["Current PDF-bound result"],
        "limitations": ["Candidate requires researcher decision."],
        "mechanism_grade": "not_applicable",
        "risk_classes": ["MECHANISM_CAUSALITY"],
        "field_dependencies": ["smiles"],
    }


def _result(project: Path, package: dict[str, object]) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "content-agent-result.v1",
        "request_kind": package["request_kind"],
        "project_id": project.name,
        "target_ids": package["target_ids"],
        "task_package_digest": package["task_package_digest"],
        "agent_label": "content-agent-progressive-test",
        "content": {"evidence_candidates": [_candidate(project)]},
    }
    value["result_digest"] = canonical_digest(value)
    return value


def _decision(row: dict[str, object]) -> dict[str, object]:
    return {
        "evidence_id": row["evidence_id"],
        "candidate_digest": row["candidate_digest"],
        "bound_parse_object_digests": row["bound_parse_object_digests"],
        "source_pdf_sha256": row["source_pdf_sha256"],
        "action": "approve",
        "reason": "Checked against the cited original PDF.",
    }


def test_210_of_309_core_package_and_import_stay_candidate_only(tmp_path: Path) -> None:
    project = _incomplete_dual_project(tmp_path)
    gate = chemical_completion_state(project, "scholarly-a")

    assert gate["confirmed_count"] == 0
    assert gate["ai_provisional_count"] == 210
    assert gate["blocked_count"] == 99
    assert gate["coverage_denominator"] == 309
    assert gate["coverage_ratio"] == pytest.approx(210 / 309)
    assert gate["workflow_can_continue"] is False
    assert require_honest_progressive_projection(project, "scholarly-a") == gate["gate_digest"]

    package = build_content_task_package(project, _paper_request(project), tmp_path / "package")
    assert {"chemical_paper", "reconciliation"} <= set(package["inputs"])

    imported = import_content_agent_result(project, _result(project, package))

    assert imported["status"] == "imported"
    persisted = json.loads(
        (project / "01_evidence/scholarly-a/paper_evidence_candidates.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(persisted["candidates"]) == 1
    assert persisted["candidates"][0]["decision"] is None
    assert not (project / "01_evidence/paper_evidence_decisions.jsonl").exists()
    assert paper_evidence_state(project)["rows"][0]["status"] == "needs_review"


def test_incomplete_exact_evidence_decision_is_stale_and_zero_write(tmp_path: Path) -> None:
    project = _incomplete_dual_project(tmp_path)
    package = build_content_task_package(project, _paper_request(project))
    import_content_agent_result(project, _result(project, package))
    row = paper_evidence_state(project)["rows"][0]
    before = _snapshot(project)

    with pytest.raises(PaperEvidenceError, match="PAPER_EVIDENCE_STALE"):
        apply_paper_evidence_decision(project, _decision(row))

    assert _snapshot(project) == before
    assert not (project / "01_evidence/paper_evidence_decisions.jsonl").exists()


def test_honest_progressive_digest_stales_old_candidate_and_import_zero_writes(
    tmp_path: Path,
) -> None:
    project = _incomplete_dual_project(tmp_path)
    package = build_content_task_package(project, _paper_request(project))
    result = _result(project, package)
    import_content_agent_result(project, result)
    old_row = paper_evidence_state(project)["rows"][0]
    old_digest = old_row["dual_parse_bindings"]["honest_progressive_digest"]
    gate = chemical_completion_state(project, "scholarly-a")

    apply_chemical_completion_batch(
        project,
        "scholarly-a",
        {
            "version_token": gate["version_token"],
            "actor_type": "simulated_researcher_agent",
            "actor_label": "offline-ai",
            "corrections": [
                {
                    "molecule_index": 210,
                    "field": "resolved_smiles",
                    "value": "CO",
                    "resolution_status": "AI_PROVISIONAL",
                    "confidence": 0.82,
                    "provenance": {"kind": "ai_candidate", "source": "original_pdf"},
                    "reason": "The candidate is traceable to the original PDF.",
                    "pdf_locator": {"page": 1},
                }
            ],
        },
    )

    current_digest = require_honest_progressive_projection(project, "scholarly-a")
    assert current_digest != old_digest
    assert paper_evidence_state(project)["rows"][0]["status"] == "stale"

    before = _snapshot(project)
    with pytest.raises(ContentAgentError):
        import_content_agent_result(project, result)
    assert _snapshot(project) == before


def test_synthesis_candidate_registration_requires_80_percent_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _incomplete_dual_project(tmp_path)
    monkeypatch.setattr(
        "review_writer.project.synthesis.comparison_protocol_state",
        lambda _: {"workflow_can_continue": True, "protocol_digest": "a" * 64},
    )
    monkeypatch.setattr(
        "review_writer.project.synthesis.paper_evidence_state",
        lambda _: {
            "projection_digest": "b" * 64,
            "rows": [
                {
                    "evidence_id": "e1",
                    "study_id": "scholarly-a",
                    "status": "approved",
                    "field_dependencies": ["smiles"],
                }
            ],
        },
    )

    with pytest.raises(SynthesisError, match="CHEMICAL_COMPLETION_INCOMPLETE"):
        register_synthesis_candidates(
            project,
            {
                "synthesis_id": "s1",
                "proposition": "The reported result is limited to this study.",
                "comparison_axis": "yield",
                "supporting_evidence_ids": ["e1"],
                "applicability_boundary": "this study",
                "mechanism_evidence_grade": "low",
                "uncertainty": "high",
                "risk_class": "scope",
                "single_study": True,
            },
        )


def test_release_projection_remains_blocked_at_210_of_309() -> None:
    rows = [
        {
            "study_id": "scholarly-a",
            "molecule_id": f"molecule-{index}",
            "status": "AI_PROVISIONAL",
            "value": "CO",
            "source_id": "stud-a",
            "pdf_locator": {"page": 1},
            "confidence": 0.8,
            "provenance": {"source": "original_pdf"},
        }
        for index in range(210)
    ] + [
        {
            "study_id": "scholarly-a",
            "molecule_id": f"molecule-{index}",
            "status": "BLOCKED",
            "value": None,
            "source_id": "stud-a",
            "pdf_locator": {"page": 1},
            "gap_reason": "The original PDF does not uniquely support a structure.",
        }
        for index in range(210, 309)
    ]

    projection = honest_progressive_release_projection(rows)

    assert projection["coverage_ratio"] == pytest.approx(210 / 309)
    assert projection["coverage_sufficient"] is False
    assert projection["internal_release_ready"] is False
    assert "HONEST_PROGRESSIVE_COVERAGE_BELOW_THRESHOLD" in projection["hard_fails"]


def test_paper_evidence_request_rejects_multiple_studies_without_write(tmp_path: Path) -> None:
    project = content_agent_project(tmp_path)
    _add_study_with_parse_action(project, "scholarly-b", "approve_candidate_extraction")
    before = _snapshot(project)

    with pytest.raises(ContentAgentError, match="REQUEST_STUDY_LOCAL_REQUIRED"):
        build_content_task_package(
            project,
            _paper_request(project, targets=["scholarly-a", "scholarly-b"]),
            tmp_path / "rejected-package",
        )

    assert _snapshot(project) == before
    assert not (tmp_path / "rejected-package").exists()


def test_paper_evidence_result_rejects_multiple_studies_without_write(tmp_path: Path) -> None:
    project = content_agent_project(tmp_path)
    _add_study_with_parse_action(project, "scholarly-b", "approve_candidate_extraction")
    package = build_content_task_package(project, _paper_request(project))
    result = _result(project, package)
    result["target_ids"] = ["scholarly-a", "scholarly-b"]
    result["result_digest"] = canonical_digest(
        {key: value for key, value in result.items() if key != "result_digest"}
    )
    before = _snapshot(project)

    with pytest.raises(ContentAgentError, match="RESULT_STUDY_LOCAL_REQUIRED"):
        import_content_agent_result(project, result)

    assert _snapshot(project) == before
