from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from review_writer.project.paper_evidence import (
    paper_evidence_state,
    register_paper_evidence_candidates,
)
from review_writer.project.source_truth import (
    load_source_truth_bundle,
    write_source_truth_bundle,
)
from tests.product_use import test_prod006_source_to_release as prod006_fixture


PROJECT_ID = prod006_fixture.PROJECT_ID
STUDY_ID = prod006_fixture.STUDY_ID
SOURCE_ID = prod006_fixture.SOURCE_ID
EVIDENCE_INCLUDE_ID = "evidence-res001-include"
EVIDENCE_EXCLUDE_ID = "evidence-res001-exclude"
RISK_CLASSES = {"AI_PROVISIONAL", "GAP", "NON_COMPARABLE"}


def _json_request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    body = None
    headers: dict[str, str] = {}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        }
    request = Request(f"{base_url}{path}", data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raw = exc.read()
        try:
            value: Any = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            value = {"raw": raw.decode("utf-8", errors="replace")}
        return exc.code, value


def _candidate(evidence_id: str, statement: str) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "source_id": SOURCE_ID,
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
        "risk_classes": sorted(RISK_CLASSES),
    }


def _build_project(review_root: Path) -> tuple[Path, dict[str, dict[str, Any]]]:
    """Construct only synthetic upstream source-bound candidates in /tmp."""
    project = review_root / PROJECT_ID
    project.mkdir(parents=True, exist_ok=True)
    prod006_fixture._write_source_inputs(project)
    write_source_truth_bundle(project, STUDY_ID)
    prod006_fixture._approve_parse_quality(project, STUDY_ID)
    registered = register_paper_evidence_candidates(
        project,
        STUDY_ID,
        {
            "candidates": [
                _candidate(
                    EVIDENCE_INCLUDE_ID,
                    "The synthetic source supports the bounded include candidate.",
                ),
                _candidate(
                    EVIDENCE_EXCLUDE_ID,
                    "The synthetic source records the bounded exclude candidate.",
                ),
            ]
        },
    )
    candidates = {
        row["evidence_id"]: row
        for row in registered["candidates"]
        if isinstance(row, dict)
    }
    assert set(candidates) == {EVIDENCE_INCLUDE_ID, EVIDENCE_EXCLUDE_ID}
    return project, candidates


def _paper_evidence_path() -> str:
    return f"/api/project/{PROJECT_ID}/paper-evidence"


