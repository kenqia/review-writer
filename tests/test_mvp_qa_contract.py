from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from review_writer.delivery.dual_parse_release import dual_parse_dashboard_projection
from review_writer.delivery.dual_parse_release import (
    confirm_chemical_paper_import,
    preflight_chemical_paper_import,
)
from review_writer.project.chemical_completion import (
    ChemicalCompletionError,
    apply_chemical_completion_batch,
    chemical_completion_state,
    require_honest_progressive_projection,
)
from review_writer.project.content_agent_handoff import (
    ContentAgentError,
    build_content_task_package,
)
from review_writer.project.dual_parse_bootstrap import (
    bind_generic_parse_outputs,
    bootstrap_dual_parse_project,
)
from review_writer.project.dual_source import write_dual_source_binding
from review_writer.project.parse_quality import (
    apply_parse_quality_decision,
    parse_quality_state,
)
from review_writer.project.parse_reconciliation import write_parse_reconciliation
from review_writer.project.source_truth import load_source_truth_bundle

from test_chemical_paper_import import ACTOR, v2000, write_chemical_zip
from test_dual_parse_bootstrap import generic_output
from test_dual_source import dual_project
from test_parse_reconciliation import reconciliation_project


CONTRACT = Path(__file__).resolve().parents[1] / "docs/qa/mvp-three-paper-qa-contract.md"
ACTOR_PAYLOAD = {
    "actor_type": "simulated_researcher_agent",
    "actor_label": "simulated_researcher",
}


def _pdf(path: Path, index: int) -> dict[str, object]:
    payload = f"%PDF-1.7\nmvp-main-{index}\n%%EOF\n".encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {
        "study_id": f"mvp-study-{index}",
        "source_id": f"mvp-source-{index}",
        "doi": f"10.1000/mvp-{index}",
        "title": f"MVP study {index}",
        "tier": "core",
        "document_role": "MAIN",
        "pdf_input_path": str(path),
        "expected_pdf_sha256": hashlib.sha256(payload).hexdigest(),
    }


def _request(root: Path, *, project_id: str = "mvp-three-paper") -> dict[str, object]:
    return {
        "schema_version": "dual-parse-bootstrap-request.v1",
        "project_id": project_id,
        "brief": {"topic": "MVP synthetic three-paper review"},
        "sources": [_pdf(root / "inputs" / f"paper-{index}.pdf", index) for index in range(3)],
    }


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _three_paper_generic_project(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    request = _request(tmp_path)
    project = bootstrap_dual_parse_project(tmp_path / "review-projects", request)
    result = bind_generic_parse_outputs(
        project,
        generic_output(tmp_path / "generic-output", request),
    )
    assert result["completed_count"] == 3
    for source in request["sources"]:
        _approve_generic_parse(project, source["study_id"])
    return project, request


def _approve_generic_parse(project: Path, study_id: str) -> None:
    state = parse_quality_state(project, study_id)
    for row in state["objects"]:
        current = next(item for item in state["objects"] if item["object_id"] == row["object_id"])
        if current["status"] == "usable":
            continue
        action = (
            "pdf_locator_only"
            if current["status"] in {"incomplete", "failed"}
            else "approve_candidate_extraction"
        )
        payload = {
            "object_id": current["object_id"],
            "object_digest": current["object_digest"],
            "gate_digest": state["gate_digest"],
            "action": action,
            "note": "Compared with the synthetic Generic Parse fixture.",
        }
        if action == "pdf_locator_only":
            payload["pdf_resolution"] = {
                "pages": [1],
                "source_scope": "Synthetic PDF locator for the contract fixture.",
                "limitations": "Parsed content is excluded from downstream use.",
            }
        state = apply_parse_quality_decision(project, study_id, payload)
    assert state["workflow_can_continue"] is True


def _import_three_chemical_inputs(
    tmp_path: Path, project: Path, request: dict[str, object]
) -> None:
    for index, source in enumerate(request["sources"]):
        study_id = source["study_id"]
        source_sha = load_source_truth_bundle(project, study_id)["sources"][0]["pdf"]["sha256"]
        archive = write_chemical_zip(
            tmp_path / f"chemical-{index}.zip",
            pages=1,
            molecules=[
                {
                    "mol_id": f"mvp-mol-{index}",
                    "page_idx": 0,
                    "bbox_normalized": [0.1, 0.2, 0.3, 0.4],
                    "smiles_expanded": "CO",
                    "smiles_unexpanded": "CO",
                    "mol_idt": f"compound {index + 1}",
                    "mol_block": v2000(),
                }
            ],
        )
        preflight = preflight_chemical_paper_import(project, study_id, archive.read_bytes())
        confirm_chemical_paper_import(
            project,
            {
                "study_id": study_id,
                "preflight_token": preflight["preflight_token"],
                **ACTOR,
            },
        )


def test_mvp_contract_is_explicit_and_does_not_reintroduce_legacy_hard_gates() -> None:
    text = CONTRACT.read_text(encoding="utf-8")

    for required in (
        "3 个已验证",
        "3 个与对应 study 绑定",
        "3 个正式 preflight → confirm → import",
        "3 个 current",
        "CONFIRMED",
        "AI_PROVISIONAL",
        "BLOCKED",
        "Evidence",
        "Synthesis",
        "zero-write",
        "DOCX/PDF",
        "fresh",
        "不猜 SMILES",
    ):
        assert required in text

    assert "19 checkpoint" in text
    assert "不把旧协议的重启、浏览器历史或复杂恢复步骤设为 MVP 硬门" in text
    assert "必须同时闭合" in text


def test_three_by_three_by_three_by_three_inputs_bind_to_fresh_project(tmp_path: Path) -> None:
    project, request = _three_paper_generic_project(tmp_path)

    main_pdfs = sorted((project / "00_sources/papers").glob("*.pdf"))
    assert len(main_pdfs) == 3
    assert len(json.loads((project / "00_sources/source_coverage.json").read_text())["studies"]) == 3
    assert all(
        row["si_policy"] == "REQUIRED" and row["study_status"] == "PARTIAL"
        for row in json.loads(
            (project / "00_sources/source_coverage.json").read_text(encoding="utf-8")
        )["studies"]
    )

    si_root = tmp_path / "supplements"
    si_files = []
    for index in range(3):
        path = si_root / f"study-{index}.si.pdf"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"%PDF-1.7\nmvp-si-{index}\n%%EOF\n".encode())
        si_files.append(path)
    assert len(si_files) == 3

    _import_three_chemical_inputs(tmp_path, project, request)
    chemical_states = [
        load_chemical_state(project, source["study_id"])
        for source in request["sources"]
    ]
    assert len(chemical_states) == 3
    assert all(state["source_pdf_sha256"] for state in chemical_states)

    bindings = [
        write_dual_source_binding(project, source["study_id"])
        for source in request["sources"]
    ]
    assert len(bindings) == 3
    assert all(binding["status"] == "current" for binding in bindings)
    assert all(binding["generic"]["source_pdf_sha256"] == binding["chemical"]["source_pdf_sha256"] for binding in bindings)


