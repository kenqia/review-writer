from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from review_writer.project.manuscript_v2 import register_section_draft
from tests.product_use import test_prod002_source_pdf_descriptors as prod002_fixture
from tests.product_use import test_prod006_source_to_release as prod006_fixture
from tests.product_use import test_qual001_parse_quality_product_use as qual001_fixture


PROJECT_ID = prod006_fixture.PROJECT_ID
STUDY_ID = prod006_fixture.STUDY_ID
SOURCE_ID = prod006_fixture.SOURCE_ID
EVIDENCE_ID = prod006_fixture.EVIDENCE_ID
SYNTHESIS_ID = prod006_fixture.SYNTHESIS_ID
SECTION_ID = prod006_fixture.SECTION_ID
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


def _protected_current_bytes(project: Path) -> dict[str, bytes | None]:
    paths = {
        "state/current.json": project / "state/current.json",
        "versions/current.json": project / "versions/current.json",
    }
    return {
        relative: path.read_bytes() if path.is_file() and not path.is_symlink() else None
        for relative, path in paths.items()
    }


def _build_project(review_root: Path) -> tuple[Path, str]:
    """Build one synthetic project shared by every user-visible slice."""
    project = review_root / PROJECT_ID
    project.mkdir(parents=True, exist_ok=True)
    prod006_fixture._write_source_inputs(project)

    image_path = project / "01_evidence/parses/extracted/prod006-main/images/figure1.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(prod006_fixture._TINY_PNG)
    prod006_fixture.write_source_truth_bundle(project, STUDY_ID)
    prod006_fixture._approve_parse_quality(project, STUDY_ID)
    prod006_fixture._register_evidence(project)
    prod006_fixture._register_synthesis_and_contract(project)
    figure = prod006_fixture._write_source_figure_registry(project)

    body = (
        f"[synthesis:{SYNTHESIS_ID}] The source reports a bounded outcome.\n\n"
        "![Tiny source figure](../01_evidence/parses/extracted/prod006-main/images/figure1.png)\n\n"
        f"Source Figure Attribution: {figure['figure_id']} | {SOURCE_ID} | page 1 | Figure 1 "
        f"[evidence:{EVIDENCE_ID}]"
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
    return project, body


def _figure_payload(base_url: str) -> dict[str, Any]:
    status, payload = _json_request(
        base_url, f"/api/project/{PROJECT_ID}/review-figures"
    )
    assert status == 200
    assert payload["route"] == "evidence-to-release.v1"
    assert payload["status"] == "current"
    return payload


def _parse_quality_payload(base_url: str) -> dict[str, Any]:
    status, payload = _json_request(
        base_url, f"/api/project/{PROJECT_ID}/parse-quality"
    )
    assert status == 200
    assert payload["project_id"] == PROJECT_ID
    return payload


def test_user_visible_integration_regression_uses_one_project_and_owned_session() -> None:
    with tempfile.TemporaryDirectory(prefix="user-visible-integration-") as temporary_root:
        review_root = Path(temporary_root)
        project, original_body = _build_project(review_root)
        protected_before = _protected_current_bytes(project)
        server, thread, base_url = prod006_fixture._start_dashboard(review_root)
        assert server.server_address[0] == "127.0.0.1"
        assert server.server_address[1] > 0
        try:
            # PROD-002: the figure asset predates Source Truth, so this GET is
            # a current, source-bound, read-only descriptor projection.
            before_descriptor = _snapshot_tree(project)
            status, paper_evidence = _json_request(
                base_url, f"/api/project/{PROJECT_ID}/paper-evidence"
            )
            assert status == 200
            descriptors = paper_evidence["source_pdf_descriptors"]
            assert descriptors["status"] == "current"
            assert descriptors["items"]
            assert _snapshot_tree(project) == before_descriptor
            assert _protected_current_bytes(project) == protected_before

            # PROD-005: current Draft, invalid PUT, stale PUT, then one valid
            # source-bound edit. Rejected PUTs must be zero-write.
            draft_path = f"/api/project/{PROJECT_ID}/draft"
            status, initial_draft = _json_request(base_url, draft_path)
            assert status == 200
            assert initial_draft["route"] == "evidence-to-release.v1"
            initial_section = next(
                row for row in initial_draft["sections"] if row["section_id"] == SECTION_ID
            )
            assert initial_section["status"] == "needs_human_edit"
            assert initial_section["body"] == original_body
            assert set(initial_section["risk_classes"]) == {
                f"paper_evidence:{EVIDENCE_ID}",
                f"synthesis:{SYNTHESIS_ID}",
            }

            rejected_before = _snapshot_tree(project)
            status, _ = _json_request(
                base_url,
                draft_path,
                method="PUT",
                payload={
                    "section_id": SECTION_ID,
                    "edited_body": "",
                    "reason": "Blank edit must be rejected without a write.",
                    "version_token": initial_section["version_token"],
                    "actor_type": "simulated_researcher_agent",
                    "actor_label": "user-visible-integration",
                },
            )
            assert status == 400
            assert _snapshot_tree(project) == rejected_before
            assert _protected_current_bytes(project) == protected_before

            status, _ = _json_request(
                base_url,
                draft_path,
                method="PUT",
                payload={
                    "section_id": SECTION_ID,
                    "edited_body": original_body + "\n\nStale request must not win.",
                    "reason": "Stale token must be rejected without a write.",
                    "version_token": "stale-" + initial_section["version_token"],
                    "actor_type": "simulated_researcher_agent",
                    "actor_label": "user-visible-integration",
                },
            )
            assert status == 409
            assert _snapshot_tree(project) == rejected_before
            assert _protected_current_bytes(project) == protected_before

            edited_body = original_body.replace(
                "reports a bounded outcome", "records a bounded outcome"
            )
            status, approved_draft = _json_request(
                base_url,
                draft_path,
                method="PUT",
                payload={
                    "section_id": SECTION_ID,
                    "edited_body": edited_body,
                    "reason": "Reviewed the source-bound wording and retained all risk labels.",
                    "version_token": initial_section["version_token"],
                    "actor_type": "simulated_researcher_agent",
                    "actor_label": "user-visible-integration",
                },
            )
            assert status == 200
            approved_section = next(
                row for row in approved_draft["sections"] if row["section_id"] == SECTION_ID
            )
            assert approved_section["status"] == "approved"
            assert approved_section["body"] == edited_body
            assert _protected_current_bytes(project) == protected_before
            assert (project / "04_manuscript/manuscript.md").is_file()
            assert (project / "04_manuscript/manuscript_lineage.v2.json").is_file()

            # FIG-001: source registry GET is current and read-only. This
            # regression deliberately does not mutate the known figure token.
            before_figures = _snapshot_tree(project)
            figure_payload = _figure_payload(base_url)
            figure = figure_payload["source_figures"][0]
            assert figure["source_id"] == SOURCE_ID
            assert figure["evidence_ids"] == [EVIDENCE_ID]
            assert figure["selection_status"] == "selected"
            assert _snapshot_tree(project) == before_figures
            assert _protected_current_bytes(project) == protected_before

            # QUAL-001: parse-quality remains approved in the same Dashboard
            # session; blank and stale PUTs are invalid/zero-write.
            before_parse = _snapshot_tree(project)
            parse_payload = _parse_quality_payload(base_url)
            assert parse_payload["status"] == "approved"
            assert parse_payload["workflow_can_continue"] is True
            parse_study, parse_object = qual001_fixture._parse_route_row(parse_payload)
            parse_base = {
                "study_id": STUDY_ID,
                "object_id": parse_object["object_id"],
                "decision_token": parse_object["decision_token"],
                "action": "approve_candidate_extraction",
            }
            status, _ = _json_request(
                base_url,
                f"/api/project/{PROJECT_ID}/parse-quality",
                method="PUT",
                payload={**parse_base, "note": ""},
            )
            assert status == 400
            assert _snapshot_tree(project) == before_parse
            status, _ = _json_request(
                base_url,
                f"/api/project/{PROJECT_ID}/parse-quality",
                method="PUT",
                payload={
                    **parse_base,
                    "decision_token": "stale-" + parse_base["decision_token"],
                    "note": "Stale parse-quality token must fail closed.",
                },
            )
            assert status == 409
            assert _snapshot_tree(project) == before_parse
            assert parse_study["study_id"] == STUDY_ID
            assert _protected_current_bytes(project) == protected_before

            # QUAL-002: the final Dashboard evaluation projection fails closed
            # when no benchmark report is present; stale/old scores are absent.
            before_final = _snapshot_tree(project)
            status, final_payload = _json_request(
                base_url, f"/api/project/{PROJECT_ID}/final"
            )
            assert status == 200
            benchmark = final_payload["evaluation"]["benchmark"]
            assert benchmark == {
                "status": "unavailable",
                "reason_code": "BENCHMARK_REPORT_MISSING",
            }
            assert _snapshot_tree(project) == before_final
            assert _protected_current_bytes(project) == protected_before

            # RES-001: current paper-evidence row plus invalid/stale PUTs. No
            # decision is changed here, so the approved draft remains bound.
            before_evidence = _snapshot_tree(project)
            status, evidence_payload = _json_request(
                base_url, f"/api/project/{PROJECT_ID}/paper-evidence"
            )
            assert status == 200
            evidence = next(
                row for row in evidence_payload["items"] if row["evidence_id"] == EVIDENCE_ID
            )
            assert evidence["source_id"] == SOURCE_ID
            assert set(evidence["risk_classes"]) == RISK_CLASSES
            assert evidence["status"] == "approved"
            invalid_evidence = {
                "evidence_id": EVIDENCE_ID,
                "action": "approve",
                "reason": "",
                "version_token": evidence["version_token"],
            }
            status, _ = _json_request(
                base_url,
                f"/api/project/{PROJECT_ID}/paper-evidence",
                method="PUT",
                payload=invalid_evidence,
            )
            assert status == 400
            assert _snapshot_tree(project) == before_evidence
            status, _ = _json_request(
                base_url,
                f"/api/project/{PROJECT_ID}/paper-evidence",
                method="PUT",
                payload={
                    **invalid_evidence,
                    "reason": "Stale evidence token must fail closed.",
                    "version_token": "stale-" + evidence["version_token"],
                },
            )
            assert status == 409
            assert _snapshot_tree(project) == before_evidence
            assert _protected_current_bytes(project) == protected_before

            # PROD-002 stale state: mutate only the synthetic persisted bundle
            # to model a stale fixture, then verify the GET is zero-write and
            # fail-closed with no descriptor items.
            prod002_fixture._make_persisted_bundle_stale(project)
            before_stale_descriptor = _snapshot_tree(project)
            status, stale_payload = _json_request(
                base_url, f"/api/project/{PROJECT_ID}/paper-evidence"
            )
            assert status == 200
            assert stale_payload["source_pdf_descriptors"] == {
                "status": "stale",
                "items": [],
            }
            assert _snapshot_tree(project) == before_stale_descriptor
            assert _protected_current_bytes(project) == protected_before
        finally:
            prod006_fixture._stop_dashboard(server, thread)

        assert not thread.is_alive()
        assert _protected_current_bytes(project) == protected_before
