from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from review_writer.project.manuscript_v2 import register_section_draft
from review_writer.project.source_truth import load_source_truth_bundle
from tests.product_use import test_prod006_source_to_release as prod006_fixture
from view import serve_review_dashboard as dashboard


PROJECT_ID = prod006_fixture.PROJECT_ID
STUDY_ID = prod006_fixture.STUDY_ID
SOURCE_ID = prod006_fixture.SOURCE_ID
EVIDENCE_ID = prod006_fixture.EVIDENCE_ID
SYNTHESIS_ID = prod006_fixture.SYNTHESIS_ID
SECTION_ID = prod006_fixture.SECTION_ID
RISK_CLASSES = {"AI_PROVISIONAL", "GAP", "NON_COMPARABLE"}
SECTION_RISK_BINDINGS = {
    f"paper_evidence:{EVIDENCE_ID}",
    f"synthesis:{SYNTHESIS_ID}",
}


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


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
            raw = response.read()
            return response.status, json.loads(raw.decode("utf-8"))
    except HTTPError as exc:
        raw = exc.read()
        try:
            value: Any = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            value = {"raw": raw.decode("utf-8", errors="replace")}
        return exc.code, value


def _build_unapproved_project(review_root: Path) -> tuple[Path, str]:
    """Build only upstream evidence and an unapproved section in temp storage."""
    project = review_root / PROJECT_ID
    project.mkdir(parents=True, exist_ok=True)
    prod006_fixture._write_source_inputs(project)
    prod006_fixture.write_source_truth_bundle(project, STUDY_ID)
    prod006_fixture._approve_parse_quality(project, STUDY_ID)
    prod006_fixture._register_evidence(project)
    prod006_fixture._register_synthesis_and_contract(project)
    figure = prod006_fixture._write_source_figure_registry(project)

    attribution = (
        f"Source Figure Attribution: {figure['figure_id']} | {SOURCE_ID} | page 1 | Figure 1"
    )
    body = (
        f"[synthesis:{SYNTHESIS_ID}] The source reports a bounded outcome.\n\n"
        "![Tiny source figure](../01_evidence/parses/extracted/prod006-main/images/figure1.png)\n\n"
        f"{attribution} [evidence:{EVIDENCE_ID}]"
    )
    draft = register_section_draft(
        project,
        {
            "section_id": SECTION_ID,
            "heading": "Reported result",
            "body": body,
            "generation_content_agent_result_digest": "b" * 64,
        },
    )
    assert draft["status"] == "needs_human_edit"
    assert set(draft["high_risk_reasons"]) == {
        f"paper_evidence:{EVIDENCE_ID}",
        f"synthesis:{SYNTHESIS_ID}",
    }
    return project, body


def _pair_state(project: Path) -> dict[str, Any]:
    manuscript_path = project / "04_manuscript/manuscript.md"
    lineage_path = project / "04_manuscript/manuscript_lineage.v2.json"
    paths = {"manuscript": manuscript_path, "lineage": lineage_path}
    state: dict[str, Any] = {"paths": paths}
    for key, path in paths.items():
        state[f"{key}_exists"] = path.is_file() and not path.is_symlink()
        state[f"{key}_bytes"] = path.read_bytes() if state[f"{key}_exists"] else None
        state[f"{key}_sha256"] = (
            _sha256(state[f"{key}_bytes"])
            if state[f"{key}_bytes"] is not None
            else None
        )
    return state


def _assert_pair_unchanged(before: dict[str, Any], project: Path) -> None:
    after = _pair_state(project)
    assert after["manuscript_exists"] == before["manuscript_exists"]
    assert after["lineage_exists"] == before["lineage_exists"]
    assert after["manuscript_bytes"] == before["manuscript_bytes"]
    assert after["lineage_bytes"] == before["lineage_bytes"]
    assert after["manuscript_sha256"] == before["manuscript_sha256"]
    assert after["lineage_sha256"] == before["lineage_sha256"]


