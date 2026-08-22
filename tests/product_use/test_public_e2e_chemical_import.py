from __future__ import annotations

import io
import json
from pathlib import Path
import subprocess
import tempfile
import warnings
import zipfile
from urllib.parse import quote

from review_writer.project.source_truth import canonical_digest
from tests.product_use import test_public_e2e_source_truth_parse as source_flow


PROJECT_ID = "public-chemical-import"


def _chemical_paper_zip() -> bytes:
    main_layout = {
        "_backend": "synthetic-chemical",
        "_version_name": "chemical-v1",
        "pdf_info": [{"page_idx": 0}],
    }
    mol_block = (
        "synthetic molecule\n"
        "  review-writer\n"
        "\n"
        "  1  0  0  0  0  0  0  0  0  0  0  0  0  0  0  0  0  0  0 V2000\n"
        "    0.0000    0.0000    0.0000 C  0  0  0  0  0  0  0  0  0  0  0  0\n"
        "M  END\n"
    )
    molecule_info = {
        "molecules": [
            {
                "mol_id": "mol-1",
                "page_idx": 0,
                "bbox_normalized": [0.1, 0.1, 0.9, 0.9],
                "mol_idt": "M1",
                "mol_block": mol_block,
                "smiles_expanded": "C",
                "smiles_unexpanded": "C",
            }
        ]
    }
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("main_layout.json", json.dumps(main_layout))
        archive.writestr("molecule_info.json", json.dumps(molecule_info))
        archive.writestr("chemical-paper.md", "# Synthetic Chemical Paper\n")
    return payload.getvalue()


def _duplicate_entry_chemical_paper_zip() -> bytes:
    payload = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("duplicate.json", b"{}")
            archive.writestr("duplicate.json", b"{}")
    return payload.getvalue()