def load_chemical_state(project: Path, study_id: str) -> dict[str, object]:
    from review_writer.project.chemical_paper import load_chemical_paper_state

    return load_chemical_paper_state(project, study_id)


def test_honest_progressive_tri_state_rejects_guess_and_preserves_gap(tmp_path: Path) -> None:
    project = dual_project(tmp_path)
    gate = chemical_completion_state(project, "scholarly-a")
    assert gate["route"] == "honest_progressive"
    assert {row["resolved_smiles_status"] for row in gate["molecules"]} <= {
        "CONFIRMED",
        "AI_PROVISIONAL",
        "BLOCKED",
    }

    before = _snapshot(project)
    with pytest.raises(ChemicalCompletionError):
        apply_chemical_completion_batch(
            project,
            "scholarly-a",
            {
                "version_token": gate["version_token"],
                **ACTOR_PAYLOAD,
                "corrections": [
                    {
                        "molecule_index": 0,
                        "field": "resolved_smiles",
                        "value": "guessed-smiles",
                        "resolution_status": "CONFIRMED",
                        "reason": "Unsupported guess.",
                        "pdf_locator": {"page": 1},
                    }
                ],
            },
        )
    assert _snapshot(project) == before

    current = chemical_completion_state(project, "scholarly-a")
    for row in current["molecules"]:
        if row["resolved_smiles_status"] == "BLOCKED":
            assert row["resolved_smiles"] is None
            assert row["gap_reason"]
    assert require_honest_progressive_projection(project, "scholarly-a") == current["gate_digest"]


def test_evidence_and_synthesis_boundaries_fail_closed_without_current_inputs(tmp_path: Path) -> None:
    project = reconciliation_project(tmp_path)
    write_parse_reconciliation(project, "scholarly-a")

    package_root = tmp_path / "candidate-package"
    request = {
        "schema_version": "content-agent-request.v1",
        "request_kind": "paper_evidence",
        "project_id": project.name,
        "target_ids": ["scholarly-a"],
        "field_dependencies": ["smiles"],
        "reason": "MVP boundary test.",
    }
    with pytest.raises(ContentAgentError):
        build_content_task_package(project, request, package_root)
    assert not package_root.exists()


def test_dashboard_projection_unknown_state_is_not_ready_or_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    import view.serve_review_dashboard as dashboard

    def unavailable(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("authority unavailable")

    monkeypatch.setattr(dashboard, "project_chemical_completion_state", unavailable)
    monkeypatch.setattr(dashboard, "chemical_paper_projection", unavailable)
    projected = dashboard.project_honest_progressive_dashboard_projection(
        Path("."),
        {"schema_version": "dual-parse-projection.v2", "studies": []},
    )
    summary = projected["honest_progressive"]
    assert summary["availability"] == "unknown"
    assert summary["status"] == "unknown"
    assert summary["coverage_denominator"] is None
    assert summary["confirmed_count"] is None
    assert summary["ai_provisional_count"] is None
    assert summary["blocked_count"] is None
    assert summary["coverage_ratio"] is None
    assert summary["gap_registry"] is None
    assert "待 Chemical Paper 导入" in summary["availability_reason"]
    assert "ready" not in json.dumps(summary, ensure_ascii=False).casefold()


def test_researcher_projection_and_artifact_contract_do_not_leak_private_data(
    tmp_path: Path,
) -> None:
    projection = dual_parse_dashboard_projection(dual_project(tmp_path))
    encoded = json.dumps(projection, ensure_ascii=False).casefold()
    for forbidden in (
        "/private/",
        "raw_json",
        "molblock",
        "opaque-token",
        "opaque-session",
        "cp-preflight-v1.",
    ):
        assert forbidden not in encoded


def test_final_artifact_audit_is_explicit_in_contract() -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    assert "不是旧稿重打包" in text
    assert "DOCX integrity" in text
    assert "PDF/页面产物存在" in text