def _draft_path() -> str:
    return f"/api/project/{PROJECT_ID}/draft"


def _evidence_path() -> str:
    return f"/api/project/{PROJECT_ID}/paper-evidence"


def _assert_binding_and_risk_surface(
    project: Path,
    base_url: str,
    workspace: dict[str, Any],
) -> dict[str, Any]:
    section = next(row for row in workspace["sections"] if row["section_id"] == SECTION_ID)
    evidence_status, evidence_payload = _json_request(base_url, _evidence_path())
    assert evidence_status == 200
    evidence = next(
        row for row in evidence_payload["items"] if row["evidence_id"] == EVIDENCE_ID
    )
    assert evidence["source_id"] == SOURCE_ID
    assert set(evidence["risk_classes"]) == RISK_CLASSES

    source_truth = load_source_truth_bundle(project, STUDY_ID)
    assert [row["document_role"] for row in source_truth["sources"]] == ["MAIN"]

    binding_pairs = {
        (
            tuple(binding["paper_evidence_ids"]),
            tuple(binding["synthesis_ids"]),
        )
        for binding in section["claim_bindings"]
    }
    assert binding_pairs == {
        ((EVIDENCE_ID,), ()),
        ((), (SYNTHESIS_ID,)),
    }
    assert workspace.get("impact_preview") is None
    assert workspace.get("promotion", "NONE") == "NONE"
    return evidence


