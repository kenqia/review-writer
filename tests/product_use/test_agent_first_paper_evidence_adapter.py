from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from review_writer.project.source_truth import write_source_truth_bundle
from tests.product_use import test_prod006_source_to_release as prod006_fixture


REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "scripts" / "run_vertical_review.py"
PROJECT_ID = prod006_fixture.PROJECT_ID
STUDY_ID = prod006_fixture.STUDY_ID
SOURCE_ID = prod006_fixture.SOURCE_ID
EVIDENCE_ID = "evidence-agent-first-cli"


def _candidate(
    *,
    evidence_id: str = EVIDENCE_ID,
    source_id: str = SOURCE_ID,
    statement: str = "The synthetic source supports the bounded agent candidate.",
) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "source_id": source_id,
        "epistemic_type": "experimental_observation",
        "statement": statement,
        "locator": {
            "source_mode": "parsed_candidate",
            "page": 1,
            "section_or_item": "Results",
            "figure_or_table": None,
            "exact_quote": "The tiny source reports a bounded conversion result.",
        },
        "reported_conditions": ["synthetic fixture conditions"],
        "quantitative_results": ["bounded synthetic result"],
        "limitations": ["Synthetic single-study fixture; no cross-study comparison."],
        "mechanism_grade": "not_applicable",
        "risk_classes": ["AI_PROVISIONAL", "GAP", "NON_COMPARABLE"],
    }


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _build_project(review_root: Path) -> Path:
    project = review_root / PROJECT_ID
    project.mkdir(parents=True, exist_ok=True)
    prod006_fixture._write_source_inputs(project)
    write_source_truth_bundle(project, STUDY_ID)
    prod006_fixture._approve_parse_quality(project, STUDY_ID)
    return project


def _run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *arguments],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )


def _json_output(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    stream = result.stdout if result.returncode == 0 else result.stderr
    return json.loads(stream)


def _assert_cli_success(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    assert result.returncode == 0, (
        f"CLI failed with exit {result.returncode}: "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    return _json_output(result)


def _snapshot_tree(root: Path) -> dict[str, bytes | None]:
    snapshot: dict[str, bytes | None] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_file():
            snapshot[path.relative_to(root).as_posix()] = path.read_bytes()
        elif path.is_dir():
            snapshot[path.relative_to(root).as_posix()] = None
    return snapshot


def _json_request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {} if body is None else {"Content-Type": "application/json"}
    request = Request(f"{base_url}{path}", data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_agent_cli_registers_reads_dashboard_decision_and_survives_cold_restart() -> None:
    with tempfile.TemporaryDirectory(prefix="agent-first-paper-evidence-") as temporary_root:
        review_root = Path(temporary_root)
        project = _build_project(review_root)
        candidate_input = review_root / "candidate.json"
        _write_json(candidate_input, {"candidates": [_candidate()]})

        registered = _assert_cli_success(
            _run_cli(
                "register-paper-evidence",
                "--project",
                str(project),
                "--study-id",
                STUDY_ID,
                "--input",
                str(candidate_input),
            )
        )
        assert registered == {
            "candidate_count": 1,
            "reason_code": "PAPER_EVIDENCE_REGISTERED",
            "status": "NEEDS_REVIEW",
        }

        before_state_tree = _snapshot_tree(project)
        before_review = _assert_cli_success(
            _run_cli("paper-evidence-state", "--project", str(project))
        )
        assert _snapshot_tree(project) == before_state_tree
        assert before_review["command"] == "paper-evidence-state"
        assert before_review["reason_code"] == "PAPER_EVIDENCE_REVIEW_REQUIRED"
        assert before_review["workflow_can_continue"] is False
        assert before_review["rows"][0]["status"] == "needs_review"

        server, thread, base_url = prod006_fixture._start_dashboard(review_root)
        try:
            status, dashboard_state = _json_request(
                base_url,
                f"/api/project/{PROJECT_ID}/paper-evidence",
            )
            assert status == 200
            item = dashboard_state["items"][0]
            assert item["evidence_id"] == EVIDENCE_ID
            assert item["status"] == "needs_review"

            status, after_decision = _json_request(
                base_url,
                f"/api/project/{PROJECT_ID}/paper-evidence",
                method="PUT",
                payload={
                    "evidence_id": EVIDENCE_ID,
                    "action": "approve",
                    "reason": "Human reviewed the source-bound candidate.",
                    "version_token": item["version_token"],
                    "actor_type": "human_researcher",
                    "actor_label": "agent-first-human-review",
                },
            )
            assert status == 200
            assert after_decision["items"][0]["status"] == "approved"
        finally:
            prod006_fixture._stop_dashboard(server, thread)

        resumed_state_tree = _snapshot_tree(project)
        resumed = _assert_cli_success(
            _run_cli("paper-evidence-state", "--project", str(project))
        )
        assert _snapshot_tree(project) == resumed_state_tree
        assert resumed["reason_code"] == "PAPER_EVIDENCE_READY"
        assert resumed["workflow_can_continue"] is True
        assert resumed["rows"][0]["status"] == "approved"
        assert resumed["rows"][0]["decision"]["action"] == "approve"

        cold_restart = _assert_cli_success(
            _run_cli("paper-evidence-state", "--project", str(project))
        )
        assert _snapshot_tree(project) == resumed_state_tree
        assert cold_restart["projection_digest"] == resumed["projection_digest"]
        assert cold_restart["rows"] == resumed["rows"]
        assert not (project / "05_release").exists()


def test_agent_cli_rejects_invalid_stale_wrong_source_and_duplicate_without_writes() -> None:
    cases = (
        ("invalid", {"candidates": []}, "PAPER_EVIDENCE_INVALID"),
        (
            "stale",
            {"candidates": [{**_candidate(), "source_pdf_sha256": "0" * 64}]},
            "SOURCE_PDF_STALE",
        ),
        (
            "wrong-source",
            {"candidates": [_candidate(source_id="source-not-canonical")]},
            "SOURCE_ID_NOT_FOUND",
        ),
        (
            "duplicate",
            {"candidates": [_candidate(), _candidate()]},
            "EVIDENCE_ID_DUPLICATE",
        ),
    )
    with tempfile.TemporaryDirectory(prefix="agent-first-paper-evidence-errors-") as temporary_root:
        review_root = Path(temporary_root)
        project = _build_project(review_root)
        valid_input = review_root / "valid.json"
        _write_json(valid_input, {"candidates": [_candidate()]})
        _assert_cli_success(
            _run_cli(
                "register-paper-evidence",
                "--project",
                str(project),
                "--study-id",
                STUDY_ID,
                "--input",
                str(valid_input),
            )
        )
        baseline = _snapshot_tree(project)

        for name, payload, expected_code in cases:
            input_path = review_root / f"{name}.json"
            _write_json(input_path, payload)
            result = _run_cli(
                "register-paper-evidence",
                "--project",
                str(project),
                "--study-id",
                STUDY_ID,
                "--input",
                str(input_path),
            )
            assert result.returncode == 2
            assert _json_output(result) == {
                "error_code": expected_code,
                "status": "ERROR",
            }
            assert _snapshot_tree(project) == baseline, name