def _items(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    assert payload["route"] == "evidence-to-release.v1"
    return {
        row["evidence_id"]: row
        for row in payload["items"]
        if isinstance(row, dict)
    }


def _snapshot_tree(root: Path) -> dict[str, tuple[str, object]]:
    snapshot: dict[str, tuple[str, object]] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            snapshot[relative] = ("symlink", os.readlink(path))
        elif path.is_file():
            snapshot[relative] = ("file", path.read_bytes())
        elif path.is_dir():
            snapshot[relative] = ("directory", None)
    return snapshot


def _decision_projection_source_bytes(project: Path) -> dict[str, bytes | None]:
    source_truth = load_source_truth_bundle(project, STUDY_ID)
    sources = [row for row in source_truth["sources"] if isinstance(row, dict)]
    assert [row["document_role"] for row in sources] == ["MAIN"]
    paths = (
        project / "01_evidence/paper_evidence_decisions.jsonl",
        project / "01_evidence/paper_evidence_projection.jsonl",
        project / sources[0]["pdf"]["path"],
    )
    return {
        path.relative_to(project).as_posix(): path.read_bytes() if path.is_file() else None
        for path in paths
    }


def _authority_snapshot(project: Path) -> dict[str, Any]:
    state = paper_evidence_state(project)
    rows = {
        row["evidence_id"]: row
        for row in state["rows"]
        if isinstance(row, dict)
    }
    source_truth = load_source_truth_bundle(project, STUDY_ID)
    sources = [row for row in source_truth["sources"] if isinstance(row, dict)]
    assert [row["document_role"] for row in sources] == ["MAIN"]
    assert len(sources) == 1
    source_pdf = project / sources[0]["pdf"]["path"]
    source_pdf_digest = hashlib.sha256(source_pdf.read_bytes()).hexdigest()
    return {
        "source_role": tuple(row["document_role"] for row in sources),
        "source_pdf_bytes": source_pdf.read_bytes(),
        "source_pdf_sha256": source_pdf_digest,
        "rows": {
            evidence_id: {
                "candidate_digest": row["candidate_digest"],
                "source_pdf_sha256": row["source_pdf_sha256"],
                "bound_parse_object_digests": tuple(row["bound_parse_object_digests"]),
                "status": row["status"],
                "decision": row["decision"],
            }
            for evidence_id, row in sorted(rows.items())
        },
    }


def _assert_no_promotion(project: Path, payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    assert payload.get("promotion", "NONE") == "NONE"
    assert "PROMOTE" not in serialized
    assert '"B2"' not in serialized
    assert not (project / "05_release").exists()


def test_res001_paper_evidence_dashboard_slice_is_source_bound_and_restart_stable() -> None:
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="res001-paper-evidence-") as temporary_root:
        project, candidates = _build_project(Path(temporary_root))
        server, thread, base_url = prod006_fixture._start_dashboard(Path(temporary_root))
        try:
            status, initial = _json_request(base_url, _paper_evidence_path())
            assert status == 200
            initial_items = _items(initial)
            assert set(initial_items) == {EVIDENCE_INCLUDE_ID, EVIDENCE_EXCLUDE_ID}
            for evidence_id, item in initial_items.items():
                assert item["source_id"] == SOURCE_ID
                assert set(item["risk_classes"]) == RISK_CLASSES
                assert item["status"] == "needs_review"
                assert isinstance(item["version_token"], str) and item["version_token"]
                if "source_role" not in item:
                    assert _authority_snapshot(project)["source_role"] == ("MAIN",)
                else:
                    assert item["source_role"] == "MAIN"
                assert candidates[evidence_id]["candidate_digest"]
                assert candidates[evidence_id]["source_pdf_sha256"]
                assert candidates[evidence_id]["bound_parse_object_digests"]

            current_status, current_before_blank = _json_request(
                base_url, _paper_evidence_path()
            )
            assert current_status == 200
            current_items_before_blank = _items(current_before_blank)
            assert (
                current_items_before_blank[EVIDENCE_INCLUDE_ID]["version_token"]
                == initial_items[EVIDENCE_INCLUDE_ID]["version_token"]
            )
            before_rejected_requests = _snapshot_tree(project)
            before_rejected_evidence_bytes = _decision_projection_source_bytes(project)
            blank_status, _ = _json_request(
                base_url,
                _paper_evidence_path(),
                method="PUT",
                payload={
                    "evidence_id": EVIDENCE_INCLUDE_ID,
                    "action": "approve",
                    "reason": "",
                    "version_token": current_items_before_blank[EVIDENCE_INCLUDE_ID]["version_token"],
                    "actor_type": "simulated_researcher_agent",
                    "actor_label": "res001-paper-evidence",
                },
            )
            if blank_status != 400:
                failures.append(f"blank reason expected HTTP 400, observed HTTP {blank_status}")
            assert _snapshot_tree(project) == before_rejected_requests
            assert _decision_projection_source_bytes(project) == before_rejected_evidence_bytes

            stale_status, _ = _json_request(
                base_url,
                _paper_evidence_path(),
                method="PUT",
                payload={
                    "evidence_id": EVIDENCE_INCLUDE_ID,
                    "action": "approve",
                    "reason": "Stale opaque token must not write.",
                    "version_token": "stale-" + current_items_before_blank[EVIDENCE_INCLUDE_ID]["version_token"],
                    "actor_type": "simulated_researcher_agent",
                    "actor_label": "res001-paper-evidence",
                },
            )
            if stale_status != 409:
                failures.append(f"stale version_token expected HTTP 409, observed HTTP {stale_status}")
            assert _snapshot_tree(project) == before_rejected_requests
            assert _decision_projection_source_bytes(project) == before_rejected_evidence_bytes

            include_status, after_include = _json_request(
                base_url,
                _paper_evidence_path(),
                method="PUT",
                payload={
                    "evidence_id": EVIDENCE_INCLUDE_ID,
                    "action": "approve",
                    "reason": "Researcher included the source-bound candidate after review.",
                    "version_token": current_items_before_blank[EVIDENCE_INCLUDE_ID]["version_token"],
                    "actor_type": "simulated_researcher_agent",
                    "actor_label": "res001-paper-evidence",
                },
            )
            assert include_status == 200
            after_include_items = _items(after_include)
            assert after_include_items[EVIDENCE_INCLUDE_ID]["status"] == "approved"
            assert after_include_items[EVIDENCE_INCLUDE_ID]["decision"]["action"] == "approve"
            assert after_include_items[EVIDENCE_INCLUDE_ID]["decision"]["reason"]
            assert after_include_items[EVIDENCE_EXCLUDE_ID]["status"] == "needs_review"
            _assert_no_promotion(project, after_include)

            exclude_status, final_payload = _json_request(
                base_url,
                _paper_evidence_path(),
                method="PUT",
                payload={
                    "evidence_id": EVIDENCE_EXCLUDE_ID,
                    "action": "reject",
                    "reason": "Researcher excluded the source-bound candidate with an explicit reason.",
                    "version_token": current_items_before_blank[EVIDENCE_EXCLUDE_ID]["version_token"],
                    "actor_type": "simulated_researcher_agent",
                    "actor_label": "res001-paper-evidence",
                },
            )
            assert exclude_status == 200
            final_items = _items(final_payload)
            assert final_items[EVIDENCE_INCLUDE_ID]["status"] == "approved"
            assert final_items[EVIDENCE_EXCLUDE_ID]["status"] == "rejected"
            assert final_items[EVIDENCE_EXCLUDE_ID]["decision"]["action"] == "reject"
            assert final_items[EVIDENCE_EXCLUDE_ID]["decision"]["reason"]
            _assert_no_promotion(project, final_payload)
        finally:
            prod006_fixture._stop_dashboard(server, thread)

        final_authority = _authority_snapshot(project)
        final_tree = _snapshot_tree(project)
        cold_server, cold_thread, cold_base_url = prod006_fixture._start_dashboard(
            Path(temporary_root)
        )
        try:
            cold_status, cold_payload = _json_request(cold_base_url, _paper_evidence_path())
            assert cold_status == 200
            assert cold_payload == final_payload
            _assert_no_promotion(project, cold_payload)
            assert _authority_snapshot(project) == final_authority
            assert _snapshot_tree(project) == final_tree
        finally:
            prod006_fixture._stop_dashboard(cold_server, cold_thread)

    assert not failures, "; ".join(failures)
