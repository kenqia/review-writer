from __future__ import annotations

import json
from pathlib import Path
import tempfile

import pytest

from review_writer.agent.local_pdf_parse import (
    LocalPdfParseError,
    register_pdf_only_evidence,
)
from review_writer.product_foundation import VersionContext
from review_writer.project.paper_evidence import (
    apply_paper_evidence_decision,
    paper_evidence_state,
)
from review_writer.project.paper_evidence_store import project_write_lock
from tests.product_use import test_public_e2e_chemical_import as chemical_flow
from tests.product_use import test_public_e2e_source_truth_parse as source_flow


def _seed_agent_parse(project: Path, session_id: str) -> None:
    context = VersionContext.load(project)
    state = context.state()
    current = context.view_version(state.current_version_id)
    with project_write_lock(project):
        context = VersionContext.load(project)
        state = context.state()
        current = context.view_version(state.current_version_id)
        context.publish_active_head(
            {
                **dict(current.snapshot),
                "agent_parse": {
                    "schema_version": "review-writer.agent-local-parse.v1",
                    "actor_type": "generator_agent",
                    "session_id": session_id,
                    "run_id": "run-pdf-only-gap-red",
                    "status": "HUMAN_ACTION_REQUIRED",
                    "reason_code": "PARSE_QUALITY_HUMAN_ACTION_REQUIRED",
                    "tool_trace": [],
                    "next_action": {"project_id": project.name, "route": "/review", "type": "HUMAN_ACTION_REQUIRED"},
                },
            },
            expected_head_id=state.active_head_id,
            expected_revision=state.revision,
            version_id="agent-parse-gap-red",
        )


def _candidate(source: dict[str, object]) -> dict[str, object]:
    return {
        "evidence_id": "agent-pdf-only-gap-evidence",
        "source_id": source["source_id"],
        "epistemic_type": "experimental_observation",
        "statement": "The source reports a bounded non-chemical observation.",
        "locator": {
            "source_mode": "parsed_candidate",
            "page": 1,
            "section_or_item": "Results",
            "figure_or_table": None,
            "exact_quote": "A source-bound parse record.",
        },
        "reported_conditions": [],
        "quantitative_results": ["one bounded reported observation"],
        "limitations": [
            "Chemical structure fields are unavailable from PDF-only input; dependent claims remain unsupported.",
        ],
        "mechanism_grade": "not_applicable",
        "risk_classes": ["AI_PROVISIONAL", "GAP", "NON_COMPARABLE"],
    }


def _snapshot(project: Path) -> dict[str, bytes]:
    return {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file() and not path.is_symlink()
    }


def _choose_pdf_locator_only(base_url: str, source: dict[str, object]) -> None:
    parse_path = f"/api/project/{chemical_flow.PROJECT_ID}/parse-quality"
    status, payload = source_flow._request_json(base_url, parse_path)
    assert status == 200
    assert isinstance(payload, dict)
    studies = payload.get("studies")
    assert isinstance(studies, list) and len(studies) == 1
    objects = studies[0].get("objects")
    assert isinstance(objects, list)
    parse_object = next(
        row for row in objects if "pdf_locator_only" in row.get("actions", [])
    )
    status, decided = source_flow._request_json(
        base_url,
        parse_path,
        method="PUT",
        payload={
            "study_id": source["study_id"],
            "object_id": parse_object["object_id"],
            "decision_token": parse_object["decision_token"],
            "action": "pdf_locator_only",
            "note": "Researcher restricted this source to original-PDF locators.",
            "pdf_resolution": {
                "pages": [1],
                "source_scope": "The verified MAIN PDF is the only allowed source.",
                "limitations": "Automatic extraction remains unavailable for this source.",
            },
        },
    )
    assert status == 200, decided
    assert isinstance(decided, dict)
    assert decided["workflow_can_continue"] is True


