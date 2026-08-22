from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from review_writer.product_foundation import VersionContext
from review_writer.product_foundation.project_root import version_context_root
from review_writer.project.paper_evidence import (
    PaperEvidenceError,
    paper_evidence_state,
    register_paper_evidence_candidates,
)
from tests.product_use import test_public_e2e_chemical_import as chemical_flow
from tests.product_use import test_public_e2e_source_truth_parse as source_flow
from tests.product_use import test_prod006_source_to_release as prod006_fixture


PROJECT_ID = chemical_flow.PROJECT_ID
EVIDENCE_ID = prod006_fixture.EVIDENCE_ID
REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "scripts" / "run_vertical_review.py"


def _request_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    status, body = source_flow._request_json(
        base_url,
        path,
        method=method,
        payload=payload,
    )
    assert isinstance(body, dict)
    return status, body


def _run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *arguments],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _payload(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    return json.loads(result.stdout if result.returncode == 0 else result.stderr)


def _project_bytes(project: Path) -> dict[str, bytes]:
    return {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in sorted(project.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file() and not path.is_symlink()
    }


def _candidate(source: dict[str, object]) -> dict[str, Any]:
    return {
        "evidence_id": EVIDENCE_ID,
        "source_id": source["source_id"],
        "epistemic_type": "experimental_observation",
        "statement": "The source reports a bounded chemical observation.",
        "locator": {
            "source_mode": "parsed_candidate",
            "page": 1,
            "section_or_item": "Synthetic source",
            "figure_or_table": None,
            "exact_quote": "A source-bound parse record.",
        },
        "reported_conditions": ["synthetic fixture conditions"],
        "quantitative_results": ["bounded source observation"],
        "limitations": ["Synthetic single-study fixture; no cross-study comparison."],
        "mechanism_grade": "not_applicable",
        "risk_classes": ["AI_PROVISIONAL", "GAP", "NON_COMPARABLE"],
    }


def _assert_registration_rejected(
    project: Path,
    study_id: str,
    payload: object,
    expected_code: str,
) -> None:
    try:
        register_paper_evidence_candidates(project, study_id, payload)
    except PaperEvidenceError as exc:
        assert exc.code == expected_code
    else:
        raise AssertionError(f"expected {expected_code}")


def test_public_chemical_evidence_decision_allows_agent_continuation_and_cold_restart() -> None:
    with tempfile.TemporaryDirectory(prefix="public-e2e-evidence-approval-") as temporary_root:
        review_root = Path(temporary_root)
        server, thread, base_url = source_flow._start_dashboard(review_root)
        try:
            source = chemical_flow._prepare_parse_ready_project(
                review_root, base_url, PROJECT_ID
            )
            chemical_flow._confirm_chemical_import(base_url, source)
            project = review_root / PROJECT_ID
            study_id = str(source["study_id"])

            registered = register_paper_evidence_candidates(
                project, study_id, _candidate(source)
            )
            candidate = registered["candidates"][0]
            assert candidate["dual_parse_bindings"] is not None
            before_unapproved = _project_bytes(project)

            _assert_registration_rejected(
                project,
                study_id,
                {"candidates": []},
                "PAPER_EVIDENCE_INVALID",
            )
            assert _project_bytes(project) == before_unapproved
            _assert_registration_rejected(
                project,
                study_id,
                {
                    **_candidate(source),
                    "evidence_id": "evidence-wrong-source",
                    "source_id": "source-not-canonical",
                },
                "SOURCE_ID_NOT_FOUND",
            )
            assert _project_bytes(project) == before_unapproved
            _assert_registration_rejected(
                project,
                study_id,
                {"candidates": [_candidate(source), _candidate(source)]},
                "EVIDENCE_ID_DUPLICATE",
            )
            assert _project_bytes(project) == before_unapproved

            status, initial = _request_json(
                base_url, f"/api/project/{PROJECT_ID}/paper-evidence"
            )
            assert status == 200
            assert initial["reason"] == "PAPER_EVIDENCE_REVIEW_REQUIRED"
            assert initial["workflow_can_continue"] is False
            item = initial["items"][0]
            assert item["evidence_id"] == EVIDENCE_ID
            assert item["source_id"] == source["source_id"]
            assert item["locator"]["page"] == 1
            descriptor = initial["source_pdf_descriptors"]["items"][0]
            assert descriptor["role"] == "MAIN"
            assert descriptor["currentness"] == "current"
            current_evidence = paper_evidence_state(project)["rows"][0]
            assert item["version_token"] == source_flow.dashboard._workspace_token(
                "paper-evidence",
                EVIDENCE_ID,
                current_evidence["candidate_digest"],
            )

            response_started = time.monotonic()
            rejected_status, rejected = _request_json(
                base_url,
                f"/api/project/{PROJECT_ID}/paper-evidence",
                method="PUT",
                payload={
                    "evidence_id": EVIDENCE_ID,
                    "action": "reject",
                    "reason": "Human rejects the bound source evidence.",
                    "version_token": item["version_token"],
                    "actor_type": "human_researcher",
                    "actor_label": "public-evidence-reviewer",
                },
            )
            assert time.monotonic() - response_started < 2
            assert rejected_status == 200, rejected
            assert rejected["workflow_can_continue"] is False
            assert rejected["reason"] == "PAPER_EVIDENCE_APPROVED_ROW_MISSING"
            assert rejected["items"][0]["status"] == "rejected"
            assert rejected["items"][0]["decision"]["action"] == "reject"
            after_reject = _project_bytes(project)

            request = {
                "session_id": "generator-public-evidence-approval",
                "section_id": prod006_fixture.SECTION_ID,
                "heading": "Bounded chemical finding",
                "body": (
                    f"[synthesis:{prod006_fixture.SYNTHESIS_ID}] "
                    "The source reports a bounded outcome.\n\n"
                    f"[evidence:{EVIDENCE_ID}]"
                ),
                "v2_addition": (
                    f"[synthesis:{prod006_fixture.SYNTHESIS_ID}] "
                    "The limitation remains explicit after review."
                ),
            }
            request_path = review_root / "generator-request.json"
            request_path.write_text(json.dumps(request) + "\n", encoding="utf-8")
            blocked = _run_cli(
                "generator-start", "--project", str(project), "--input", str(request_path)
            )
            assert blocked.returncode == 2
            assert _payload(blocked) == {
                "command": "generator-start",
                "error_code": "GENERATOR_TOOL_FAILED",
                "status": "ERROR",
                "tool_error_code": "PAPER_EVIDENCE_NOT_APPROVED",
                "write_mode": "NONE",
            }
            assert _project_bytes(project) == after_reject
            assert not (project / "05_release").exists()

            source_flow._stop_dashboard(server, thread)
            server, thread, base_url = source_flow._start_dashboard(review_root)
            cold_rejected_status, cold_rejected = _request_json(
                base_url, f"/api/project/{PROJECT_ID}/paper-evidence"
            )
            assert cold_rejected_status == 200
            assert cold_rejected["workflow_can_continue"] is False
            assert cold_rejected["reason"] == "PAPER_EVIDENCE_APPROVED_ROW_MISSING"
            assert cold_rejected["items"][0]["status"] == "rejected"
            assert cold_rejected["items"][0]["decision"]["action"] == "reject"
            item = cold_rejected["items"][0]
            assert item["version_token"] == source_flow.dashboard._workspace_token(
                "paper-evidence",
                EVIDENCE_ID,
                paper_evidence_state(project)["rows"][0]["candidate_digest"],
            )

            stale_status, _ = _request_json(
                base_url,
                f"/api/project/{PROJECT_ID}/paper-evidence",
                method="PUT",
                payload={
                    "evidence_id": EVIDENCE_ID,
                    "action": "approve",
                    "reason": "Stale decision must not write.",
                    "version_token": "stale-" + item["version_token"],
                    "actor_type": "human_researcher",
                    "actor_label": "public-evidence-reviewer",
                },
            )
            assert stale_status == 409
            assert _project_bytes(project) == after_reject
            assert item["version_token"] == source_flow.dashboard._workspace_token(
                "paper-evidence",
                EVIDENCE_ID,
                paper_evidence_state(project)["rows"][0]["candidate_digest"],
            )

            approved_status, approved = _request_json(
                base_url,
                f"/api/project/{PROJECT_ID}/paper-evidence",
                method="PUT",
                payload={
                    "evidence_id": EVIDENCE_ID,
                    "action": "approve",
                    "reason": "Human reviewed the bound source evidence.",
                    "version_token": item["version_token"],
                    "actor_type": "human_researcher",
                    "actor_label": "public-evidence-reviewer",
                },
            )
            assert approved_status == 200, approved
            assert approved["workflow_can_continue"] is True
            assert approved["items"][0]["decision"]["action"] == "approve"
            prod006_fixture._register_synthesis_and_contract(project)
            old_context = VersionContext.load(project)
            old_state = old_context.state()
            old_current_id = old_state.current_version_id

            started = _run_cli(
                "generator-start", "--project", str(project), "--input", str(request_path)
            )
            assert started.returncode == 0, started.stderr
            start_payload = _payload(started)
            assert start_payload["status"] == "HUMAN_ACTION_REQUIRED"
            assert start_payload["candidate"]["version"] == "v1"
            assert start_payload["current"]["version_id"] != old_current_id
            assert VersionContext.load(project).view_version(old_current_id).read_only is True

            status, draft = _request_json(base_url, f"/api/project/{PROJECT_ID}/draft")
            assert status == 200
            section = next(
                row
                for row in draft["sections"]
                if row["section_id"] == prod006_fixture.SECTION_ID
            )
            edited_body = section["body"].replace("reports", "records", 1)
            status, after_edit = _request_json(
                base_url,
                f"/api/project/{PROJECT_ID}/draft",
                method="PUT",
                payload={
                    "section_id": prod006_fixture.SECTION_ID,
                    "edited_body": edited_body,
                    "reason": "Human preserved the source-bound markers and edited the wording.",
                    "version_token": section["version_token"],
                    "actor_type": "human_researcher",
                    "actor_label": "public-draft-reviewer",
                },
            )
            assert status == 200, after_edit

            continued = _run_cli(
                "generator-continue",
                "--project",
                str(project),
                "--session-id",
                request["session_id"],
            )
            assert continued.returncode == 0, continued.stderr
            continued_payload = _payload(continued)
            assert continued_payload["status"] == "HUMAN_ACTION_REQUIRED"
            assert continued_payload["candidate"]["version"] == "v2"
            draft_row = json.loads(
                (project / "04_manuscript/section_drafts.jsonl")
                .read_text(encoding="utf-8")
                .strip()
            )
            assert draft_row["body"].startswith(edited_body)
            assert request["v2_addition"] in draft_row["body"]
            evidence_digest = paper_evidence_state(project)["projection_digest"]
            current_after_continuation = VersionContext.load(project).view_version(
                VersionContext.load(project).state().current_version_id
            )
        finally:
            source_flow._stop_dashboard(server, thread)

        cold_server, cold_thread, cold_base_url = source_flow._start_dashboard(review_root)
        try:
            status, cold = _request_json(
                cold_base_url, f"/api/project/{PROJECT_ID}/paper-evidence"
            )
            assert status == 200
            assert cold["workflow_can_continue"] is True
            assert cold["items"][0]["decision"]["action"] == "approve"
            assert paper_evidence_state(project)["projection_digest"] == evidence_digest
            cold_context = VersionContext.load(project)
            cold_state = cold_context.state()
            cold_current = cold_context.view_version(cold_state.current_version_id)
            assert cold_current.version_id == current_after_continuation.version_id
            assert cold_current.snapshot_digest == current_after_continuation.snapshot_digest
            current_path = version_context_root(project) / "current.json"
            current_before_resume = current_path.read_bytes()
            resume_status, resumed = _request_json(
                cold_base_url,
                f"/api/project/{PROJECT_ID}/resume",
                method="POST",
                payload={
                    "expected_revision": cold_state.revision,
                    "node_digest": cold_current.snapshot_digest,
                    "version_token": cold_current.snapshot["version_token"],
                },
            )
            assert resume_status == 200, resumed
            assert resumed["result"] == "RESUMED"
            assert resumed["write_mode"] == "NONE"
            assert resumed["version"]["version_id"] == cold_current.version_id
            assert resumed["revision"] == cold_state.revision
            assert current_path.read_bytes() == current_before_resume
        finally:
            source_flow._stop_dashboard(cold_server, cold_thread)