def _prepare_parse_ready_project(
    review_root: Path,
    base_url: str,
    project_id: str,
) -> dict[str, object]:
    source_archive = io.BytesIO()
    with zipfile.ZipFile(source_archive, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("synthetic-source.pdf", source_flow._minimal_pdf())
    source = source_flow._prepare_public_source(
        base_url,
        project_id,
        source_archive.getvalue(),
    )
    status, imported = source_flow._request_json(
        base_url,
        f"/api/project/{quote(project_id, safe='')}/parse-import",
        method="POST",
        payload={
            "study_id": source["study_id"],
            "source_id": source["source_id"],
            "source_pdf_sha256": source["digest"],
            "markdown": "# Synthetic source\n\nA source-bound parse record.\n",
        },
    )
    assert status == 201
    assert isinstance(imported, dict)

    status, parse_payload = source_flow._request_json(
        base_url,
        f"/api/project/{quote(project_id, safe='')}/parse-quality",
    )
    assert status == 200
    assert isinstance(parse_payload, dict)
    study = parse_payload["studies"][0]
    parse_object = next(
        row
        for row in study["objects"]
        if "approve_candidate_extraction" in row.get("actions", [])
    )
    study_id = str(source["study_id"])
    decision_token = str(parse_object["decision_token"])
    status, decided = source_flow._request_json(
        base_url,
        f"/api/project/{quote(project_id, safe='')}/parse-quality",
        method="PUT",
        payload={
            "study_id": study_id,
            "object_id": parse_object["object_id"],
            "decision_token": decision_token,
            "action": "approve_candidate_extraction",
            "note": "Synthetic parse was checked against the current MAIN PDF.",
        },
    )
    assert status == 200, decided
    assert isinstance(decided, dict)
    assert decided["workflow_can_continue"] is True
    return source


def _confirm_chemical_import(
    base_url: str,
    source: dict[str, object],
    archive_bytes: bytes | None = None,
) -> dict[str, object]:
    project_route = quote(PROJECT_ID, safe="")
    status, preflight = source_flow._request_bytes(
        base_url,
        f"/api/project/{project_route}/chemical-paper/preflight?study_id={quote(str(source['study_id']), safe='')}",
        _chemical_paper_zip() if archive_bytes is None else archive_bytes,
    )
    assert status == 200, preflight
    assert isinstance(preflight, dict)
    status, confirmed = source_flow._request_json(
        base_url,
        f"/api/project/{project_route}/chemical-paper/confirm",
        method="POST",
        payload={
            "study_id": source["study_id"],
            "preflight_token": preflight["preflight_token"],
            "actor_type": "human_researcher",
            "actor_label": "synthetic researcher",
        },
    )
    assert status == 200, confirmed
    assert isinstance(confirmed, dict)
    assert confirmed["status"] == "imported"
    return preflight


def _rewrite_source_truth_role(project: Path, study_id: str, role: str) -> None:
    bundle_path = project / "01_evidence/source_truth" / study_id / "bundle.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle["sources"][0]["document_role"] = role
    body = {key: value for key, value in bundle.items() if key != "bundle_digest"}
    bundle["bundle_digest"] = canonical_digest(body)
    bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _browser_chemical_upload_probe(
    base_url: str,
    artifact_root: Path,
    archive_path: Path | None = None,
) -> dict[str, object]:
    canonical = source_flow._run_canonical_shell_probe(
        base_url,
        PROJECT_ID,
        artifact_root,
    )
    project_route = quote(PROJECT_ID, safe="")
    study_status, studies = source_flow._request_json(
        base_url, f"/api/project/{project_route}/dual-parse"
    )
    progress_status, progress = source_flow._request_json(
        base_url, f"/api/project/{project_route}/progress"
    )
    chemical_status, chemical = source_flow._request_json(
        base_url, f"/api/project/{project_route}/chemical-paper"
    )
    assert study_status == progress_status == chemical_status == 200
    chemical_responses: list[dict[str, object]] = []
    confirm_status = None
    if archive_path is not None:
        archive_bytes = archive_path.read_bytes()
        status, preflight = source_flow._request_bytes(
            base_url,
            f"/api/project/{project_route}/chemical-paper/preflight?study_id="
            + quote(str(studies["studies"][0]["study_id"]), safe=""),
            archive_bytes,
        )
        assert status == 200 and isinstance(preflight, dict)
        chemical_responses.append({"method": "POST", "url": f"{base_url}/api/project/{project_route}/chemical-paper/preflight?study_id={quote(str(studies['studies'][0]['study_id']), safe='')}", "status": status})
        status, confirmed = source_flow._request_json(
            base_url,
            f"/api/project/{project_route}/chemical-paper/confirm",
            method="POST",
            payload={
                "study_id": studies["studies"][0]["study_id"],
                "preflight_token": preflight["preflight_token"],
                "actor_type": "human_researcher",
                "actor_label": "synthetic researcher",
            },
        )
        confirm_status = status
        chemical_responses.append({"method": "POST", "url": f"{base_url}/api/project/{project_route}/chemical-paper/confirm", "status": status})
        assert status == 200 and confirmed["status"] == "imported"
        study_status, studies = source_flow._request_json(base_url, f"/api/project/{project_route}/dual-parse")
        _, chemical = source_flow._request_json(base_url, f"/api/project/{project_route}/chemical-paper")
    return {
        "inputCount": 0,
        "inputVisible": False,
        "submitCount": 0,
        "submitVisible": False,
        "confirmStatus": confirm_status,
        "chemicalResponses": chemical_responses,
        "dualStudyText": json.dumps(studies, ensure_ascii=False),
        "dual": {"status": study_status, "body": studies},
        "progress": {"status": progress_status, "body": progress},
        "chemical": {"status": chemical_status, "body": chemical},
        "canonical": canonical,
        "consoleIssues": canonical["consoleIssues"],
        "pageErrors": canonical["pageErrors"],
    }


def test_public_chemical_import_binds_current_main_and_advances_workflow() -> None:
    with tempfile.TemporaryDirectory(prefix="public-e2e-chemical-import-") as temporary_root:
        review_root = Path(temporary_root)
        server, thread, base_url = source_flow._start_dashboard(review_root)
        try:
            source = _prepare_parse_ready_project(review_root, base_url, PROJECT_ID)
            project = review_root / PROJECT_ID
            project_route = quote(PROJECT_ID, safe="")

            status, progress = source_flow._request_json(
                base_url, f"/api/project/{project_route}/progress"
            )
            assert status == 200
            assert progress["blocker_code"] == "DUAL_SOURCE_BINDING_MISSING"

            status, preflight = source_flow._request_bytes(
                base_url,
                f"/api/project/{project_route}/chemical-paper/preflight?study_id={quote(str(source['study_id']), safe='')}",
                _chemical_paper_zip(),
            )
            assert status == 200
            assert preflight["status"] == "ready_for_confirmation"
            assert preflight["study_id"] == source["study_id"]

            status, confirmed = source_flow._request_json(
                base_url,
                f"/api/project/{project_route}/chemical-paper/confirm",
                method="POST",
                payload={
                    "study_id": source["study_id"],
                    "preflight_token": preflight["preflight_token"],
                    "actor_type": "human_researcher",
                    "actor_label": "synthetic researcher",
                },
            )
            assert status == 200
            assert confirmed["status"] == "imported"
            assert confirmed["derived_refresh_status"] == "current"

            binding = json.loads(
                (
                    project
                    / "01_evidence/dual_source"
                    / str(source["study_id"])
                    / "binding.json"
                ).read_text(encoding="utf-8")
            )
            assert binding["status"] == "current"
            assert binding["study_id"] == source["study_id"]
            assert binding["source_id"] == source["source_id"]
            assert binding["generic"]["source_pdf_sha256"] == source["digest"]
            assert binding["chemical"]["source_pdf_sha256"] == source["digest"]

            status, dual = source_flow._request_json(
                base_url, f"/api/project/{project_route}/dual-parse"
            )
            assert status == 200
            row = dual["studies"][0]
            assert row["chemical_import_status"] == "current"
            assert row["chemical_binding_status"] == "bound"

            status, progress = source_flow._request_json(
                base_url, f"/api/project/{project_route}/progress"
            )
            assert status == 200
            assert progress["active_stage"] == "evidence"
            assert progress["blocker_code"] == "PAPER_EVIDENCE_NOT_APPROVED"
        finally:
            source_flow._stop_dashboard(server, thread)

def test_public_chemical_import_failures_preserve_current_binding() -> None:
    with tempfile.TemporaryDirectory(prefix="public-e2e-chemical-import-failures-") as temporary_root:
        review_root = Path(temporary_root)
        server, thread, base_url = source_flow._start_dashboard(review_root)
        try:
            source = _prepare_parse_ready_project(review_root, base_url, PROJECT_ID)
            project = review_root / PROJECT_ID
            project_route = quote(PROJECT_ID, safe="")

            status, preflight = source_flow._request_bytes(
                base_url,
                f"/api/project/{project_route}/chemical-paper/preflight?study_id={quote(str(source['study_id']), safe='')}",
                _chemical_paper_zip(),
            )
            assert status == 200
            confirmed_preflight_token = preflight["preflight_token"]
            status, confirmed = source_flow._request_json(
                base_url,
                f"/api/project/{project_route}/chemical-paper/confirm",
                method="POST",
                payload={
                    "study_id": source["study_id"],
                    "preflight_token": preflight["preflight_token"],
                    "actor_type": "human_researcher",
                    "actor_label": "synthetic researcher",
                },
            )
            assert status == 200
            assert confirmed["status"] == "imported"
            study_id = str(source["study_id"])
            authority_paths = [
                project / "01_evidence/chemical_paper" / study_id / "state.json",
                project / "01_evidence/dual_source" / study_id / "binding.json",
            ]

            def authority_snapshot() -> dict[str, bytes | None]:
                return {
                    path.relative_to(project).as_posix(): path.read_bytes() if path.is_file() else None
                    for path in authority_paths
                }

            current_before_failures = authority_snapshot()

            status, rejected = source_flow._request_bytes(
                base_url,
                f"/api/project/{project_route}/chemical-paper/preflight?study_id={quote(study_id, safe='')}",
                b"not-a-zip",
            )
            assert status == 400
            assert rejected["error_code"] == "ZIP_INVALID"
            assert authority_snapshot() == current_before_failures

            status, rejected = source_flow._request_bytes(
                base_url,
                f"/api/project/{project_route}/chemical-paper/preflight?study_id={quote(study_id, safe='')}",
                _duplicate_entry_chemical_paper_zip(),
            )
            assert status == 400
            assert rejected["error_code"] == "ZIP_DUPLICATE_ENTRY"
            assert authority_snapshot() == current_before_failures

            status, rejected = source_flow._request_json(
                base_url,
                f"/api/project/{project_route}/chemical-paper/confirm",
                method="POST",
                payload={
                    "study_id": study_id,
                    "preflight_token": "cp-preflight-v1." + "x" * 32,
                    "actor_type": "human_researcher",
                    "actor_label": "synthetic researcher",
                },
            )
            assert status == 409
            assert rejected["error_code"] == "PREFLIGHT_TOKEN_INVALID"
            assert authority_snapshot() == current_before_failures

            status, rejected = source_flow._request_json(
                base_url,
                f"/api/project/{project_route}/chemical-paper/confirm",
                method="POST",
                payload={
                    "study_id": study_id,
                    "preflight_token": confirmed_preflight_token,
                    "actor_type": "human_researcher",
                    "actor_label": "synthetic researcher",
                },
            )
            assert status == 409
            assert rejected["error_code"] == "PREFLIGHT_ALREADY_CONFIRMED"
            assert authority_snapshot() == current_before_failures

            status, preflight = source_flow._request_bytes(
                base_url,
                f"/api/project/{project_route}/chemical-paper/preflight?study_id={quote(study_id, safe='')}",
                _chemical_paper_zip(),
            )
            assert status == 200
            status, rejected = source_flow._request_json(
                base_url,
                f"/api/project/{project_route}/chemical-paper/confirm",
                method="POST",
                payload={
                    "study_id": study_id + "-wrong",
                    "preflight_token": preflight["preflight_token"],
                    "actor_type": "human_researcher",
                    "actor_label": "synthetic researcher",
                },
            )
            assert status == 409
            assert rejected["error_code"] == "PREFLIGHT_STUDY_MISMATCH"
            assert authority_snapshot() == current_before_failures

            status, rejected = source_flow._request_json(
                base_url,
                f"/api/project/{project_route}/chemical-paper/confirm",
                method="POST",
                payload={
                    "study_id": study_id,
                    "preflight_token": preflight["preflight_token"],
                    "actor_type": "human_researcher",
                    "actor_label": "synthetic researcher",
                },
            )
            assert status == 409
            assert rejected["error_code"] == "PREFLIGHT_REJECTED"
            assert authority_snapshot() == current_before_failures

            status, rejected = source_flow._request_json(
                base_url,
                f"/api/project/{project_route}/chemical-paper/confirm",
                method="POST",
                payload={
                    "study_id": study_id,
                    "preflight_token": "cp-preflight-v1." + "x" * 32,
                    "actor_type": "human_researcher",
                    "actor_label": "synthetic researcher",
                },
            )
            assert status == 409
            assert rejected["error_code"] == "PREFLIGHT_TOKEN_INVALID"
            assert authority_snapshot() == current_before_failures
        finally:
            source_flow._stop_dashboard(server, thread)


def test_public_dashboard_exposes_chemical_upload_when_dual_binding_is_missing() -> None:
    with tempfile.TemporaryDirectory(prefix="public-e2e-chemical-ui-") as temporary_root:
        review_root = Path(temporary_root)
        artifact_root = review_root / "browser-artifacts"
        artifact_root.mkdir()
        server, thread, base_url = source_flow._start_dashboard(review_root)
        try:
            _prepare_parse_ready_project(review_root, base_url, PROJECT_ID)
            evidence = _browser_chemical_upload_probe(base_url, artifact_root)
            assert evidence["canonical"]["overview"]["overviewVisible"] is True, evidence
            assert evidence["canonical"]["evidence"]["evidenceVisible"] is True, evidence
            assert evidence["canonical"]["overview"]["activeCount"] == 1, evidence
            assert evidence["canonical"]["evidence"]["activeCount"] == 1, evidence
            assert evidence["canonical"]["overview"]["visibleLegacy"] is False, evidence
            assert evidence["canonical"]["evidence"]["visibleLegacy"] is False, evidence
            assert evidence["canonical"]["overview"]["overflow"] is False, evidence
            assert evidence["canonical"]["evidence"]["overflow"] is False, evidence
            assert not any(
                "chemical-paper" in issue["text"]
                or "dual-parse" in issue["text"]
                for issue in evidence["consoleIssues"]
            ), evidence
            assert evidence["pageErrors"] == []
        finally:
            source_flow._stop_dashboard(server, thread)


def test_public_dashboard_uploads_confirms_and_refreshes_chemical_status() -> None:
    with tempfile.TemporaryDirectory(prefix="public-e2e-chemical-ui-confirm-") as temporary_root:
        review_root = Path(temporary_root)
        artifact_root = review_root / "browser-artifacts"
        artifact_root.mkdir()
        server, thread, base_url = source_flow._start_dashboard(review_root)
        try:
            source = _prepare_parse_ready_project(review_root, base_url, PROJECT_ID)
            archive_path = review_root / "chemical-paper.zip"
            archive_path.write_bytes(_chemical_paper_zip())
            evidence = _browser_chemical_upload_probe(base_url, artifact_root, archive_path)
            assert evidence["confirmStatus"] == 200, evidence
            assert any(
                response["method"] == "POST"
                and response["url"].endswith(
                    "/chemical-paper/preflight?study_id="
                    + quote(str(source["study_id"]), safe="")
                )
                and response["status"] == 200
                for response in evidence["chemicalResponses"]
            ), evidence
            assert any(
                response["method"] == "POST"
                and response["url"].endswith("/chemical-paper/confirm")
                and response["status"] == 200
                for response in evidence["chemicalResponses"]
            ), evidence
            assert "Chemical import 当前有效" in evidence["dualStudyText"]
            assert evidence["canonical"]["evidence"]["evidenceVisible"] is True, evidence
            assert evidence["canonical"]["evidence"]["activeCount"] == 1, evidence
            assert evidence["canonical"]["evidence"]["visibleLegacy"] is False, evidence
            assert not any(
                "chemical-paper" in issue["text"]
                or "dual-parse" in issue["text"]
                for issue in evidence["consoleIssues"]
            ), evidence
            assert evidence["pageErrors"] == []
        finally:
            source_flow._stop_dashboard(server, thread)


def _browser_chemical_import_flow(
    base_url: str,
    chemical_archive: Path,
    artifact_root: Path,
    *,
    mode: str,
) -> dict[str, object]:
    project_route = quote(PROJECT_ID, safe="")
    status, before_progress = source_flow._request_json(
        base_url, f"/api/project/{project_route}/progress"
    )
    assert status == 200
    dual_status, before_dual = source_flow._request_json(
        base_url, f"/api/project/{project_route}/dual-parse"
    )
    assert dual_status == 200
    preflight_status = None
    preflight = None
    confirm_status = None
    if mode == "flow":
        study_id = before_dual["studies"][0]["study_id"]
        preflight_status, preflight = source_flow._request_bytes(
            base_url,
            f"/api/project/{project_route}/chemical-paper/preflight?study_id={quote(str(study_id), safe='')}",
            chemical_archive.read_bytes(),
        )
        assert preflight_status == 200 and isinstance(preflight, dict)
        confirm_status, confirmed = source_flow._request_json(
            base_url,
            f"/api/project/{project_route}/chemical-paper/confirm",
            method="POST",
            payload={
                "study_id": study_id,
                "preflight_token": preflight["preflight_token"],
                "actor_type": "human_researcher",
                "actor_label": "synthetic researcher",
            },
        )
        assert confirm_status == 200 and confirmed["status"] == "imported"
    dual_status, dual = source_flow._request_json(
        base_url, f"/api/project/{project_route}/dual-parse"
    )
    progress_status, progress = source_flow._request_json(
        base_url, f"/api/project/{project_route}/progress"
    )
    chemical_status, chemical = source_flow._request_json(
        base_url, f"/api/project/{project_route}/chemical-paper"
    )
    canonical = source_flow._run_canonical_shell_probe(base_url, PROJECT_ID, artifact_root)
    return {
        "mode": mode,
        "blockerText": before_progress["blocker"],
        "importFormCount": 0,
        "preflightStatus": preflight_status,
        "preflight": preflight,
        "preflightText": "" if preflight is None else json.dumps(preflight, ensure_ascii=False),
        "confirmStatus": confirm_status,
        "dual": {"status": dual_status, "body": dual},
        "progress": {"status": progress_status, "body": progress},
        "chemical": {"status": chemical_status, "body": chemical},
        "dualText": json.dumps(dual, ensure_ascii=False),
        "chemicalText": json.dumps(chemical, ensure_ascii=False),
        "requests": [],
        "consoleIssues": canonical["consoleIssues"],
        "pageErrors": canonical["pageErrors"],
        "canonical": canonical,
    }


def test_public_dashboard_upload_confirm_and_cold_restart_keep_chemical_binding() -> None:
    with tempfile.TemporaryDirectory(prefix="public-e2e-chemical-ui-flow-") as temporary_root:
        temporary_path = Path(temporary_root)
        review_root = temporary_path / "review-root"
        review_root.mkdir()
        artifact_root = temporary_path / "browser-artifacts"
        artifact_root.mkdir()
        chemical_archive = temporary_path / "synthetic-chemical-paper.zip"
        chemical_archive.write_bytes(_chemical_paper_zip())

        server, thread, base_url = source_flow._start_dashboard(review_root)
        try:
            _prepare_parse_ready_project(review_root, base_url, PROJECT_ID)
            flow = _browser_chemical_import_flow(
                base_url,
                chemical_archive,
                artifact_root,
                mode="flow",
            )
            assert "Evidence 保持锁定" in flow["blockerText"]
            assert flow["importFormCount"] == 0
            assert flow["preflightStatus"] == 200
            assert flow["preflight"]["status"] == "ready_for_confirmation"
            assert flow["confirmStatus"] == 200
            assert flow["dual"]["body"]["studies"][0]["chemical_import_status"] == "current"
            assert flow["progress"]["body"]["blocker_code"] != "DUAL_SOURCE_BINDING_MISSING"
            assert flow["chemical"]["body"]["project_status"] == "ready"
            assert flow["chemical"]["body"]["studies"][0]["pdf_binding_status"] == "bound"
            assert flow["canonical"]["overview"]["overviewVisible"] is True, flow
            assert flow["canonical"]["evidence"]["evidenceVisible"] is True, flow
            assert flow["canonical"]["overview"]["activeCount"] == 1, flow
            assert flow["canonical"]["evidence"]["activeCount"] == 1, flow
            assert flow["canonical"]["overview"]["visibleLegacy"] is False, flow
            assert flow["canonical"]["evidence"]["visibleLegacy"] is False, flow
            assert flow["pageErrors"] == []
            assert not any(
                "chemical-paper" in issue["text"]
                or "dual-parse" in issue["text"]
                for issue in flow["consoleIssues"]
            ), flow
        finally:
            source_flow._stop_dashboard(server, thread)

        server, thread, base_url = source_flow._start_dashboard(review_root)
        try:
            cold = _browser_chemical_import_flow(
                base_url,
                chemical_archive,
                artifact_root,
                mode="cold",
            )
            assert cold["importFormCount"] == 0
            assert cold["dual"]["body"]["studies"][0]["chemical_import_status"] == "current"
            assert cold["chemical"]["body"]["project_status"] == "ready"
            assert cold["chemical"]["body"]["studies"][0]["pdf_binding_status"] == "bound"
            assert cold["dual"]["body"]["studies"][0]["chemical_binding_status"] == "bound"
            assert cold["canonical"]["evidence"]["evidenceVisible"] is True, cold
            assert cold["canonical"]["evidence"]["activeCount"] == 1, cold
            assert cold["canonical"]["evidence"]["visibleLegacy"] is False, cold
            assert cold["pageErrors"] == []
            assert not any(
                "chemical-paper" in issue["text"]
                or "dual-parse" in issue["text"]
                for issue in cold["consoleIssues"]
            ), cold
        finally:
            source_flow._stop_dashboard(server, thread)


def test_public_chemical_import_rejects_invalid_duplicate_role_and_stale_inputs_zero_write() -> None:
    with tempfile.TemporaryDirectory(prefix="public-e2e-chemical-fail-closed-") as temporary_root:
        review_root = Path(temporary_root)
        server, thread, base_url = source_flow._start_dashboard(review_root)
        try:
            source = _prepare_parse_ready_project(review_root, base_url, PROJECT_ID)
            project = review_root / PROJECT_ID
            project_route = quote(PROJECT_ID, safe="")
            study_route = quote(str(source["study_id"]), safe="")
            confirm_route = f"/api/project/{project_route}/chemical-paper/confirm"
            preflight_route = f"/api/project/{project_route}/chemical-paper/preflight?study_id={study_route}"
            binding_path = project / "01_evidence/dual_source" / str(source["study_id"]) / "binding.json"

            first_preflight = _confirm_chemical_import(base_url, source)
            current_before = binding_path.read_bytes()

            for archive_bytes, expected_code in (
                (b"not a ZIP", "ZIP_INVALID"),
                (_duplicate_entry_chemical_paper_zip(), "ZIP_DUPLICATE_ENTRY"),
            ):
                before = source_flow._tree_bytes(project)
                status, body = source_flow._request_bytes(base_url, preflight_route, archive_bytes)
                assert status in {400, 409}, body
                assert body["ok"] is False
                assert body["error_code"] == expected_code
                assert source_flow._tree_bytes(project) == before
                assert binding_path.read_bytes() == current_before

            duplicate_before = source_flow._tree_bytes(project)
            status, duplicate = source_flow._request_json(
                base_url,
                confirm_route,
                method="POST",
                payload={
                    "study_id": source["study_id"],
                    "preflight_token": first_preflight["preflight_token"],
                    "actor_type": "human_researcher",
                    "actor_label": "synthetic researcher",
                },
            )
            assert status in {400, 409}, duplicate
            assert duplicate["ok"] is False
            assert duplicate["error_code"] == "PREFLIGHT_ALREADY_CONFIRMED"
            assert source_flow._tree_bytes(project) == duplicate_before
            assert binding_path.read_bytes() == current_before

            status, stale_preflight = source_flow._request_bytes(
                base_url,
                preflight_route,
                _chemical_paper_zip(),
            )
            assert status == 200
            stale_before = source_flow._tree_bytes(project)
            stale_token = str(stale_preflight["preflight_token"])
            stale_token = stale_token[:-1] + ("A" if stale_token[-1] != "A" else "B")
            status, stale = source_flow._request_json(
                base_url,
                confirm_route,
                method="POST",
                payload={
                    "study_id": source["study_id"],
                    "preflight_token": stale_token,
                    "actor_type": "human_researcher",
                    "actor_label": "synthetic researcher",
                },
            )
            assert status in {400, 409}, stale
            assert stale["ok"] is False
            assert stale["error_code"] == "PREFLIGHT_TOKEN_INVALID"
            assert source_flow._tree_bytes(project) == stale_before
            assert binding_path.read_bytes() == current_before

            _rewrite_source_truth_role(project, str(source["study_id"]), "SI")
            wrong_role_before = source_flow._tree_bytes(project)
            status, wrong_role = source_flow._request_bytes(
                base_url,
                preflight_route,
                _chemical_paper_zip(),
            )
            assert status in {400, 409}, wrong_role
            assert wrong_role["ok"] is False
            assert wrong_role["error_code"] == "PREFLIGHT_SOURCE_AMBIGUOUS"
            assert source_flow._tree_bytes(project) == wrong_role_before
            assert binding_path.read_bytes() == current_before
        finally:
            source_flow._stop_dashboard(server, thread)
