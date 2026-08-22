from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from review_writer.product_foundation import VersionContext
from review_writer.product_foundation.project_root import version_context_root
from review_writer.project.source_truth import write_source_truth_bundle
from tests.product_use import test_prod006_source_to_release as prod006_fixture


PROJECT_ID = prod006_fixture.PROJECT_ID
STUDY_ID = prod006_fixture.STUDY_ID
EVIDENCE_ID = prod006_fixture.EVIDENCE_ID
SYNTHESIS_ID = prod006_fixture.SYNTHESIS_ID
SECTION_ID = prod006_fixture.SECTION_ID
REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "scripts" / "run_vertical_review.py"


def _json_request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    body = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if payload is not None
        else None
    )
    headers = (
        {
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        }
        if body is not None
        else {}
    )
    request = Request(f"{base_url}{path}", data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *arguments],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _payload(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    stream = result.stdout if result.returncode == 0 else result.stderr
    return json.loads(stream)


def _project_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file() and not path.is_symlink()
    }


def _prepare_registered_project(review_root: Path) -> Path:
    project = review_root / PROJECT_ID
    project.mkdir(parents=True, exist_ok=True)
    prod006_fixture._write_source_inputs(project)
    write_source_truth_bundle(project, STUDY_ID)
    prod006_fixture._approve_parse_quality(project, STUDY_ID)
    prod006_fixture._register_evidence(project)
    prod006_fixture._register_synthesis_and_contract(project)

    review_state = project / "00_brief/review_state.json"
    VersionContext.create(
        {
            "currentness": "current",
            "version_token": "generator-runtime-base",
            "artifact_refs": [
                {
                    "path": "00_brief/review_state.json",
                    "sha256": hashlib.sha256(review_state.read_bytes()).hexdigest(),
                }
            ],
        },
        project_id=PROJECT_ID,
        version_id="base-v1",
        branch_id="main",
        branch_name="Main",
        project_root=project,
    )
    return project