def test_agent_pdf_only_evidence_persists_gap_and_trace() -> None:
    with tempfile.TemporaryDirectory(prefix="agent-pdf-only-gap-") as temporary_root:
        review_root = Path(temporary_root)
        server, thread, base_url = source_flow._start_dashboard(review_root)
        try:
            source = chemical_flow._prepare_parse_ready_project(
                review_root, base_url, chemical_flow.PROJECT_ID
            )
            project = review_root / chemical_flow.PROJECT_ID
            session_id = "generator-pdf-only-gap"
            _seed_agent_parse(project, session_id)
            result = register_pdf_only_evidence(
                project,
                session_id=session_id,
                study_id=str(source["study_id"]),
                candidate=_candidate(source),
            )
            assert result["status"] == "HUMAN_ACTION_REQUIRED"
            row = result["evidence"]["candidates"][0]
            assert row["field_dependencies"] == []
            assert set(row["risk_classes"]) == {"AI_PROVISIONAL", "GAP", "NON_COMPARABLE"}
            assert result["agent_trace"]["tool"] == "register_paper_evidence_candidates"
            assert paper_evidence_state(project)["workflow_can_continue"] is False
            assert paper_evidence_state(project)["rows"][0]["status"] == "needs_review"
            approved = apply_paper_evidence_decision(
                project,
                {
                    "evidence_id": row["evidence_id"],
                    "candidate_digest": row["candidate_digest"],
                    "bound_parse_object_digests": row["bound_parse_object_digests"],
                    "source_pdf_sha256": row["source_pdf_sha256"],
                    "action": "approve",
                    "reason": "Researcher approved the bounded PDF-only observation with its Chemical GAP.",
                },
            )
            assert approved["status"] == "approved"
            state = paper_evidence_state(project)
            assert state["workflow_can_continue"] is True
            assert state["rows"][0]["field_dependencies"] == []
            assert "Chemical GAP:" in state["rows"][0]["limitations"][-1]
        finally:
            source_flow._stop_dashboard(server, thread)


def test_agent_pdf_only_evidence_routes_locator_only_to_manual_pdf_evidence() -> None:
    with tempfile.TemporaryDirectory(prefix="agent-pdf-only-manual-") as temporary_root:
        review_root = Path(temporary_root)
        server, thread, base_url = source_flow._start_dashboard(review_root)
        try:
            source = chemical_flow._prepare_parse_ready_project(
                review_root, base_url, chemical_flow.PROJECT_ID
            )
            project = review_root / chemical_flow.PROJECT_ID
            session_id = "generator-pdf-only-manual"
            _seed_agent_parse(project, session_id)
            _choose_pdf_locator_only(base_url, source)

            result = register_pdf_only_evidence(
                project,
                session_id=session_id,
                study_id=str(source["study_id"]),
                candidate=_candidate(source),
            )

            row = result["evidence"]["candidates"][0]
            assert row["locator"]["source_mode"] == "original_pdf_manual"
            assert row["bound_parse_object_digests"] == []
            assert row["source_pdf_sha256"] == source["digest"]
            assert result["agent_trace"]["tool"] == "register_manual_pdf_evidence"
        finally:
            source_flow._stop_dashboard(server, thread)


def test_agent_pdf_only_evidence_rejects_chemical_dependency_without_write() -> None:
    with tempfile.TemporaryDirectory(prefix="agent-pdf-only-gap-negative-") as temporary_root:
        review_root = Path(temporary_root)
        server, thread, base_url = source_flow._start_dashboard(review_root)
        try:
            source = chemical_flow._prepare_parse_ready_project(
                review_root, base_url, chemical_flow.PROJECT_ID
            )
            project = review_root / chemical_flow.PROJECT_ID
            session_id = "generator-pdf-only-gap-negative"
            _seed_agent_parse(project, session_id)
            before = _snapshot(project)
            payload = _candidate(source)
            payload["field_dependencies"] = ["smiles"]
            with pytest.raises(LocalPdfParseError) as error:
                register_pdf_only_evidence(
                    project,
                    session_id=session_id,
                    study_id=str(source["study_id"]),
                    candidate=payload,
                )
            assert error.value.code == "CHEMICAL_FIELDS_REQUIRE_IMPORT"
            after = _snapshot(project)
            assert after == before
        finally:
            source_flow._stop_dashboard(server, thread)


def test_agent_pdf_only_evidence_rejects_stale_version_without_write() -> None:
    with tempfile.TemporaryDirectory(prefix="agent-pdf-only-gap-conflict-") as temporary_root:
        review_root = Path(temporary_root)
        server, thread, base_url = source_flow._start_dashboard(review_root)
        try:
            source = chemical_flow._prepare_parse_ready_project(
                review_root, base_url, chemical_flow.PROJECT_ID
            )
            project = review_root / chemical_flow.PROJECT_ID
            session_id = "generator-pdf-only-gap-conflict"
            _seed_agent_parse(project, session_id)
            before = _snapshot(project)
            current = VersionContext.load(project).state()
            with pytest.raises(LocalPdfParseError) as error:
                register_pdf_only_evidence(
                    project,
                    session_id=session_id,
                    study_id=str(source["study_id"]),
                    candidate=_candidate(source),
                    expected_revision=current.revision - 1,
                    expected_head_id=current.active_head_id,
                )
            assert error.value.code == "GENERATOR_VERSION_CONFLICT"
            assert _snapshot(project) == before
        finally:
            source_flow._stop_dashboard(server, thread)