def test_prod005_dashboard_v2_draft_edit_merge_is_source_bound_and_restart_stable() -> None:
    with tempfile.TemporaryDirectory(prefix="prod005-dashboard-draft-") as temporary_root:
        review_root = Path(temporary_root)
        project, original_body = _build_unapproved_project(review_root)
        server, thread, base_url = prod006_fixture._start_dashboard(review_root)
        try:
            status, initial = _json_request(base_url, _draft_path())
            assert status == 200
            assert initial["route"] == "evidence-to-release.v1"
            assert initial["available"] is True
            initial_section = next(
                row for row in initial["sections"] if row["section_id"] == SECTION_ID
            )
            assert initial_section["status"] == "needs_human_edit"
            assert initial_section["body"] == original_body
            assert set(initial_section["risk_classes"]) == SECTION_RISK_BINDINGS
            _assert_binding_and_risk_surface(project, base_url, initial)

            blank_before = _pair_state(project)
            blank_status, _ = _json_request(
                base_url,
                _draft_path(),
                method="PUT",
                payload={
                    "section_id": SECTION_ID,
                    "edited_body": "",
                    "reason": "Blank edit must be rejected without a write.",
                    "version_token": initial_section["version_token"],
                    "actor_type": "simulated_researcher_agent",
                    "actor_label": "prod005-dashboard",
                },
            )
            assert blank_status == 400
            _assert_pair_unchanged(blank_before, project)

            edited_body = original_body.replace(
                "reports a bounded outcome", "records a bounded outcome"
            )
            valid_status, approved = _json_request(
                base_url,
                _draft_path(),
                method="PUT",
                payload={
                    "section_id": SECTION_ID,
                    "edited_body": edited_body,
                    "reason": "Reviewed the source-bound wording and retained all risk labels.",
                    "version_token": initial_section["version_token"],
                    "actor_type": "simulated_researcher_agent",
                    "actor_label": "prod005-dashboard",
                },
            )
            assert valid_status == 200
            assert approved["route"] == "evidence-to-release.v1"
            approved_section = next(
                row for row in approved["sections"] if row["section_id"] == SECTION_ID
            )
            assert approved_section["status"] == "approved"
            assert approved_section["body"] == edited_body
            assert approved_section["decision"]["action"] == "approve"
            assert approved_section["decision"]["actor_type"] == "simulated_researcher_agent"
            assert set(approved_section["risk_classes"]) == SECTION_RISK_BINDINGS
            assert approved.get("promotion", "NONE") == "NONE"
            assert not (project / "05_release").exists()

            merged_state = _pair_state(project)
            assert merged_state["manuscript_exists"] is True
            assert merged_state["lineage_exists"] is True
            manuscript_bytes = merged_state["manuscript_bytes"]
            lineage_bytes = merged_state["lineage_bytes"]
            assert isinstance(manuscript_bytes, bytes)
            assert isinstance(lineage_bytes, bytes)
            lineage = json.loads(lineage_bytes.decode("utf-8"))
            assert lineage["schema_version"] == "manuscript-lineage.v2"
            assert lineage["route"] == "evidence-to-release.v1"
            assert lineage["manuscript_sha256"] == merged_state["manuscript_sha256"]
            assert lineage["manuscript_sha256"] == _sha256(manuscript_bytes)
            assert lineage["lineage_digest"] == dashboard.canonical_digest(
                {key: value for key, value in lineage.items() if key != "lineage_digest"}
            )
            lineage_binding = lineage["claim_bindings"]
            assert len(lineage_binding) == 2
            assert {
                (
                    tuple(row["paper_evidence_ids"]),
                    tuple(row["synthesis_ids"]),
                )
                for row in lineage_binding
            } == {
                ((EVIDENCE_ID,), ()),
                ((), (SYNTHESIS_ID,)),
            }
            assert {row["section_id"] for row in lineage_binding} == {SECTION_ID}
            assert _assert_binding_and_risk_surface(project, base_url, approved)["source_id"] == SOURCE_ID

            stale_before = _pair_state(project)
            stale_status, _ = _json_request(
                base_url,
                _draft_path(),
                method="PUT",
                payload={
                    "section_id": SECTION_ID,
                    "edited_body": edited_body + "\n\nStale request must not win.",
                    "reason": "Stale token must be rejected without a write.",
                    "version_token": initial_section["version_token"],
                    "actor_type": "simulated_researcher_agent",
                    "actor_label": "prod005-dashboard",
                },
            )
            assert stale_status == 409
            _assert_pair_unchanged(stale_before, project)

            blank_after_merge_before = _pair_state(project)
            blank_after_merge_status, _ = _json_request(
                base_url,
                _draft_path(),
                method="PUT",
                payload={
                    "section_id": SECTION_ID,
                    "edited_body": "",
                    "reason": "Blank edit must remain fail-closed.",
                    "version_token": approved_section["version_token"],
                    "actor_type": "simulated_researcher_agent",
                    "actor_label": "prod005-dashboard",
                },
            )
            assert blank_after_merge_status == 400
            _assert_pair_unchanged(blank_after_merge_before, project)
        finally:
            prod006_fixture._stop_dashboard(server, thread)

        cold_server, cold_thread, cold_base_url = prod006_fixture._start_dashboard(review_root)
        try:
            cold_status, cold_workspace = _json_request(cold_base_url, _draft_path())
            assert cold_status == 200
            cold_section = next(
                row for row in cold_workspace["sections"] if row["section_id"] == SECTION_ID
            )
            assert cold_workspace["route"] == "evidence-to-release.v1"
            assert cold_section["status"] == "approved"
            assert cold_section["body"] == edited_body
            assert cold_section["version_token"] == approved_section["version_token"]
            assert set(cold_section["risk_classes"]) == SECTION_RISK_BINDINGS
            _assert_binding_and_risk_surface(project, cold_base_url, cold_workspace)

            cold_state = _pair_state(project)
            assert cold_state["manuscript_bytes"] == merged_state["manuscript_bytes"]
            assert cold_state["lineage_bytes"] == merged_state["lineage_bytes"]
            assert cold_state["manuscript_sha256"] == merged_state["manuscript_sha256"]
            assert cold_state["lineage_sha256"] == merged_state["lineage_sha256"]
            assert cold_workspace.get("promotion", "NONE") == "NONE"
            assert not (project / "05_release").exists()
        finally:
            prod006_fixture._stop_dashboard(cold_server, cold_thread)