def test_generator_runtime_start_human_edit_continue_and_cold_resume() -> None:
    with tempfile.TemporaryDirectory(
        prefix="generator-runtime-product-use-"
    ) as temporary_root:
        review_root = Path(temporary_root)
        project = _prepare_registered_project(review_root)
        request = {
            "session_id": "generator-session-product-use",
            "section_id": SECTION_ID,
            "heading": "Reported result",
            "body": (
                f"[synthesis:{SYNTHESIS_ID}] The source reports a bounded outcome.\n\n"
                f"[evidence:{EVIDENCE_ID}]"
            ),
            "v2_addition": (
                f"[synthesis:{SYNTHESIS_ID}] The limitation remains explicit after review."
            ),
        }
        request_path = review_root / "generator-request.json"
        request_path.write_text(
            json.dumps(request, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        started = _run_cli(
            "generator-start",
            "--project",
            str(project),
            "--input",
            str(request_path),
        )
        assert started.returncode == 0, started.stderr
        start_payload = _payload(started)
        assert start_payload["status"] == "HUMAN_ACTION_REQUIRED"
        assert start_payload["candidate"]["version"] == "v1"
        assert start_payload["next_action"] == {
            "project_id": PROJECT_ID,
            "route": "/draft",
            "type": "HUMAN_ACTION_REQUIRED",
        }

        context_v1 = VersionContext.load(project)
        state_v1 = context_v1.state()
        node_v1 = context_v1.view_version(state_v1.current_version_id)
        runtime_v1 = node_v1.snapshot["generator_runtime"]
        assert runtime_v1["session_id"] == request["session_id"]
        assert runtime_v1["phase"] == "v1"
        assert runtime_v1["audit"]
        assert all(event["input_binding"] for event in runtime_v1["audit"])
        assert all(event["output_binding"] for event in runtime_v1["audit"])

        server, thread, base_url = prod006_fixture._start_dashboard(review_root)
        try:
            status, draft = _json_request(
                base_url,
                f"/api/project/{PROJECT_ID}/draft",
            )
            assert status == 200
            section = next(
                row for row in draft["sections"] if row["section_id"] == SECTION_ID
            )
            edited_body = section["body"].replace("reports", "records", 1)
            status, approved = _json_request(
                base_url,
                f"/api/project/{PROJECT_ID}/draft",
                method="PUT",
                payload={
                    "section_id": SECTION_ID,
                    "edited_body": edited_body,
                    "reason": "Human preserved the source-bound markers and edited the wording.",
                    "version_token": section["version_token"],
                    "actor_type": "simulated_researcher_agent",
                    "actor_label": "generator-runtime-human",
                },
            )
            assert status == 200, approved
            approved_section = next(
                row for row in approved["sections"] if row["section_id"] == SECTION_ID
            )
            assert approved_section["decision"]["action"] == "approve"
            assert approved_section["body"] == edited_body
        finally:
            prod006_fixture._stop_dashboard(server, thread)

        continued = _run_cli(
            "generator-continue",
            "--project",
            str(project),
            "--session-id",
            request["session_id"],
        )
        assert continued.returncode == 0, continued.stderr
        continue_payload = _payload(continued)
        assert continue_payload["status"] == "HUMAN_ACTION_REQUIRED"
        assert continue_payload["candidate"]["version"] == "v2"
        assert continue_payload["session_id"] == request["session_id"]

        context_v2 = VersionContext.load(project)
        state_v2 = context_v2.state()
        assert state_v2.current_version_id != state_v1.current_version_id
        assert context_v2.view_version(state_v1.current_version_id).read_only is True
        node_v2 = context_v2.view_version(state_v2.current_version_id)
        runtime_v2 = node_v2.snapshot["generator_runtime"]
        assert runtime_v2["phase"] == "v2"
        assert runtime_v2["human_decision"]["action"] == "approve"
        assert (
            runtime_v2["human_decision"]["edited_body_sha256"]
            == hashlib.sha256(edited_body.encode("utf-8")).hexdigest()
        )

        draft_path = project / "04_manuscript/section_drafts.jsonl"
        current_row = json.loads(draft_path.read_text(encoding="utf-8").splitlines()[0])
        assert current_row["body"].startswith(edited_body)
        assert request["v2_addition"] in current_row["body"]
        assert current_row["body"] != request["body"]

        resumed = _run_cli(
            "generator-continue",
            "--project",
            str(project),
            "--session-id",
            request["session_id"],
        )
        assert resumed.returncode == 0, resumed.stderr
        resume_payload = _payload(resumed)
        assert resume_payload["status"] == "HUMAN_ACTION_REQUIRED"
        assert resume_payload["write_mode"] == "NONE"
        assert resume_payload["current"]["version_id"] == state_v2.current_version_id
        assert (
            VersionContext.load(project).state().current_version_id
            == state_v2.current_version_id
        )


def test_generator_runtime_rejects_stale_and_invalid_requests_without_writes() -> None:
    with tempfile.TemporaryDirectory(
        prefix="generator-runtime-errors-"
    ) as temporary_root:
        review_root = Path(temporary_root)
        project = _prepare_registered_project(review_root)
        request = {
            "session_id": "generator-session-errors",
            "section_id": SECTION_ID,
            "heading": "Reported result",
            "body": f"[synthesis:{SYNTHESIS_ID}] [evidence:{EVIDENCE_ID}]",
            "v2_addition": f"[synthesis:{SYNTHESIS_ID}] Keep the limitation explicit.",
        }
        request_path = review_root / "generator-errors-request.json"
        request_path.write_text(json.dumps(request) + "\n", encoding="utf-8")
        before = _project_bytes(project)

        stale = _run_cli(
            "generator-start",
            "--project",
            str(project),
            "--input",
            str(request_path),
            "--expected-revision",
            "99",
            "--expected-head-id",
            "base-v1",
        )
        assert stale.returncode == 2
        assert _payload(stale) == {
            "command": "generator-start",
            "error_code": "GENERATOR_VERSION_CONFLICT",
            "status": "ERROR",
            "write_mode": "NONE",
        }
        assert _project_bytes(project) == before

        invalid_path = review_root / "generator-invalid-request.json"
        invalid_path.write_text(
            json.dumps({**request, "v2_addition": ""}) + "\n",
            encoding="utf-8",
        )
        invalid = _run_cli(
            "generator-start",
            "--project",
            str(project),
            "--input",
            str(invalid_path),
        )
        assert invalid.returncode == 2
        assert _payload(invalid) == {
            "command": "generator-start",
            "error_code": "V2_ADDITION_INVALID",
            "status": "ERROR",
            "write_mode": "NONE",
        }
        assert _project_bytes(project) == before


def test_generator_runtime_rejects_missing_or_corrupt_current_without_writes() -> None:
    for mutation in ("missing", "corrupt"):
        with tempfile.TemporaryDirectory(
            prefix=f"generator-runtime-current-{mutation}-"
        ) as temporary_root:
            review_root = Path(temporary_root)
            project = _prepare_registered_project(review_root)
            request = {
                "session_id": f"generator-session-{mutation}",
                "section_id": SECTION_ID,
                "heading": "Reported result",
                "body": f"[synthesis:{SYNTHESIS_ID}] [evidence:{EVIDENCE_ID}]",
                "v2_addition": f"[synthesis:{SYNTHESIS_ID}] Keep the limitation explicit.",
            }
            request_path = review_root / "generator-current-request.json"
            request_path.write_text(json.dumps(request) + "\n", encoding="utf-8")
            current_path = version_context_root(project) / "current.json"
            if mutation == "missing":
                current_path.unlink()
            else:
                current_path.write_bytes(b"not-json")
            before = _project_bytes(project)

            result = _run_cli(
                "generator-start",
                "--project",
                str(project),
                "--input",
                str(request_path),
            )
            assert result.returncode == 2
            assert _payload(result) == {
                "command": "generator-start",
                "error_code": "VERSION_CONTEXT_INVALID",
                "status": "ERROR",
                "write_mode": "NONE",
            }
            assert _project_bytes(project) == before
