from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import time
import os
from pathlib import Path

import pytest

import review_writer.project.vertical_review as vertical_review
from test_source_truth import _source_truth_project
from review_writer.project.paper_evidence import (
    PaperEvidenceError,
    apply_paper_evidence_decision,
    paper_evidence_state,
    register_paper_evidence_candidates,
)
from review_writer.project.parse_quality import (
    apply_parse_quality_decision,
    parse_quality_state,
    write_parse_quality_gate,
)
from review_writer.project.source_truth import write_source_truth_bundle
from review_writer.project.vertical_review import (
    VerticalReviewError,
    apply_risk_decisions,
    benchmark_metrics,
    build_risk_packet,
    build_writer_packet,
    initialize_review,
    rebuild_projection,
    register_study,
)
from review_writer.project.workflow_projection import workflow_state


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI = REPO_ROOT / "scripts" / "run_vertical_review.py"


def _evidence_ref(study_id: str) -> dict:
    return {
        "source_id": f"SOURCE-{study_id}",
        "page": 1,
        "section_or_item": "Results",
        "exact_quote": "Synthetic source observation.",
    }


def _claim(
    claim_id: str,
    *,
    text: str | None = None,
    risk_level: str = "R1",
    risk_categories: list[str] | None = None,
) -> dict:
    return {
        "claim_id": claim_id,
        "claim_text": text or f"Synthetic claim {claim_id}.",
        "risk_level": risk_level,
        "risk_categories": list(risk_categories or []),
        "evidence_refs": [_evidence_ref(claim_id)],
    }


def _reaction_unit(reaction_unit_id: str) -> dict:
    return {"reaction_unit_id": reaction_unit_id}


def _candidate(
    study_id: str,
    claims: list[dict],
    *,
    reaction_units: list[dict] | None = None,
) -> dict:
    candidate = {
        "schema_version": "evidence-candidate.v2",
        "job_id": f"JOB-{study_id}",
        "study_id": study_id,
        "claims": claims,
    }
    if reaction_units is not None:
        candidate["reaction_units"] = reaction_units
    return candidate


def _r0(study_id: str, status: str = "R0_PASS", **extra) -> dict:
    job_id = f"JOB-{study_id}"
    return {
        "candidate_job_id": job_id,
        "job_id": job_id,
        "status": status,
        **extra,
    }


def _reviewer(study_id: str, verdict: str = "SUPPORT", **extra) -> dict:
    return {
        "job_id": f"JOB-{study_id}",
        "study_id": study_id,
        "verdict": verdict,
        **extra,
    }


def _finding(target_id: str, verdict: str = "SUPPORT", reason: str = "Grounded.") -> dict:
    return {"target_id": target_id, "verdict": verdict, "reason": reason}


def _initialize(tmp_path: Path) -> Path:
    return initialize_review(tmp_path, "synthetic-review", {"topic": "Synthetic review"})


def _initialization_files(project: Path) -> set[str]:
    return {
        path.relative_to(project).as_posix()
        for path in project.rglob("*")
        if path.is_file()
    }


def _file_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _write_prepare_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _prepare_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _request_set_digest(requests: list[dict]) -> str:
    return hashlib.sha256(
        json.dumps(
            requests,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _expected_sealed_job_id(job: dict) -> str:
    source_files = [
        {
            key: source[key]
            for key in (
                "document_role",
                "layout_sha256",
                "reading_order_sha256",
                "source_binary_sha256",
                "source_id",
            )
        }
        for source in job["source_files"]
    ]
    source_files.sort(key=lambda row: (row["document_role"], row["source_id"]))
    payload = {
        "mode": job["mode"],
        "schema_version": job["schema_version"],
        "semantic_target_contract": job["semantic_target_contract"],
        "source_files": source_files,
        "study": job["study"],
        "target_namespace": job.get("target_namespace"),
    }
    return "JOB-" + hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
    ).hexdigest()


def _canonical_prepare_project(
    tmp_path: Path,
    *,
    study_id: str = "STUDY-CANARY",
    si_policy: str = "NOT_REQUIRED",
    si_dependent_claim_ids: list[str] | None = None,
    main_pdf_bytes: bytes | None = None,
    with_parse_gate: bool = True,
) -> Path:
    project = _initialize(tmp_path)
    doi = "10.1000/canary.test"
    _write_prepare_json(
        project / "00_discovery/candidate_pool.json",
        {
            "candidates": [
                {
                    "candidate_id": study_id,
                    "doi": f"https://doi.org/{doi}.",
                    "si_policy": si_policy,
                    "si_dependent_claim_ids": list(si_dependent_claim_ids or []),
                }
            ]
        },
    )
    _write_prepare_json(
        project / "00_discovery/screening_decisions.json",
        {"decisions": [{"candidate_id": study_id, "disposition": "INCLUDE_FOR_FULL_TEXT"}]},
    )
    acquired: dict[str, dict[str, str]] = {}
    completed = []
    text_sources = []
    for role, source_id, text in (
        ("MAIN", "CANARY_MAIN", "Main evidence paragraph."),
        ("SI", "CANARY_SI", "Supporting information paragraph."),
    ):
        relative_pdf = f"sources/{study_id}/{role}.pdf"
        pdf = project / "00_sources" / relative_pdf
        pdf.parent.mkdir(parents=True, exist_ok=True)
        pdf.write_bytes(
            main_pdf_bytes
            if role == "MAIN" and main_pdf_bytes is not None
            else f"synthetic {role} pdf bytes\n".encode()
        )
        acquired[role] = {"path": relative_pdf, "sha256": _prepare_sha256(pdf)}
        markdown = project / f"01_evidence/mineru/markdown/{source_id}.md"
        markdown.parent.mkdir(parents=True, exist_ok=True)
        markdown.write_text(f"# Parsed {role}\n", encoding="utf-8")
        parse_markdown = project / f"01_evidence/parses/markdown/{source_id}.md"
        parse_markdown.parent.mkdir(parents=True, exist_ok=True)
        parse_markdown.write_text(f"# Parsed {role}\n", encoding="utf-8")
        extracted = project / f"01_evidence/parses/extracted/{source_id}"
        extracted.mkdir(parents=True, exist_ok=True)
        (extracted / "full.md").write_text(f"# Parsed {role}\n", encoding="utf-8")
        _write_prepare_json(
            extracted / f"{source_id}_content_list.json",
            [
                {
                    "bbox": [1, 2, 3, 4],
                    "page_idx": 0,
                    "text": f"Parsed {role}",
                    "text_level": 1,
                    "type": "text",
                }
            ],
        )
        _write_prepare_json(extracted / "layout.json", {"pages": [{"page_idx": 0}]})
        completed.append({
            "markdown_copy": rf"C:\runtime\mineru\markdown\{source_id}.md",
            "relative_pdf_path": relative_pdf,
            "slug": source_id,
            "state": "done",
        })
        reading = project / f"01_evidence/text_layers/{source_id}.reading.txt"
        layout = project / f"01_evidence/text_layers/{source_id}.layout.txt"
        reading.parent.mkdir(parents=True, exist_ok=True)
        reading.write_text(text + "\f", encoding="utf-8")
        layout.write_text(f"{role} visual locator.\f", encoding="utf-8")
        text_sources.append(
            {
                "layout_path": layout.name,
                "layout_sha256": _prepare_sha256(layout),
                "page_count": 1,
                "pdf_sha256": _prepare_sha256(pdf),
                "reading_order_path": reading.name,
                "reading_order_sha256": _prepare_sha256(reading),
                "source_id": source_id,
            }
        )
    downloads = [
        {
            "document_role": role,
            "doi": doi,
            "download_id": f"{study_id}_{role}",
            "expected_sha256": acquired[role]["sha256"],
            "study_id": study_id,
        }
        for role in ("MAIN", "SI")
    ]
    requests = [
        {
            "document_role": row["document_role"],
            "doi": row["doi"],
            "pdf_sha256": row["expected_sha256"],
            "study_id": row["study_id"],
        }
        for row in downloads
    ]
    _write_prepare_json(
        project / "00_discovery/acquisition_manifest.json",
        {"schema_version": "case02-acquisition-plan.v1", "downloads": downloads},
    )
    _write_prepare_json(
        project / "00_sources/reusable_library_audit.json",
        {
            "schema_version": "reusable-library-audit.v1",
            "canonical_artifact": "00_sources/reusable_library_audit.json",
            "library_status": "NOT_DECLARED",
            "request_set_digest": _request_set_digest(requests),
            "required_parser_contract": "mineru-v2",
            "results": [
                {
                    "assets": {},
                    "document_role": request["document_role"],
                    "library_id": None,
                    "match_basis": "DOI",
                    "reason": "NO_LIBRARY_MATCH",
                    "status": "NOT_REUSABLE",
                    "study_id": request["study_id"],
                }
                for request in requests
            ],
        },
    )
    _write_prepare_json(
        project / "00_sources" / "acquisition_final_receipt.json",
        {
            "studies": [
                {
                    "study_id": study_id,
                    "doi": f"DOI:{doi}",
                    "main_pdf": acquired["MAIN"],
                    "si_pdf": acquired["SI"],
                    "status": "ACQUIRED",
                }
            ]
        },
    )
    _write_prepare_json(
        project / "00_sources" / "source_identity_audit.json",
        {"results": [{"doi": doi, "verdict": "PASS"}]},
    )
    _write_prepare_json(
        project / "00_sources" / "source_coverage.json",
        {
            "canonical_artifact": "00_sources/source_coverage.json",
            "schema_version": "source-coverage.v1",
            "studies": [
                {
                    "available_roles": ["MAIN", "SI"],
                    "blocked_claim_ids": [],
                    "blocking_reasons": [],
                    "limitations": [],
                    "main_policy": "MAIN_REQUIRED",
                    "si_policy": si_policy,
                    "study_id": study_id,
                    "study_status": "READY",
                }
            ],
        },
    )
    _write_prepare_json(
        project / "01_evidence/mineru/manifest.json",
        {"completed": list(reversed(completed)), "failed": []},
    )
    _write_prepare_json(
        project / "01_evidence/text_layers/text_layers.manifest.json",
        {"schema_version": "pdf-text-layers.v1", "sources": list(reversed(text_sources))},
    )
    if with_parse_gate:
        write_source_truth_bundle(project, study_id)
        write_parse_quality_gate(project, study_id)
        state = parse_quality_state(project, study_id)
        for row in state["objects"]:
            if row["status"] == "usable":
                continue
            state = apply_parse_quality_decision(
                project,
                study_id,
                {
                    "action": (
                        "pdf_locator_only"
                        if row["status"] in {"incomplete", "failed"}
                        else "approve_candidate_extraction"
                    ),
                    "gate_digest": state["gate_digest"],
                    "note": "Synthetic fixture verified against its source page.",
                    "object_id": row["object_id"],
                },
            )
    return project


def _run_prepare(project: Path, study_id: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), "prepare-study", "--project-dir", str(project), "--study-id", study_id],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _run_source_truth(project: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), "build-source-truth", "--project", str(project)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _refresh_and_approve_parse_gate(project: Path, study_id: str) -> dict[str, object]:
    write_source_truth_bundle(project, study_id)
    write_parse_quality_gate(project, study_id)
    state = parse_quality_state(project, study_id)
    for row in state["objects"]:
        if row["status"] == "usable":
            continue
        state = apply_parse_quality_decision(
            project,
            study_id,
            {
                "action": (
                    "pdf_locator_only"
                    if row["status"] in {"incomplete", "failed"}
                    else "approve_candidate_extraction"
                ),
                "gate_digest": state["gate_digest"],
                "note": "Synthetic fixture rechecked after source-set change.",
                "object_id": row["object_id"],
            },
        )
    return state


def test_build_source_truth_command_writes_a_gate_per_declared_study(tmp_path: Path) -> None:
    project = _canonical_prepare_project(tmp_path, with_parse_gate=False)

    result = _run_source_truth(project)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "command": "build-source-truth",
        "needs_review": 1,
        "project_id": project.name,
        "status": "NEEDS_REVIEW",
        "study_count": 1,
    }
    bundle = json.loads(
        (project / "01_evidence/source_truth/STUDY-CANARY/bundle.json").read_text(
            encoding="utf-8"
        )
    )
    gate = json.loads(
        (project / "01_evidence/source_truth/STUDY-CANARY/parse_quality.json").read_text(
            encoding="utf-8"
        )
    )
    assert gate["bundle_digest"] == bundle["bundle_digest"]


def test_prepare_study_requires_parse_quality_gate(tmp_path: Path) -> None:
    project = _canonical_prepare_project(tmp_path, with_parse_gate=False)
    write_source_truth_bundle(project, "STUDY-CANARY")

    result = _run_prepare(project, "STUDY-CANARY")

    assert result.returncode == 3, result.stderr
    assert json.loads(result.stdout)["reason_code"] == "PARSE_QUALITY_MISSING"
    assert not (project / "01_evidence/STUDY-CANARY").exists()


def test_pdf_locator_decision_never_creates_provider_packet(tmp_path: Path) -> None:
    project = _canonical_prepare_project(tmp_path)
    state = parse_quality_state(project, "STUDY-CANARY")
    target = next(row for row in state["objects"] if row["status"] == "usable_with_review")
    apply_parse_quality_decision(
        project,
        "STUDY-CANARY",
        {
            "action": "pdf_locator_only",
            "gate_digest": state["gate_digest"],
            "note": "Use only the original PDF for this object.",
            "object_id": target["object_id"],
        },
    )

    result = _run_prepare(project, "STUDY-CANARY")

    assert result.returncode == 3, result.stderr
    assert json.loads(result.stdout)["reason_code"] == "PARSE_PDF_LOCATOR_ONLY"
    assert not (project / "01_evidence/STUDY-CANARY").exists()


def test_gate_digest_change_invalidates_the_old_sealed_job_id(tmp_path: Path) -> None:
    project = _canonical_prepare_project(tmp_path)
    first = _run_prepare(project, "STUDY-CANARY")
    assert first.returncode == 0, first.stderr
    packet = project / "01_evidence/STUDY-CANARY"
    first_job = json.loads((packet / "sealed_job.json").read_text(encoding="utf-8"))

    for relative in (
        "01_evidence/mineru/markdown/CANARY_MAIN.md",
        "01_evidence/parses/markdown/CANARY_MAIN.md",
        "01_evidence/parses/extracted/CANARY_MAIN/full.md",
    ):
        (project / relative).write_text("# Parsed MAIN changed\n", encoding="utf-8")
    write_source_truth_bundle(project, "STUDY-CANARY")
    write_parse_quality_gate(project, "STUDY-CANARY")
    state = parse_quality_state(project, "STUDY-CANARY")
    for row in state["objects"]:
        if row["status"] != "usable":
            state = apply_parse_quality_decision(
                project,
                "STUDY-CANARY",
                {
                    "action": "approve_candidate_extraction",
                    "gate_digest": state["gate_digest"],
                    "note": "Rechecked after the parse changed.",
                    "object_id": row["object_id"],
                },
            )
    for path in packet.iterdir():
        path.unlink()
    packet.rmdir()

    second = _run_prepare(project, "STUDY-CANARY")

    assert second.returncode == 0, second.stderr
    second_job = json.loads((packet / "sealed_job.json").read_text(encoding="utf-8"))
    assert first_job["semantic_target_contract"]["parse_quality_gate_digest"] != (
        second_job["semantic_target_contract"]["parse_quality_gate_digest"]
    )
    assert first_job["job_id"] != second_job["job_id"]


def _authoritative_bytes(project: Path) -> dict[str, bytes]:
    relative_paths = (
        "00_brief/review_state.json",
        "01_evidence/evidence_cards.jsonl",
        "01_evidence/exception_queue.json",
        "02_claims/claim_projection.jsonl",
        "02_claims/writer_packet.json",
        "03_review/risk_packet.json",
        "03_review/risk_decisions.json",
    )
    return {
        relative: (project / relative).read_bytes()
        for relative in relative_paths
        if (project / relative).is_file()
    }


def _bound_decision(project: Path, claim_id: str, action: str, **extra) -> dict:
    projection = [
        json.loads(line)
        for line in (project / "02_claims" / "claim_projection.jsonl").read_text().splitlines()
        if line.strip()
    ]
    digest = next(
        row["review_target_digest"] for row in projection if row["claim_id"] == claim_id
    )
    return {
        "action": action,
        "claim_id": claim_id,
        "review_target_digest": digest,
        **extra,
    }


def _packet_bound(project: Path, decisions: list[dict]) -> dict:
    packet = json.loads((project / "03_review" / "risk_packet.json").read_text())
    return {"packet_digest": packet["packet_digest"], "decisions": decisions}


def _complete_risk_review(
    project: Path,
    *,
    actions: dict[str, str] | None = None,
) -> dict:
    state = json.loads((project / "00_brief" / "review_state.json").read_text())
    if state.get("status") == vertical_review.AWAITING_BRIEF_CONFIRMATION:
        vertical_review.confirm_review_brief(project)
    packet = build_risk_packet(project)
    if packet["targets"]:
        decisions = [
            _bound_decision(
                project,
                target["claim_id"],
                (actions or {}).get(target["claim_id"], "APPROVE"),
            )
            for target in packet["targets"]
        ]
        apply_risk_decisions(project, _packet_bound(project, decisions))
    return packet


def test_initialize_awaits_brief_confirmation_without_discovery_side_effects(
    tmp_path: Path,
) -> None:
    project = _initialize(tmp_path)

    state = json.loads((project / "00_brief" / "review_state.json").read_text())

    assert state == {
        "blockers": [],
        "brief": {"topic": "Synthetic review"},
        "counts": {"claims": 0, "evidence": 0, "sources": 0},
        "current_stage": "review_brief",
        "project_id": "synthetic-review",
        "schema_version": "vertical-review-state.v1",
        "status": "AWAITING_BRIEF_CONFIRMATION",
    }
    assert not (project / "00_discovery").exists()


def test_confirm_review_brief_is_idempotent_and_preserves_scope(tmp_path: Path) -> None:
    project = _initialize(tmp_path)
    initial = json.loads((project / "00_brief" / "review_state.json").read_text())

    confirmed = vertical_review.confirm_review_brief(project)

    assert confirmed["brief"] == initial["brief"]
    assert confirmed["status"] == "BRIEF_CONFIRMED"
    assert confirmed["current_stage"] == "ready_for_discovery"
    assert not (project / "00_discovery").exists()
    confirmed_bytes = (project / "00_brief" / "review_state.json").read_bytes()

    assert vertical_review.confirm_review_brief(project) == confirmed
    assert (project / "00_brief" / "review_state.json").read_bytes() == confirmed_bytes


def _assert_brief_rejected_without_side_effects(tmp_path: Path, brief: object) -> None:
    review_root = tmp_path / "review-projects"
    try:
        with pytest.raises(VerticalReviewError, match="BRIEF_INVALID"):
            initialize_review(review_root, "invalid-review", brief)  # type: ignore[arg-type]
    finally:
        assert not review_root.exists()


@pytest.mark.parametrize(
    "brief",
    (
        {},
        {"review_question": "Missing topic"},
        {"topic": ""},
        {"topic": "   "},
        {"topic": 7},
        {"topic": True},
    ),
)
def test_initialize_rejects_missing_or_invalid_topic_without_side_effects(
    tmp_path: Path,
    brief: object,
) -> None:
    _assert_brief_rejected_without_side_effects(tmp_path, brief)


@pytest.mark.parametrize(
    "field",
    ("review_question", "output_language", "audience", "scope", "review_status"),
)
@pytest.mark.parametrize("value", ("", "   ", 7, True))
def test_initialize_rejects_invalid_known_optional_strings_without_side_effects(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    _assert_brief_rejected_without_side_effects(
        tmp_path,
        {"topic": "Synthetic review", field: value},
    )


@pytest.mark.parametrize(
    "brief",
    (
        {"topic": "Synthetic review", "from_year": 2020},
        {"topic": "Synthetic review", "to_year": 2020},
        {"topic": "Synthetic review", "from_year": True, "to_year": 2020},
        {"topic": "Synthetic review", "from_year": 0, "to_year": 2020},
        {"topic": "Synthetic review", "from_year": 2020, "to_year": 10000},
        {"topic": "Synthetic review", "from_year": 2021, "to_year": 2020},
        {"topic": "Synthetic review", "target_primary_studies": True},
        {"topic": "Synthetic review", "target_primary_studies": 0},
        {"topic": "Synthetic review", "target_primary_studies": "24"},
        {"topic": "Synthetic review", "acceptable_core_range": [20]},
        {"topic": "Synthetic review", "acceptable_core_range": [True, 30]},
        {"topic": "Synthetic review", "acceptable_core_range": [0, 30]},
        {"topic": "Synthetic review", "acceptable_core_range": [30, 20]},
        {
            "topic": "Synthetic review",
            "target_primary_studies": 31,
            "acceptable_core_range": [20, 30],
        },
    ),
)
def test_initialize_rejects_invalid_year_and_study_ranges_without_side_effects(
    tmp_path: Path,
    brief: object,
) -> None:
    _assert_brief_rejected_without_side_effects(tmp_path, brief)


@pytest.mark.parametrize("field", ("required_modes", "exclusions", "deliverables"))
@pytest.mark.parametrize(
    "value",
    (
        "not-an-array",
        [""],
        ["   "],
        ["valid", 7],
        ["duplicate", "duplicate"],
    ),
)
def test_initialize_rejects_invalid_brief_arrays_without_side_effects(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    _assert_brief_rejected_without_side_effects(
        tmp_path,
        {"topic": "Synthetic review", field: value},
    )


def test_initialize_preserves_valid_unknown_brief_metadata(tmp_path: Path) -> None:
    brief = {
        "topic": "Synthetic review",
        "review_question": "What differs?",
        "output_language": "English",
        "audience": "Synthetic chemists",
        "scope": "A generic validation scope",
        "review_status": "draft",
        "from_year": 2001,
        "to_year": 2025,
        "target_primary_studies": 24,
        "acceptable_core_range": [20, 30],
        "required_modes": ["mode-a", "mode-b"],
        "exclusions": ["out-of-scope"],
        "deliverables": ["dynamic workbench", "editable DOCX"],
        "future_metadata": {"nested": [1, {"flag": True}]},
    }

    project = initialize_review(tmp_path, "synthetic-review", brief)
    state = json.loads((project / "00_brief" / "review_state.json").read_text())

    assert state["brief"] == brief


def test_initialize_repairs_state_only_project(tmp_path: Path) -> None:
    project = _initialize(tmp_path)
    state_path = project / "00_brief" / "review_state.json"
    state_bytes = state_path.read_bytes()
    for path in project.rglob("*"):
        if path.is_file() and path != state_path:
            path.unlink()

    repaired = _initialize(tmp_path)

    assert repaired == project
    assert state_path.read_bytes() == state_bytes
    assert _initialization_files(project) == {
        "00_brief/review_state.json",
        "01_evidence/evidence_cards.jsonl",
        "01_evidence/exception_queue.json",
        "02_claims/claim_projection.jsonl",
        "03_review/risk_decisions.json",
    }


def test_initialize_completes_valid_pre_state_partial_project(tmp_path: Path) -> None:
    project = tmp_path / "synthetic-review"
    evidence_path = project / "01_evidence" / "evidence_cards.jsonl"
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_bytes(b"")

    initialized = _initialize(tmp_path)

    assert initialized == project
    assert _initialization_files(project) == {
        "00_brief/review_state.json",
        "01_evidence/evidence_cards.jsonl",
        "01_evidence/exception_queue.json",
        "02_claims/claim_projection.jsonl",
        "03_review/risk_decisions.json",
    }
    assert json.loads((project / "01_evidence" / "exception_queue.json").read_text()) == {
        "exceptions": []
    }


def test_initialize_rejects_project_root_symlink_without_touching_target(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside-root"
    queue_path = outside / "01_evidence" / "exception_queue.json"
    queue_path.parent.mkdir(parents=True)
    queue_path.write_text('{"exceptions": []}\n')
    before = _file_bytes(outside)
    (tmp_path / "synthetic-review").symlink_to(outside, target_is_directory=True)

    with pytest.raises(VerticalReviewError):
        _initialize(tmp_path)

    assert _file_bytes(outside) == before


def test_initialize_rejects_descendant_directory_symlink_without_touching_target(
    tmp_path: Path,
) -> None:
    project = tmp_path / "synthetic-review"
    project.mkdir()
    outside = tmp_path / "outside-evidence"
    queue_path = outside / "exception_queue.json"
    outside.mkdir()
    queue_path.write_text('{"exceptions": []}\n')
    before = _file_bytes(outside)
    (project / "01_evidence").symlink_to(outside, target_is_directory=True)

    with pytest.raises(VerticalReviewError):
        _initialize(tmp_path)

    assert _file_bytes(outside) == before
    assert not (project / "00_brief" / "review_state.json").exists()


@pytest.mark.parametrize(
    ("boundary", "operation"),
    [
        ("project", "metrics"),
        ("01_evidence", "register"),
        ("02_claims", "writer"),
        ("03_review", "risk"),
    ],
)
def test_project_operations_reject_symlink_boundaries_without_touching_target(
    tmp_path: Path,
    boundary: str,
    operation: str,
) -> None:
    project = _initialize(tmp_path)
    outside = tmp_path / f"outside-{boundary}"
    if boundary == "project":
        project.rename(outside)
        project.symlink_to(outside, target_is_directory=True)
    else:
        component = project / boundary
        component.rename(outside)
        component.symlink_to(outside, target_is_directory=True)
    before = _file_bytes(outside)

    with pytest.raises(VerticalReviewError):
        if operation == "metrics":
            benchmark_metrics(project)
        elif operation == "register":
            register_study(
                project,
                _candidate("STUDY-BOUNDARY", [_claim("CLAIM-BOUNDARY")]),
                _r0("STUDY-BOUNDARY"),
                _reviewer("STUDY-BOUNDARY"),
            )
        elif operation == "writer":
            build_writer_packet(project)
        else:
            build_risk_packet(project)

    assert _file_bytes(outside) == before


@pytest.mark.parametrize("invalid_kind", ["nonempty_object", "unknown_file"])
def test_initialize_rejects_invalid_or_unknown_existing_objects_without_writes(
    tmp_path: Path,
    invalid_kind: str,
) -> None:
    project = tmp_path / "synthetic-review"
    if invalid_kind == "nonempty_object":
        existing = project / "01_evidence" / "evidence_cards.jsonl"
        existing.parent.mkdir(parents=True)
        existing.write_text('{"study_id":"EXISTING"}\n')
    else:
        existing = project / "notes.txt"
        project.mkdir(parents=True)
        existing.write_text("existing work")
    before = existing.read_bytes()

    with pytest.raises(VerticalReviewError):
        _initialize(tmp_path)

    assert existing.read_bytes() == before
    assert _initialization_files(project) == {existing.relative_to(project).as_posix()}


def test_r1_supported_grounded_claim_is_approved(tmp_path: Path) -> None:
    project = _initialize(tmp_path)

    card = register_study(
        project,
        _candidate("STUDY-1", [_claim("CLAIM-1")]),
        _r0("STUDY-1", findings=[]),
        _reviewer("STUDY-1", review_id="REVIEW-1"),
    )

    assert card["study_id"] == "STUDY-1"
    projection = card["claim_projection"]
    assert len(projection) == 1
    assert projection[0]["claim_id"] == "CLAIM-1"
    assert projection[0]["decision"] == "APPROVED"
    assert projection[0]["lineage"]["study_id"] == "STUDY-1"
    assert projection[0]["lineage"]["source_locators"][0]["source_id"] == "SOURCE-CLAIM-1"


def test_r3_supported_claim_requires_human_review(tmp_path: Path) -> None:
    project = _initialize(tmp_path)

    result = register_study(
        project,
        _candidate("STUDY-R3", [_claim("CLAIM-R3", risk_level="R3")]),
        _r0("STUDY-R3"),
        _reviewer("STUDY-R3"),
    )

    assert result["claim_projection"][0]["decision"] == "HUMAN_REQUIRED"


def test_registration_updates_confirmed_project_state_from_canonical_projection(
    tmp_path: Path,
) -> None:
    project = _initialize(tmp_path)
    vertical_review.confirm_review_brief(project)

    register_study(
        project,
        _candidate("STUDY-STATE-A", [_claim("CLAIM-STATE-A")]),
        _r0("STUDY-STATE-A"),
        _reviewer("STUDY-STATE-A"),
    )
    state = json.loads((project / "00_brief" / "review_state.json").read_text())
    assert state["current_stage"] == "evidence_review"
    assert state["status"] == "in_progress"
    assert state["counts"] == {"claims": 1, "evidence": 1, "sources": 1}

    register_study(
        project,
        _candidate("STUDY-STATE-B", [_claim("CLAIM-STATE-B", risk_level="R3")]),
        _r0("STUDY-STATE-B"),
        _reviewer("STUDY-STATE-B"),
    )
    state = json.loads((project / "00_brief" / "review_state.json").read_text())
    assert state["current_stage"] == "evidence_review"
    assert state["status"] == "needs_human_review"
    assert state["counts"] == {"claims": 2, "evidence": 2, "sources": 2}


def test_registration_state_write_failure_is_recoverable_and_keeps_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _initialize(tmp_path)
    vertical_review.confirm_review_brief(project)
    state_path = project / "00_brief" / "review_state.json"
    state_before = state_path.read_bytes()
    candidate = _candidate("STUDY-STATE-RETRY", [_claim("CLAIM-STATE-RETRY")])
    r0_report = _r0("STUDY-STATE-RETRY")
    reviewer = _reviewer("STUDY-STATE-RETRY", verdict="AMBIGUOUS")
    original_write_json = vertical_review._write_json

    def fail_state(path: Path, value: object) -> None:
        if path == state_path:
            raise OSError("synthetic review-state write failure")
        original_write_json(path, value)

    with monkeypatch.context() as patch:
        patch.setattr(vertical_review, "_write_json", fail_state)
        with pytest.raises(OSError):
            register_study(project, candidate, r0_report, reviewer)

    assert state_path.read_bytes() == state_before
    queue = json.loads((project / "01_evidence" / "exception_queue.json").read_text())
    assert queue["exceptions"] == [
        {
            "error_code": "REVIEWER_NOT_SUPPORT",
            "r0_status": "R0_PASS",
            "reviewer_verdict": "AMBIGUOUS",
            "study_id": "STUDY-STATE-RETRY",
        }
    ]
    assert benchmark_metrics(project)["registered_study_count"] == 1

    register_study(project, candidate, r0_report, reviewer)
    state = json.loads(state_path.read_text())
    assert state["current_stage"] == "evidence_review"
    assert state["counts"] == {"claims": 1, "evidence": 1, "sources": 1}


def test_ambiguous_reviewer_blocks_low_risk_claim(tmp_path: Path) -> None:
    project = _initialize(tmp_path)

    result = register_study(
        project,
        _candidate("STUDY-AMBIGUOUS", [_claim("CLAIM-AMBIGUOUS")]),
        _r0("STUDY-AMBIGUOUS"),
        _reviewer("STUDY-AMBIGUOUS", verdict="AMBIGUOUS"),
    )

    assert result["claim_projection"][0]["decision"] == "BLOCKED"


def test_target_findings_do_not_block_supported_claim_when_study_root_is_reject(
    tmp_path: Path,
) -> None:
    project = _initialize(tmp_path)
    study_id = "STUDY-PARTIAL-REJECT"

    result = register_study(
        project,
        _candidate(
            study_id,
            [_claim("CLAIM-PARTIAL-A"), _claim("CLAIM-PARTIAL-B")],
            reaction_units=[_reaction_unit("REACTION-PARTIAL")],
        ),
        _r0(study_id),
        _reviewer(
            study_id,
            verdict="REJECT",
            findings=[
                _finding("REACTION-PARTIAL"),
                _finding("CLAIM-PARTIAL-A"),
                _finding("CLAIM-PARTIAL-B", verdict="REJECT", reason="Not supported."),
            ],
        ),
    )

    by_id = {row["claim_id"]: row for row in result["claim_projection"]}
    assert by_id["CLAIM-PARTIAL-A"]["decision"] == "APPROVED"
    assert by_id["CLAIM-PARTIAL-B"]["decision"] == "BLOCKED"
    queue = json.loads((project / "01_evidence" / "exception_queue.json").read_text())
    assert queue["exceptions"] == [
        {
            "error_code": "REVIEWER_NOT_SUPPORT",
            "r0_status": "R0_PASS",
            "reviewer_verdict": "REJECT",
            "study_id": study_id,
        }
    ]


def test_target_findings_apply_high_risk_gate_after_claim_support(
    tmp_path: Path,
) -> None:
    project = _initialize(tmp_path)
    study_id = "STUDY-PARTIAL-AMBIGUOUS"

    result = register_study(
        project,
        _candidate(
            study_id,
            [
                _claim("CLAIM-PARTIAL-R3", risk_level="R3"),
                _claim("CLAIM-PARTIAL-AMBIGUOUS"),
            ],
            reaction_units=[_reaction_unit("REACTION-PARTIAL-R3")],
        ),
        _r0(study_id),
        _reviewer(
            study_id,
            verdict="AMBIGUOUS",
            findings=[
                _finding("REACTION-PARTIAL-R3"),
                _finding("CLAIM-PARTIAL-R3"),
                _finding(
                    "CLAIM-PARTIAL-AMBIGUOUS",
                    verdict="AMBIGUOUS",
                    reason="Evidence is equivocal.",
                ),
            ],
        ),
    )

    by_id = {row["claim_id"]: row for row in result["claim_projection"]}
    assert by_id["CLAIM-PARTIAL-R3"]["decision"] == "HUMAN_REQUIRED"
    assert by_id["CLAIM-PARTIAL-AMBIGUOUS"]["decision"] == "BLOCKED"


@pytest.mark.parametrize(
    "tamper",
    (
        "not_list",
        "empty",
        "non_object",
        "unknown_target",
        "duplicate_target",
        "missing_coverage",
        "invalid_verdict",
        "invalid_verdict_type",
        "empty_reason",
        "root_mismatch",
    ),
)
def test_invalid_target_findings_fail_closed_into_exception_queue(
    tmp_path: Path,
    tamper: str,
) -> None:
    project = _initialize(tmp_path)
    study_id = f"STUDY-FINDINGS-{tamper.upper()}"
    candidate = _candidate(
        study_id,
        [_claim("CLAIM-FINDINGS-A"), _claim("CLAIM-FINDINGS-B")],
        reaction_units=[_reaction_unit("REACTION-FINDINGS")],
    )
    reviewer = _reviewer(
        study_id,
        findings=[
            _finding("REACTION-FINDINGS"),
            _finding("CLAIM-FINDINGS-A"),
            _finding("CLAIM-FINDINGS-B"),
        ],
    )
    if tamper == "not_list":
        reviewer["findings"] = {"target_id": "REACTION-FINDINGS"}
    elif tamper == "empty":
        reviewer["findings"] = []
    elif tamper == "non_object":
        reviewer["findings"][0] = "not-an-object"
    elif tamper == "unknown_target":
        reviewer["findings"][0]["target_id"] = "UNKNOWN-TARGET"
    elif tamper == "duplicate_target":
        reviewer["findings"][2]["target_id"] = "CLAIM-FINDINGS-A"
    elif tamper == "missing_coverage":
        reviewer["findings"].pop()
    elif tamper == "invalid_verdict":
        reviewer["findings"][0]["verdict"] = "ACCEPT_WITH_NOTES"
    elif tamper == "invalid_verdict_type":
        reviewer["findings"][0]["verdict"] = ["SUPPORT"]
    elif tamper == "empty_reason":
        reviewer["findings"][0]["reason"] = "   "
    else:
        reviewer["verdict"] = "AMBIGUOUS"

    with pytest.raises(VerticalReviewError) as error:
        register_study(project, candidate, _r0(study_id), reviewer)

    assert error.value.code == "REVIEWER_FINDINGS_INVALID"
    assert (project / "01_evidence" / "evidence_cards.jsonl").read_text() == ""
    assert (project / "02_claims" / "claim_projection.jsonl").read_text() == ""
    queue = json.loads((project / "01_evidence" / "exception_queue.json").read_text())
    assert queue["exceptions"] == [
        {
            "error_code": "REVIEWER_FINDINGS_INVALID",
            "r0_status": "R0_PASS",
            "reviewer_verdict": reviewer["verdict"],
            "study_id": study_id,
        }
    ]


@pytest.mark.parametrize(
    ("verdict", "expected_decision"),
    (("SUPPORT", "APPROVED"), ("REJECT", "BLOCKED"), ("AMBIGUOUS", "BLOCKED")),
)
def test_reviewer_without_findings_keeps_root_only_reduction(
    tmp_path: Path,
    verdict: str,
    expected_decision: str,
) -> None:
    project = _initialize(tmp_path)
    study_id = f"STUDY-ROOT-ONLY-{verdict}"

    result = register_study(
        project,
        _candidate(study_id, [_claim(f"CLAIM-ROOT-ONLY-{verdict}")]),
        _r0(study_id),
        _reviewer(study_id, verdict=verdict),
    )

    assert result["claim_projection"][0]["decision"] == expected_decision


@pytest.mark.parametrize(
    ("tamper", "code"),
    [
        ("candidate_job", "CANDIDATE_JOB_ID_INVALID"),
        ("r0_job", "R0_BINDING_INVALID"),
        ("r0_candidate_job", "R0_BINDING_INVALID"),
        ("reviewer_job", "REVIEWER_BINDING_INVALID"),
        ("reviewer_study", "REVIEWER_BINDING_INVALID"),
        ("reviewer_verdict", "REVIEWER_BINDING_INVALID"),
        ("reviewer_verdict_unknown", "REVIEWER_VERDICT_INVALID"),
    ],
)
def test_registration_rejects_identity_mismatch_into_exception_queue(
    tmp_path: Path,
    tamper: str,
    code: str,
) -> None:
    project = _initialize(tmp_path)
    candidate = _candidate("STUDY-BINDING", [_claim("CLAIM-BINDING")])
    r0_report = _r0("STUDY-BINDING")
    reviewer = _reviewer("STUDY-BINDING")
    if tamper == "candidate_job":
        candidate["job_id"] = ""
    elif tamper == "r0_job":
        r0_report["job_id"] = "JOB-OTHER"
    elif tamper == "r0_candidate_job":
        r0_report["candidate_job_id"] = "JOB-OTHER"
    elif tamper == "reviewer_job":
        reviewer["job_id"] = "JOB-OTHER"
    elif tamper == "reviewer_study":
        reviewer["study_id"] = "STUDY-OTHER"
    elif tamper == "reviewer_verdict":
        reviewer["verdict"] = ""
    else:
        reviewer["verdict"] = "ACCEPT_WITH_NOTES"

    with pytest.raises(VerticalReviewError) as error:
        register_study(project, candidate, r0_report, reviewer)

    assert error.value.code == code
    queue = json.loads((project / "01_evidence" / "exception_queue.json").read_text())
    assert len(queue["exceptions"]) == 1
    assert queue["exceptions"][0]["study_id"] == "STUDY-BINDING"
    assert queue["exceptions"][0]["error_code"] == code


def test_writer_packet_is_an_approved_only_whitelist(tmp_path: Path) -> None:
    project = _initialize(tmp_path)
    register_study(
        project,
        _candidate("STUDY-APPROVED", [_claim("CLAIM-APPROVED")]),
        _r0("STUDY-APPROVED"),
        _reviewer("STUDY-APPROVED"),
    )
    register_study(
        project,
        _candidate("STUDY-HUMAN", [_claim("CLAIM-HUMAN", risk_level="R3")]),
        _r0("STUDY-HUMAN"),
        _reviewer("STUDY-HUMAN"),
    )
    register_study(
        project,
        _candidate("STUDY-BLOCKED", [_claim("CLAIM-BLOCKED")]),
        _r0("STUDY-BLOCKED"),
        _reviewer("STUDY-BLOCKED", verdict="AMBIGUOUS"),
    )

    _complete_risk_review(project, actions={"CLAIM-HUMAN": "EXCLUDE"})
    packet = build_writer_packet(project)

    assert [claim["claim_id"] for claim in packet["claims"]] == ["CLAIM-APPROVED"]
    assert all(claim["decision"] == "APPROVED" for claim in packet["claims"])
    assert packet["approved_claim_count"] == 1
    assert packet["human_required_count"] == 0
    assert packet["blocked_count"] == 2
    assert packet["known_exclusions"]
    assert {row["claim_id"] for row in packet["known_exclusions"]} == {
        "CLAIM-BLOCKED",
        "CLAIM-HUMAN",
    }


def test_writer_packet_builds_one_original_comparative_evidence_figure(tmp_path: Path) -> None:
    project = _initialize(tmp_path)
    for index, mode in enumerate(("Photoredox", "Electrochemical"), start=1):
        study_id = f"STUDY-FIGURE-{index}"
        candidate = _candidate(study_id, [_claim(f"CLAIM-FIGURE-{index}")])
        candidate.update(
            {
                "activation_mode": mode,
                "citation": f"Synthetic study {index}",
                "reaction_class": "C-C bond formation",
            }
        )
        register_study(project, candidate, _r0(study_id), _reviewer(study_id))

    _complete_risk_review(project)
    packet = build_writer_packet(project)

    assert len(packet["figures"]) == 1
    figure = packet["figures"][0]
    assert figure["license"] == "ORIGINAL_GENERATED"
    assert figure["markdown_path"] == "../03_figure_redraw/comparative_evidence_map.png"
    image = project / "03_figure_redraw/comparative_evidence_map.png"
    assert image.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    manifest = json.loads(
        (project / "03_figure_redraw/figure_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["copied_source_images"] is False
    assert manifest["figures"][0]["source_claim_ids"] == [
        "CLAIM-FIGURE-1",
        "CLAIM-FIGURE-2",
    ]


def test_writer_packet_requires_explicit_rebuild_after_projection_or_decision_change(
    tmp_path: Path,
) -> None:
    project = _initialize(tmp_path)
    register_study(
        project,
        _candidate("STUDY-FRESHNESS", [_claim("CLAIM-FRESHNESS")]),
        _r0("STUDY-FRESHNESS"),
        _reviewer("STUDY-FRESHNESS"),
    )
    writer_path = project / "02_claims" / "writer_packet.json"
    _complete_risk_review(project)
    build_writer_packet(project)
    assert writer_path.is_file()

    rebuild_projection(project)
    assert not writer_path.exists()

    _complete_risk_review(project)
    build_writer_packet(project)
    packet = build_risk_packet(project)
    apply_risk_decisions(
        project,
        {
            "packet_digest": packet["packet_digest"],
            "decisions": [_bound_decision(project, "CLAIM-FRESHNESS", "EXCLUDE")],
        },
    )
    assert not writer_path.exists()
    rebuilt = build_writer_packet(project)
    assert rebuilt["claims"] == []


def test_register_replacement_invalidates_writer_packet_until_explicit_rebuild(
    tmp_path: Path,
) -> None:
    project = _initialize(tmp_path)
    study_id = "STUDY-REGISTER-FRESHNESS"
    claim_id = "CLAIM-REGISTER-FRESHNESS"
    register_study(
        project,
        _candidate(study_id, [_claim(claim_id, text="Initial text.")]),
        _r0(study_id),
        _reviewer(study_id),
    )
    writer_path = project / "02_claims" / "writer_packet.json"
    _complete_risk_review(project)
    build_writer_packet(project)
    assert writer_path.is_file()

    register_study(
        project,
        _candidate(study_id, [_claim(claim_id, text="Replacement text.")]),
        _r0(study_id),
        _reviewer(study_id),
    )

    assert not writer_path.exists()
    _complete_risk_review(project)
    rebuilt = build_writer_packet(project)
    assert rebuilt["claims"][0]["text"] == "Replacement text."


def test_writer_packet_records_current_projection_digest(tmp_path: Path) -> None:
    project = _initialize(tmp_path)
    result = register_study(
        project,
        _candidate("STUDY-PACKET-DIGEST", [_claim("CLAIM-PACKET-DIGEST")]),
        _r0("STUDY-PACKET-DIGEST"),
        _reviewer("STUDY-PACKET-DIGEST"),
    )
    _complete_risk_review(project)
    current_projection = [
        json.loads(line)
        for line in (project / "02_claims/claim_projection.jsonl").read_text().splitlines()
        if line.strip()
    ]
    expected = hashlib.sha256(
        json.dumps(
            current_projection,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    packet = build_writer_packet(project)

    assert packet["projection_sha256"] == expected


@pytest.mark.parametrize(
    "consumer",
    [build_writer_packet, build_risk_packet, benchmark_metrics],
    ids=["writer", "risk", "metrics"],
)
@pytest.mark.parametrize("tamper", ["forged", "text", "lineage"])
def test_projection_consumers_reject_any_non_authoritative_projection(
    tmp_path: Path,
    consumer,
    tamper: str,
) -> None:
    project = _initialize(tmp_path)
    result = register_study(
        project,
        _candidate("STUDY-TAMPER", [_claim("CLAIM-TAMPER")]),
        _r0("STUDY-TAMPER"),
        _reviewer("STUDY-TAMPER"),
    )
    if tamper == "forged":
        rows = [{"claim_id": "CLAIM-TAMPER", "decision": "APPROVED"}]
    else:
        rows = copy.deepcopy(result["claim_projection"])
        if tamper == "text":
            rows[0]["text"] = "Forged consumer wording."
        else:
            rows[0]["lineage"]["study_id"] = "FORGED-STUDY"
    projection_path = project / "02_claims" / "claim_projection.jsonl"
    projection_path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    tampered_bytes = projection_path.read_bytes()

    with pytest.raises(VerticalReviewError) as error:
        consumer(project)

    assert error.value.code == "PROJECTION_INVALID"
    assert projection_path.read_bytes() == tampered_bytes


def test_failed_third_study_is_queued_without_deleting_passing_cards(tmp_path: Path) -> None:
    project = _initialize(tmp_path)
    for index in (1, 2):
        register_study(
            project,
            _candidate(f"STUDY-{index}", [_claim(f"CLAIM-{index}")]),
            _r0(f"STUDY-{index}"),
            _reviewer(f"STUDY-{index}"),
        )
    cards_path = project / "01_evidence" / "evidence_cards.jsonl"
    passing_bytes = cards_path.read_bytes()

    with pytest.raises(VerticalReviewError) as error:
        register_study(
            project,
            _candidate("STUDY-BAD", [_claim("CLAIM-BAD")]),
            _r0("STUDY-BAD", status="R0_FAIL_GROUNDING_CONTRACT"),
            _reviewer("STUDY-BAD"),
        )

    assert error.value.code == "R0_REJECTED"
    assert cards_path.read_bytes() == passing_bytes
    cards = [json.loads(line) for line in passing_bytes.decode("utf-8").splitlines()]
    assert [card["study_id"] for card in cards] == ["STUDY-1", "STUDY-2"]
    queue = json.loads((project / "01_evidence" / "exception_queue.json").read_text())
    assert [entry["study_id"] for entry in queue["exceptions"]] == ["STUDY-BAD"]
    assert queue["exceptions"][0]["error_code"] == "R0_REJECTED"


def test_repeated_failure_upserts_one_exception_per_study(tmp_path: Path) -> None:
    project = _initialize(tmp_path)
    for _ in range(2):
        with pytest.raises(VerticalReviewError):
            register_study(
                project,
                _candidate("STUDY-RETRY", [_claim("CLAIM-RETRY")]),
                _r0("STUDY-RETRY", status="R0_FAIL_GROUNDING_CONTRACT"),
                _reviewer("STUDY-RETRY"),
            )

    queue = json.loads((project / "01_evidence" / "exception_queue.json").read_text())
    assert queue["exceptions"] == [
        {
            "error_code": "R0_REJECTED",
            "r0_status": "R0_FAIL_GROUNDING_CONTRACT",
            "reviewer_verdict": "SUPPORT",
            "study_id": "STUDY-RETRY",
        }
    ]
    with pytest.raises(VerticalReviewError):
        register_study(
            project,
            _candidate("STUDY-ALPHA", [_claim("CLAIM-ALPHA")]),
            _r0("STUDY-ALPHA", status="R0_FAIL_GROUNDING_CONTRACT"),
            _reviewer("STUDY-ALPHA"),
        )
    queue = json.loads((project / "01_evidence" / "exception_queue.json").read_text())
    assert [entry["study_id"] for entry in queue["exceptions"]] == [
        "STUDY-ALPHA",
        "STUDY-RETRY",
    ]


def test_successful_retry_clears_study_exception_and_metrics(tmp_path: Path) -> None:
    project = _initialize(tmp_path)
    candidate = _candidate("STUDY-RECOVERED", [_claim("CLAIM-RECOVERED")])
    with pytest.raises(VerticalReviewError):
        register_study(
            project,
            candidate,
            _r0("STUDY-RECOVERED", status="R0_FAIL_GROUNDING_CONTRACT"),
            _reviewer("STUDY-RECOVERED"),
        )

    register_study(
        project,
        candidate,
        _r0("STUDY-RECOVERED"),
        _reviewer("STUDY-RECOVERED"),
    )

    queue = json.loads((project / "01_evidence" / "exception_queue.json").read_text())
    assert queue["exceptions"] == []
    assert benchmark_metrics(project)["exception_count"] == 0


def test_risk_decisions_reduce_to_consumer_text_and_status_only(tmp_path: Path) -> None:
    project = _initialize(tmp_path)
    original_text = "Original approved wording."
    register_study(
        project,
        _candidate(
            "STUDY-RISK",
            [
                _claim("CLAIM-APPROVE", text=original_text, risk_level="R3"),
                _claim("CLAIM-REWORD", risk_level="R3"),
                _claim("CLAIM-EXCLUDE", risk_level="R3"),
                _claim("CLAIM-UNRESOLVED", risk_level="R3"),
            ],
        ),
        _r0("STUDY-RISK"),
        _reviewer("STUDY-RISK"),
    )
    cards_path = project / "01_evidence" / "evidence_cards.jsonl"
    evidence_bytes = cards_path.read_bytes()
    packet = build_risk_packet(project)

    projection = apply_risk_decisions(
        project,
        {
            "packet_digest": packet["packet_digest"],
            "decisions": [
                _bound_decision(project, "CLAIM-APPROVE", "APPROVE"),
                _bound_decision(
                    project,
                    "CLAIM-REWORD",
                    "REWORD",
                    approved_text="Human-approved wording.",
                ),
                _bound_decision(project, "CLAIM-EXCLUDE", "EXCLUDE"),
                _bound_decision(project, "CLAIM-UNRESOLVED", "UNRESOLVED"),
            ]
        },
    )

    by_id = {row["claim_id"]: row for row in projection}
    assert by_id["CLAIM-APPROVE"]["decision"] == "APPROVED"
    assert by_id["CLAIM-APPROVE"]["text"] == original_text
    assert by_id["CLAIM-REWORD"]["decision"] == "APPROVED"
    assert by_id["CLAIM-REWORD"]["text"] == "Human-approved wording."
    assert by_id["CLAIM-REWORD"]["original_text"] == "Synthetic claim CLAIM-REWORD."
    assert by_id["CLAIM-EXCLUDE"]["decision"] == "BLOCKED"
    assert by_id["CLAIM-UNRESOLVED"]["decision"] == "HUMAN_REQUIRED"
    assert cards_path.read_bytes() == evidence_bytes


def test_projection_and_risk_packet_bind_canonical_review_target_digest(
    tmp_path: Path,
) -> None:
    project = _initialize(tmp_path)
    result = register_study(
        project,
        _candidate("STUDY-DIGEST", [_claim("CLAIM-DIGEST", risk_level="R3")]),
        _r0("STUDY-DIGEST"),
        _reviewer("STUDY-DIGEST"),
    )
    row = result["claim_projection"][0]
    digest_payload = {
        key: row[key]
        for key in (
            "claim_id",
            "study_id",
            "original_text",
            "evidence_refs",
            "lineage",
            "risk_level",
            "risk_categories",
        )
    }
    expected = hashlib.sha256(
        json.dumps(
            digest_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    assert row["review_target_digest"] == expected
    packet = build_risk_packet(project)
    assert packet["targets"][0]["review_target_digest"] == expected


def test_new_risk_packet_invalidates_prior_decisions_and_writer_packet(tmp_path: Path) -> None:
    project = _initialize(tmp_path)
    vertical_review.confirm_review_brief(project)
    register_study(
        project,
        _candidate("STUDY-PACKET-REFRESH", [_claim("CLAIM-PACKET-REFRESH", risk_level="R3")]),
        _r0("STUDY-PACKET-REFRESH"),
        _reviewer("STUDY-PACKET-REFRESH"),
    )
    first_packet = build_risk_packet(project)
    decision = _bound_decision(project, "CLAIM-PACKET-REFRESH", "APPROVE")
    apply_risk_decisions(
        project,
        {"packet_digest": first_packet["packet_digest"], "decisions": [decision]},
    )
    assert build_writer_packet(project)["approved_claim_count"] == 1

    second_packet = build_risk_packet(project)

    assert second_packet["packet_digest"] != first_packet["packet_digest"]
    stored = json.loads((project / "03_review" / "risk_decisions.json").read_text())
    assert stored == {
        "schema_version": "vertical-review-risk-decisions.v2",
        "project_id": "synthetic-review",
        "packet_digest": second_packet["packet_digest"],
        "decisions": [],
    }
    with pytest.raises(VerticalReviewError) as error:
        build_writer_packet(project)
    assert error.value.code == "RISK_REVIEW_INCOMPLETE"


def test_risk_decisions_must_cover_current_packet_and_close_every_target(tmp_path: Path) -> None:
    project = _initialize(tmp_path)
    vertical_review.confirm_review_brief(project)
    register_study(
        project,
        _candidate(
            "STUDY-PACKET-COVERAGE",
            [
                _claim("CLAIM-PACKET-A", risk_level="R3"),
                _claim("CLAIM-PACKET-B", risk_level="R3"),
            ],
        ),
        _r0("STUDY-PACKET-COVERAGE"),
        _reviewer("STUDY-PACKET-COVERAGE"),
    )
    packet = build_risk_packet(project)

    with pytest.raises(VerticalReviewError) as missing:
        apply_risk_decisions(
            project,
            {
                "packet_digest": packet["packet_digest"],
                "decisions": [_bound_decision(project, "CLAIM-PACKET-A", "APPROVE")],
            },
        )
    assert missing.value.code == "RISK_REVIEW_INCOMPLETE"

    apply_risk_decisions(
        project,
        {
            "packet_digest": packet["packet_digest"],
            "decisions": [
                _bound_decision(project, "CLAIM-PACKET-A", "APPROVE"),
                _bound_decision(project, "CLAIM-PACKET-B", "UNRESOLVED"),
            ],
        },
    )

    state = json.loads((project / "00_brief" / "review_state.json").read_text())
    assert state["status"] == "awaiting_risk_decisions"
    assert state["current_stage"] == "risk_review"
    with pytest.raises(VerticalReviewError) as blocked_writer:
        build_writer_packet(project)
    assert blocked_writer.value.code == "RISK_REVIEW_INCOMPLETE"


def test_writer_packet_requires_current_completed_risk_checkpoint(tmp_path: Path) -> None:
    project = _initialize(tmp_path)
    vertical_review.confirm_review_brief(project)
    register_study(
        project,
        _candidate("STUDY-WRITER-GATE", [_claim("CLAIM-WRITER-GATE", risk_level="R3")]),
        _r0("STUDY-WRITER-GATE"),
        _reviewer("STUDY-WRITER-GATE"),
    )

    with pytest.raises(VerticalReviewError) as missing_packet:
        build_writer_packet(project)
    assert missing_packet.value.code == "RISK_REVIEW_INCOMPLETE"

    packet = build_risk_packet(project)
    with pytest.raises(VerticalReviewError) as pending:
        build_writer_packet(project)
    assert pending.value.code == "RISK_REVIEW_INCOMPLETE"

    apply_risk_decisions(
        project,
        {
            "packet_digest": packet["packet_digest"],
            "decisions": [_bound_decision(project, "CLAIM-WRITER-GATE", "APPROVE")],
        },
    )
    state = json.loads((project / "00_brief" / "review_state.json").read_text())
    assert state["status"] == "risk_decisions_applied"
    assert state["current_stage"] == "ready_for_writing"
    assert build_writer_packet(project)["approved_claim_count"] == 1


def test_apply_risk_decision_persists_current_review_target_digest(tmp_path: Path) -> None:
    project = _initialize(tmp_path)
    result = register_study(
        project,
        _candidate("STUDY-DECISION-DIGEST", [_claim("CLAIM-DECISION-DIGEST", risk_level="R3")]),
        _r0("STUDY-DECISION-DIGEST"),
        _reviewer("STUDY-DECISION-DIGEST"),
    )
    packet = build_risk_packet(project)
    digest = result["claim_projection"][0]["review_target_digest"]

    apply_risk_decisions(
        project,
        {
            "packet_digest": packet["packet_digest"],
            "decisions": [
                {
                    "claim_id": "CLAIM-DECISION-DIGEST",
                    "action": "APPROVE",
                    "review_target_digest": digest,
                }
            ]
        },
    )

    stored = json.loads((project / "03_review" / "risk_decisions.json").read_text())
    assert stored["decisions"][0]["review_target_digest"] == digest


def test_risk_decisions_refresh_confirmed_project_state(tmp_path: Path) -> None:
    project = _initialize(tmp_path)
    vertical_review.confirm_review_brief(project)
    for suffix in ("A", "B"):
        register_study(
            project,
            _candidate(f"STUDY-RISK-STATE-{suffix}", [_claim(f"CLAIM-RISK-STATE-{suffix}", risk_level="R3")]),
            _r0(f"STUDY-RISK-STATE-{suffix}"),
            _reviewer(f"STUDY-RISK-STATE-{suffix}"),
        )

    packet = build_risk_packet(project)
    mixed = [
        _bound_decision(project, "CLAIM-RISK-STATE-A", "APPROVE"),
        _bound_decision(project, "CLAIM-RISK-STATE-B", "UNRESOLVED"),
    ]
    apply_risk_decisions(project, {"packet_digest": packet["packet_digest"], "decisions": mixed})
    state = json.loads((project / "00_brief" / "review_state.json").read_text())
    assert state["status"] == "awaiting_risk_decisions"
    assert state["current_stage"] == "risk_review"

    closed = [
        _bound_decision(project, "CLAIM-RISK-STATE-A", "APPROVE"),
        _bound_decision(project, "CLAIM-RISK-STATE-B", "EXCLUDE"),
    ]
    apply_risk_decisions(project, {"packet_digest": packet["packet_digest"], "decisions": closed})
    state = json.loads((project / "00_brief" / "review_state.json").read_text())
    assert state["current_stage"] == "ready_for_writing"
    assert state["status"] == "risk_decisions_applied"
    assert state["counts"] == {"claims": 2, "evidence": 2, "sources": 2}


def test_risk_decision_commit_failure_stages_projection_and_retry_recovers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _initialize(tmp_path)
    register_study(
        project,
        _candidate("STUDY-COMMIT-FAILURE", [_claim("CLAIM-COMMIT-FAILURE", risk_level="R3")]),
        _r0("STUDY-COMMIT-FAILURE"),
        _reviewer("STUDY-COMMIT-FAILURE"),
    )
    packet = build_risk_packet(project)
    decision = _bound_decision(project, "CLAIM-COMMIT-FAILURE", "APPROVE")
    writer_path = project / "02_claims" / "writer_packet.json"
    projection_path = project / "02_claims" / "claim_projection.jsonl"
    decisions_path = project / "03_review" / "risk_decisions.json"
    projection_before = projection_path.read_bytes()
    decisions_before = decisions_path.read_bytes()
    original_write_json = vertical_review._write_json

    def fail_commit_record(path: Path, value: object) -> None:
        if path == decisions_path:
            raise OSError("synthetic risk decision commit failure")
        original_write_json(path, value)

    with monkeypatch.context() as patch:
        patch.setattr(vertical_review, "_write_json", fail_commit_record)
        with pytest.raises(OSError):
            apply_risk_decisions(
                project,
                {"packet_digest": packet["packet_digest"], "decisions": [decision]},
            )

    assert decisions_path.read_bytes() == decisions_before
    assert projection_path.read_bytes() != projection_before
    staged = json.loads(projection_path.read_text().splitlines()[0])
    assert staged["decision"] == "APPROVED"
    assert not writer_path.exists()
    for consumer in (build_writer_packet, build_risk_packet, benchmark_metrics):
        with pytest.raises(VerticalReviewError) as error:
            consumer(project)
        assert error.value.code == "PROJECTION_INVALID"

    recovered = apply_risk_decisions(
        project,
        {"packet_digest": packet["packet_digest"], "decisions": [decision]},
    )

    assert recovered[0]["decision"] == "APPROVED"
    stored = json.loads(decisions_path.read_text())
    assert stored["decisions"] == [decision]
    assert build_writer_packet(project)["approved_claim_count"] == 1


def test_old_risk_approval_is_ignored_after_claim_target_changes(tmp_path: Path) -> None:
    project = _initialize(tmp_path)
    study_id = "STUDY-STALE-RISK"
    claim_id = "CLAIM-STALE-RISK"
    first = register_study(
        project,
        _candidate(study_id, [_claim(claim_id, text="First wording.", risk_level="R3")]),
        _r0(study_id),
        _reviewer(study_id),
    )
    old_digest = first["claim_projection"][0]["review_target_digest"]
    old_decision = {
        "claim_id": claim_id,
        "action": "APPROVE",
        "review_target_digest": old_digest,
    }
    first_packet = build_risk_packet(project)
    apply_risk_decisions(
        project,
        {"packet_digest": first_packet["packet_digest"], "decisions": [old_decision]},
    )

    changed_claim = _claim(claim_id, text="Changed wording.", risk_level="R3")
    changed_claim["evidence_refs"][0].update({"source_id": "SOURCE-CHANGED", "page": 2})
    changed_candidate = _candidate(study_id, [changed_claim])
    changed_candidate["job_id"] = "JOB-CHANGED"
    changed_r0 = _r0(study_id)
    changed_r0.update({"job_id": "JOB-CHANGED", "candidate_job_id": "JOB-CHANGED"})
    changed_reviewer = _reviewer(study_id)
    changed_reviewer["job_id"] = "JOB-CHANGED"

    result = register_study(project, changed_candidate, changed_r0, changed_reviewer)

    row = result["claim_projection"][0]
    assert row["review_target_digest"] != old_digest
    assert row["decision"] == "HUMAN_REQUIRED"
    with pytest.raises(VerticalReviewError) as writer_error:
        build_writer_packet(project)
    assert writer_error.value.code == "RISK_REVIEW_INCOMPLETE"
    refreshed_packet = build_risk_packet(project)
    before = _authoritative_bytes(project)

    with pytest.raises(VerticalReviewError) as error:
        apply_risk_decisions(
            project,
            {"packet_digest": refreshed_packet["packet_digest"], "decisions": [old_decision]},
        )

    assert error.value.code == "RISK_TARGET_STALE"
    assert _authoritative_bytes(project) == before


def test_missing_risk_target_digest_is_rejected_without_state_change(tmp_path: Path) -> None:
    project = _initialize(tmp_path)
    register_study(
        project,
        _candidate("STUDY-MISSING-DIGEST", [_claim("CLAIM-MISSING-DIGEST", risk_level="R3")]),
        _r0("STUDY-MISSING-DIGEST"),
        _reviewer("STUDY-MISSING-DIGEST"),
    )
    packet = build_risk_packet(project)
    before = _authoritative_bytes(project)

    with pytest.raises(VerticalReviewError) as error:
        apply_risk_decisions(
            project,
            {
                "packet_digest": packet["packet_digest"],
                "decisions": [{"claim_id": "CLAIM-MISSING-DIGEST", "action": "APPROVE"}],
            },
        )

    assert error.value.code == "RISK_TARGET_STALE"
    assert _authoritative_bytes(project) == before


@pytest.mark.parametrize(
    ("decisions", "code"),
    [
        (
            {
                "decisions": [
                    {"claim_id": "CLAIM-RISK", "action": "APPROVE"},
                    {"claim_id": "CLAIM-RISK", "action": "EXCLUDE"},
                ]
            },
            "RISK_TARGET_DUPLICATE",
        ),
        (
            {"decisions": [{"claim_id": "CLAIM-UNKNOWN", "action": "APPROVE"}]},
            "RISK_TARGET_UNKNOWN",
        ),
        (
            {"decisions": [{"claim_id": "CLAIM-RISK", "action": "REWORD"}]},
            "APPROVED_TEXT_REQUIRED",
        ),
    ],
)
def test_invalid_risk_decisions_fail_closed(tmp_path: Path, decisions: dict, code: str) -> None:
    project = _initialize(tmp_path)
    register_study(
        project,
        _candidate("STUDY-RISK", [_claim("CLAIM-RISK", risk_level="R3")]),
        _r0("STUDY-RISK"),
        _reviewer("STUDY-RISK"),
    )
    projection_path = project / "02_claims" / "claim_projection.jsonl"
    projection_bytes = projection_path.read_bytes()
    packet = build_risk_packet(project)
    projection_bytes = projection_path.read_bytes()
    current_digest = _bound_decision(project, "CLAIM-RISK", "APPROVE")[
        "review_target_digest"
    ]
    bound_decisions = copy.deepcopy(decisions)
    for row in bound_decisions["decisions"]:
        row["review_target_digest"] = (
            current_digest if row.get("claim_id") == "CLAIM-RISK" else "unknown-target"
        )

    with pytest.raises(VerticalReviewError) as error:
        apply_risk_decisions(
            project,
            {"packet_digest": packet["packet_digest"], **bound_decisions},
        )

    assert error.value.code == code
    assert projection_path.read_bytes() == projection_bytes


def test_risk_packet_sampling_is_sha256_stable_and_deduplicated(tmp_path: Path) -> None:
    project = _initialize(tmp_path)
    low_risk_ids = [f"CLAIM-LOW-{index:02d}" for index in range(20)]
    register_study(
        project,
        _candidate(
            "STUDY-SAMPLE",
            [
                *[_claim(claim_id) for claim_id in low_risk_ids],
                _claim(
                    "CLAIM-HIGH",
                    risk_level="R1",
                    risk_categories=["STRUCTURE"],
                ),
            ],
        ),
        _r0("STUDY-SAMPLE"),
        _reviewer("STUDY-SAMPLE"),
    )

    first = build_risk_packet(project, low_risk_sample_rate=0.10)
    risk_path = project / "03_review" / "risk_packet.json"
    first_bytes = risk_path.read_bytes()
    second = build_risk_packet(project, low_risk_sample_rate=0.10)

    expected_sample = sorted(
        low_risk_ids,
        key=lambda claim_id: hashlib.sha256(claim_id.encode("utf-8")).hexdigest(),
    )[:2]
    sampled = [
        row["claim_id"]
        for row in first["targets"]
        if row["selection_reason"] == "LOW_RISK_AUDIT"
    ]
    target_ids = [row["claim_id"] for row in first["targets"]]
    assert sampled == expected_sample
    assert target_ids.count("CLAIM-HIGH") == 1
    assert len(target_ids) == len(set(target_ids))
    assert second["targets"] == first["targets"]
    assert second["generation"] == first["generation"] + 1
    assert second["packet_digest"] != first["packet_digest"]
    assert risk_path.read_bytes() != first_bytes


def test_register_and_risk_application_never_mutate_input_fixtures(tmp_path: Path) -> None:
    project = _initialize(tmp_path)
    fixtures = {
        "candidate": _candidate(
            "STUDY-IMMUTABLE",
            [_claim("CLAIM-IMMUTABLE", risk_level="R3")],
        ),
        "r0": _r0("STUDY-IMMUTABLE", findings=[]),
        "reviewer": _reviewer(
            "STUDY-IMMUTABLE",
            review_id="REVIEW-IMMUTABLE",
        ),
    }
    fixtures["candidate"]["provider_candidate"] = {
        "provider": "synthetic-provider",
        "provider_record_id": "FIXTURE-1",
    }
    paths = {name: tmp_path / f"{name}.json" for name in fixtures}
    for name, path in paths.items():
        path.write_text(json.dumps(fixtures[name], ensure_ascii=False, indent=3) + "\n")
    fixture_bytes = {name: path.read_bytes() for name, path in paths.items()}
    loaded = {name: json.loads(path.read_text()) for name, path in paths.items()}
    loaded_before = copy.deepcopy(loaded)

    register_study(project, loaded["candidate"], loaded["r0"], loaded["reviewer"])
    packet = build_risk_packet(project)
    apply_risk_decisions(
        project,
        {
            "packet_digest": packet["packet_digest"],
            "decisions": [_bound_decision(project, "CLAIM-IMMUTABLE", "APPROVE")],
        },
    )

    assert loaded == loaded_before
    assert {name: path.read_bytes() for name, path in paths.items()} == fixture_bytes
    stored_card = json.loads(
        (project / "01_evidence" / "evidence_cards.jsonl").read_text().splitlines()[0]
    )
    assert stored_card["candidate"] == loaded_before["candidate"]


def test_benchmark_metrics_report_authoritative_projection_counts(tmp_path: Path) -> None:
    project = _initialize(tmp_path)
    register_study(
        project,
        _candidate(
            "STUDY-METRICS",
            [
                _claim("CLAIM-METRICS-APPROVED"),
                _claim("CLAIM-METRICS-HUMAN", risk_level="R3"),
            ],
        ),
        _r0("STUDY-METRICS"),
        _reviewer("STUDY-METRICS"),
    )
    with pytest.raises(VerticalReviewError):
        register_study(
            project,
            _candidate("STUDY-METRICS-BAD", [_claim("CLAIM-METRICS-BAD")]),
            _r0("STUDY-METRICS-BAD", status="R0_FAIL_GROUNDING_CONTRACT"),
            _reviewer("STUDY-METRICS-BAD"),
        )

    metrics = benchmark_metrics(project)

    assert metrics == {
        "approved_claim_count": 1,
        "blocked_claim_count": 0,
        "exception_count": 1,
        "human_required_claim_count": 1,
        "project_id": "synthetic-review",
        "projected_claim_count": 2,
        "registered_study_count": 1,
    }


def test_cli_exposes_required_subcommands_and_prepare_creates_no_state(tmp_path: Path) -> None:
    help_result = subprocess.run(
        [sys.executable, str(CLI), "--help"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert help_result.returncode == 0, help_result.stderr
    for command in (
        "preflight",
        "init",
        "prepare-study",
        "prepare-batch",
        "register-study",
        "build-risk-packet",
        "build-writer-packet",
        "bind-draft",
        "metrics",
    ):
        assert command in help_result.stdout
    assert "apply-risk-decisions" not in help_result.stdout

    project = _initialize(tmp_path)
    before = {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    }
    prepare = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "prepare-study",
            "--project-dir",
            str(project),
            "--study-id",
            "STUDY-NOT-DECLARED",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert prepare.returncode == 3, prepare.stderr
    summary = json.loads(prepare.stdout)
    assert summary == {
        "command": "prepare-study",
        "reason_code": "ACQUISITION_MANIFEST_MISSING",
        "status": "NOT_READY",
        "study_id": "STUDY-NOT-DECLARED",
    }
    study_ids_path = tmp_path / "study-ids.txt"
    study_ids_path.write_text("STUDY-A\nSTUDY-B\n")
    batch = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "prepare-batch",
            "--project-dir",
            str(project),
            "--study-ids-file",
            str(study_ids_path),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert batch.returncode == 3, batch.stderr
    batch_summary = json.loads(batch.stdout)
    assert batch_summary["status"] == "NOT_READY"
    assert batch_summary["ready_count"] == 0
    assert batch_summary["not_ready_count"] == 2
    assert [row["study_id"] for row in batch_summary["studies"]] == [
        "STUDY-A",
        "STUDY-B",
    ]
    after = {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_preflight_reports_missing_mineru_without_exposing_secret_values(tmp_path: Path) -> None:
    missing_token = tmp_path / "missing-mineru-token.txt"
    environment = dict(os.environ)
    environment.pop("MINERU_API_TOKEN", None)
    result = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "preflight",
            "--review-root",
            str(tmp_path / "review-root"),
            "--mineru-token-file",
            str(missing_token),
            "--mineru-egress-authorized",
        ],
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 3
    payload = json.loads(result.stdout)
    assert payload["status"] == "BLOCKED"
    assert payload["reason_code"] == "MINERU_PREFLIGHT_BLOCKED"
    assert payload["checks"]["mineru_token"] == "missing"
    assert "token_value" not in json.dumps(payload)


def test_wait_state_timeout_is_bounded_and_returns_resume_instruction(tmp_path: Path) -> None:
    project = _initialize(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "wait-state",
            "--project-dir",
            str(project),
            "--status",
            "BRIEF_CONFIRMED",
            "--stage",
            "ready_for_discovery",
            "--poll-seconds",
            "0.01",
            "--timeout-seconds",
            "0.02",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    payload = json.loads(result.stderr)
    assert payload == {
        "command": "wait-state",
        "error_code": "WAIT_STATE_TIMEOUT",
        "project_saved": True,
        "resume_instruction": "完成工作台操作后，在 QoderWork 发送“继续当前综述项目”。",
        "status": "ERROR",
    }


def test_prepare_study_builds_current_pre_provider_packet_without_reruns_and_is_idempotent(
    tmp_path: Path,
) -> None:
    study_id = "STUDY-CANARY"
    project = _canonical_prepare_project(tmp_path, study_id=study_id)
    before = _file_bytes(project)
    first = _run_prepare(project, study_id)
    assert first.returncode == 0, first.stderr
    summary = json.loads(first.stdout)
    assert (summary["status"], summary["reason_code"], summary["study_id"]) == (
        "READY",
        "PRE_PROVIDER_PACKET_READY",
        study_id,
    )
    assert set(summary["outputs"]) == {"sealed_job", "atom_catalog"}
    assert "evidence paragraph" not in first.stdout

    job_path = project / summary["outputs"]["sealed_job"]
    catalog_path = project / summary["outputs"]["atom_catalog"]
    job = json.loads(job_path.read_text(encoding="utf-8"))
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert job["study"] == {"doi": "10.1000/canary.test", "study_id": study_id}
    assert job["target_namespace"] == (
        "study-" + hashlib.sha256(study_id.encode("utf-8")).hexdigest()
    )
    assert [source["document_role"] for source in job["source_files"]] == ["MAIN", "SI"]
    assert all(
        {
            "source_id",
            "document_role",
            "reading_order_path",
            "reading_order_sha256",
            "layout_path",
            "layout_sha256",
            "page_count",
        }
        <= source.keys()
        for source in job["source_files"]
    )
    assert catalog["job_id"] == job["job_id"]
    assert catalog["study_id"] == study_id
    assert catalog["atoms"]

    after = _file_bytes(project)
    assert {path: after[path] for path in before} == before
    assert set(after) - set(before) == {
        f"01_evidence/{study_id}/sealed_job.json",
        f"01_evidence/{study_id}/atom_catalog.json",
    }
    output_bytes = (job_path.read_bytes(), catalog_path.read_bytes())
    second = _run_prepare(project, study_id)
    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout) == summary
    assert (job_path.read_bytes(), catalog_path.read_bytes()) == output_bytes


@pytest.mark.parametrize(
    ("audit_payload", "reason_code"),
    (
        (None, "REUSABLE_LIBRARY_AUDIT_MISSING"),
        ({"schema_version": "wrong", "canonical_artifact": "00_sources/reusable_library_audit.json"}, "REUSABLE_LIBRARY_AUDIT_INVALID"),
        ({"schema_version": "reusable-library-audit.v1", "canonical_artifact": "other.json"}, "REUSABLE_LIBRARY_AUDIT_INVALID"),
    ),
)
def test_prepare_study_requires_the_canonical_reusable_library_audit(
    tmp_path: Path,
    audit_payload: dict[str, str] | None,
    reason_code: str,
) -> None:
    study_id = "STUDY-CANARY"
    project = _canonical_prepare_project(tmp_path, study_id=study_id)
    audit_path = project / "00_sources/reusable_library_audit.json"
    if audit_payload is None:
        audit_path.unlink()
    else:
        _write_prepare_json(audit_path, audit_payload)
    before = _file_bytes(project)

    result = _run_prepare(project, study_id)

    assert result.returncode == 3, result.stderr
    assert json.loads(result.stdout)["reason_code"] == reason_code
    assert _file_bytes(project) == before
    assert not (project / "01_evidence" / study_id).exists()


@pytest.mark.parametrize(
    ("mutation", "reason_code"),
    (
        ("stale_digest", "REUSABLE_LIBRARY_AUDIT_STALE"),
        ("missing_parser_contract", "REUSABLE_LIBRARY_AUDIT_INVALID"),
        ("blank_parser_contract", "REUSABLE_LIBRARY_AUDIT_INVALID"),
        ("reusable_source_pdf_mismatch", "REUSABLE_LIBRARY_AUDIT_INVALID"),
        ("reusable_parser_contract_mismatch", "REUSABLE_LIBRARY_AUDIT_INVALID"),
        ("pdf_only_with_derived_asset", "REUSABLE_LIBRARY_AUDIT_INVALID"),
        ("unresolved_with_pdf_asset", "REUSABLE_LIBRARY_AUDIT_INVALID"),
        ("malformed_results", "REUSABLE_LIBRARY_AUDIT_INVALID"),
        ("malformed_result_assets", "REUSABLE_LIBRARY_AUDIT_INVALID"),
        ("role_mismatch", "REUSABLE_LIBRARY_AUDIT_STALE"),
    ),
)
def test_prepare_rejects_stale_or_mismatched_reusable_library_results(
    tmp_path: Path,
    mutation: str,
    reason_code: str,
) -> None:
    project = _canonical_prepare_project(tmp_path)
    audit_path = project / "00_sources/reusable_library_audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if mutation == "stale_digest":
        audit["request_set_digest"] = _request_set_digest([])
    elif mutation == "missing_parser_contract":
        audit.pop("required_parser_contract")
    elif mutation == "blank_parser_contract":
        audit["required_parser_contract"] = " "
    elif mutation in {"reusable_source_pdf_mismatch", "reusable_parser_contract_mismatch"}:
        result_row = audit["results"][0]
        pdf_sha256 = "1" * 64
        result_row.update(
            {
                "assets": {
                    "pdf": {"path": "library/main.pdf", "sha256": pdf_sha256},
                    **{
                        name: {
                            "parser_contract": (
                                "other-parser"
                                if mutation == "reusable_parser_contract_mismatch"
                                else audit["required_parser_contract"]
                            ),
                            "path": f"library/main.{name}",
                            "sha256": "2" * 64,
                            "source_pdf_sha256": (
                                "0" * 64
                                if mutation == "reusable_source_pdf_mismatch"
                                else pdf_sha256
                            ),
                        }
                        for name in ("mineru", "text", "atom")
                    },
                },
                "library_id": "LIB-MAIN",
                "reason": None,
                "status": "REUSABLE",
            }
        )
    elif mutation == "pdf_only_with_derived_asset":
        audit["results"][0].update(
            {
                "assets": {
                    "pdf": {"path": "library/main.pdf", "sha256": "1" * 64},
                    "mineru": {
                        "parser_contract": audit["required_parser_contract"],
                        "path": "library/main.mineru",
                        "sha256": "2" * 64,
                        "source_pdf_sha256": "1" * 64,
                    },
                },
                "library_id": "LIB-MAIN",
                "reason": "PARSER_CONTRACT_MISMATCH",
                "status": "PDF_ONLY",
            }
        )
    elif mutation == "unresolved_with_pdf_asset":
        audit["results"][0].update(
            {
                "assets": {"pdf": {"path": "library/main.pdf", "sha256": "1" * 64}},
                "reason": "AMBIGUOUS_LIBRARY_MATCH",
                "status": "UNRESOLVED",
            }
        )
    elif mutation == "malformed_results":
        audit["results"] = {"not": "a list"}
    elif mutation == "malformed_result_assets":
        audit["results"][0]["assets"] = {"claims": {}}
    else:
        audit["results"][0]["document_role"] = "SI"
    _write_prepare_json(audit_path, audit)

    result = _run_prepare(project, "STUDY-CANARY")

    assert result.returncode == 3, result.stderr
    assert json.loads(result.stdout)["reason_code"] == reason_code
    assert not (project / "01_evidence/STUDY-CANARY").exists()


def test_prepare_job_id_binds_source_hashes_and_the_semantic_target_contract(
    tmp_path: Path,
) -> None:
    source_a = _canonical_prepare_project(
        tmp_path / "source-a",
        main_pdf_bytes=b"synthetic main source A\n",
    )
    source_b = _canonical_prepare_project(
        tmp_path / "source-b",
        main_pdf_bytes=b"synthetic main source B\n",
    )
    for project in (source_a, source_b):
        result = _run_prepare(project, "STUDY-CANARY")
        assert result.returncode == 0, result.stderr
    source_a_job = json.loads(
        (source_a / "01_evidence/STUDY-CANARY/sealed_job.json").read_text(encoding="utf-8")
    )
    source_b_job = json.loads(
        (source_b / "01_evidence/STUDY-CANARY/sealed_job.json").read_text(encoding="utf-8")
    )
    assert source_a_job["job_id"] == _expected_sealed_job_id(source_a_job)
    assert source_b_job["job_id"] == _expected_sealed_job_id(source_b_job)
    assert source_a_job["source_files"] != source_b_job["source_files"]
    assert source_a_job["job_id"] != source_b_job["job_id"]

    required = _canonical_prepare_project(
        tmp_path / "required",
        si_policy="REQUIRED",
        si_dependent_claim_ids=["CLAIM-SI-DEPENDENT"],
    )
    recommended = _canonical_prepare_project(
        tmp_path / "recommended",
        si_policy="RECOMMENDED",
        si_dependent_claim_ids=["CLAIM-SI-DEPENDENT"],
    )
    for project in (required, recommended):
        receipt_path = project / "00_sources/acquisition_final_receipt.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["studies"][0].pop("si_pdf")
        _write_prepare_json(receipt_path, receipt)
        _refresh_and_approve_parse_gate(project, "STUDY-CANARY")
        result = _run_prepare(project, "STUDY-CANARY")
        assert result.returncode == 0, result.stderr
    required_job = json.loads(
        (required / "01_evidence/STUDY-CANARY/sealed_job.json").read_text(encoding="utf-8")
    )
    recommended_job = json.loads(
        (recommended / "01_evidence/STUDY-CANARY/sealed_job.json").read_text(encoding="utf-8")
    )
    assert required_job["job_id"] == _expected_sealed_job_id(required_job)
    assert recommended_job["job_id"] == _expected_sealed_job_id(recommended_job)
    assert required_job["source_files"] == recommended_job["source_files"]
    assert required_job["semantic_target_contract"] != recommended_job["semantic_target_contract"]
    assert required_job["job_id"] != recommended_job["job_id"]


@pytest.mark.parametrize(
    ("si_policy", "expected_status", "expected_reason", "expected_blocked_claims"),
    (
        (
            "REQUIRED",
            "PARTIAL",
            "SI_REQUIRED_FOR_DECLARED_CLAIMS",
            ["CLAIM-SI-DEPENDENT"],
        ),
        ("RECOMMENDED", "READY_WITH_LIMITATION", None, []),
        ("NOT_REQUIRED", "READY", None, []),
    ),
)
def test_prepare_study_persists_canonical_si_policy_without_blocking_the_whole_study(
    tmp_path: Path,
    si_policy: str,
    expected_status: str,
    expected_reason: str | None,
    expected_blocked_claims: list[str],
) -> None:
    study_id = "STUDY-CANARY"
    project = _canonical_prepare_project(
        tmp_path,
        study_id=study_id,
        si_policy=si_policy,
        si_dependent_claim_ids=["CLAIM-SI-DEPENDENT"],
    )
    receipt_path = project / "00_sources/acquisition_final_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["studies"][0].pop("si_pdf")
    _write_prepare_json(receipt_path, receipt)
    gate = _refresh_and_approve_parse_gate(project, study_id)

    result = _run_prepare(project, study_id)

    assert result.returncode == 0, result.stderr
    coverage = json.loads(
        (project / "00_sources/source_coverage.json").read_text(encoding="utf-8")
    )
    assert coverage["schema_version"] == "source-coverage.v1"
    assert coverage["canonical_artifact"] == "00_sources/source_coverage.json"
    assert len(coverage["studies"]) == 1
    study = coverage["studies"][0]
    assert study["study_id"] == study_id
    assert study["available_roles"] == ["MAIN"]
    assert study["si_policy"] == si_policy
    assert study["study_status"] == expected_status
    assert study["blocked_claim_ids"] == expected_blocked_claims
    if expected_reason is None:
        assert study["blocking_reasons"] == []
    else:
        assert study["blocking_reasons"] == [expected_reason]
    job = json.loads(
        (project / f"01_evidence/{study_id}/sealed_job.json").read_text(encoding="utf-8")
    )
    assert job["semantic_target_contract"] == {
        "allowed_target_kinds": ["ELIGIBILITY", "REACTION_UNIT", "CLAIM"],
        "denied_claim_ids": expected_blocked_claims,
        "parse_quality_gate_digest": gate["gate_digest"],
        "policy": "ALLOW_EXCEPT_DECLARED_SI_DEPENDENT_CLAIMS",
    }


def test_prepare_study_blocks_missing_main_and_records_the_same_canonical_coverage(
    tmp_path: Path,
) -> None:
    study_id = "STUDY-CANARY"
    project = _canonical_prepare_project(tmp_path, study_id=study_id)
    receipt_path = project / "00_sources/acquisition_final_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["studies"][0].pop("main_pdf")
    _write_prepare_json(receipt_path, receipt)

    result = _run_prepare(project, study_id)

    assert result.returncode == 3, result.stderr
    assert json.loads(result.stdout)["reason_code"] == "MAIN_REQUIRED"
    coverage = json.loads(
        (project / "00_sources/source_coverage.json").read_text(encoding="utf-8")
    )
    assert coverage["studies"][0]["study_status"] == "BLOCKED"
    assert coverage["studies"][0]["blocking_reasons"] == ["MAIN_REQUIRED"]
    assert not (project / "01_evidence" / study_id).exists()


@pytest.mark.parametrize(
    ("case", "reason_code"),
    (
        ("malformed_si", "ACQUISITION_SI_INVALID"),
        ("identity_warn", "SOURCE_IDENTITY_NOT_PASS"),
        ("missing_hash", "ACQUISITION_SOURCE_HASH_INVALID"),
    ),
)
def test_prepare_study_fails_closed_for_missing_or_ambiguous_bindings(
    tmp_path: Path,
    case: str,
    reason_code: str,
) -> None:
    study_id = "STUDY-CANARY"
    project = _canonical_prepare_project(tmp_path, study_id=study_id)
    if case in {"malformed_si", "missing_hash"}:
        receipt_path = project / "00_sources/acquisition_final_receipt.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if case == "malformed_si":
            receipt["studies"][0]["si_pdf"] = {"sha256": "0" * 64}
        else:
            receipt["studies"][0]["main_pdf"].pop("sha256")
        _write_prepare_json(receipt_path, receipt)
    elif case == "identity_warn":
        audit_path = project / "00_sources/source_identity_audit.json"
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        audit["results"][0]["verdict"] = "WARN"
        _write_prepare_json(audit_path, audit)
    else:
        manifest_path = project / "01_evidence/text_layers/text_layers.manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        si_row = next(row for row in manifest["sources"] if row["source_id"] == "CANARY_SI")
        if case == "missing":
            manifest["sources"].remove(si_row)
        elif case == "ambiguous":
            manifest["sources"].append({**si_row, "source_id": "CANARY_SI_DUPLICATE"})
        else:
            wrong = project / "01_evidence/mineru/markdown/CANARY_SI.md"
            si_row["reading_order_path"] = wrong.relative_to(project).as_posix()
            si_row["reading_order_sha256"] = _prepare_sha256(wrong)
        _write_prepare_json(manifest_path, manifest)
    before = _file_bytes(project)
    result = _run_prepare(project, study_id)
    assert result.returncode == 3, result.stderr
    assert json.loads(result.stdout)["reason_code"] == reason_code
    assert _file_bytes(project) == before
    assert not (project / "01_evidence" / study_id).exists()


@pytest.mark.parametrize("case", ("missing", "ambiguous", "wrong_subtree"))
def test_prepare_uses_the_bundle_when_legacy_text_manifest_drifts(
    tmp_path: Path,
    case: str,
) -> None:
    project = _canonical_prepare_project(tmp_path)
    manifest_path = project / "01_evidence/text_layers/text_layers.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    si_row = next(row for row in manifest["sources"] if row["source_id"] == "CANARY_SI")
    if case == "missing":
        manifest["sources"].remove(si_row)
    elif case == "ambiguous":
        manifest["sources"].append({**si_row, "source_id": "CANARY_SI_DUPLICATE"})
    else:
        wrong = project / "01_evidence/mineru/markdown/CANARY_SI.md"
        si_row["reading_order_path"] = wrong.relative_to(project).as_posix()
        si_row["reading_order_sha256"] = _prepare_sha256(wrong)
    _write_prepare_json(manifest_path, manifest)

    result = _run_prepare(project, "STUDY-CANARY")

    assert result.returncode == 0, result.stderr
    job = json.loads(
        (project / "01_evidence/STUDY-CANARY/sealed_job.json").read_text(encoding="utf-8")
    )
    assert {row["source_id"] for row in job["source_files"]} == {"CANARY_MAIN", "CANARY_SI"}


def test_prepare_batch_persists_ready_studies_independently(tmp_path: Path) -> None:
    project = _canonical_prepare_project(tmp_path)
    study_ids = tmp_path / "study-ids.txt"
    study_ids.write_text("STUDY-CANARY\nSTUDY-NOT-DECLARED\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "prepare-batch",
            "--project-dir",
            str(project),
            "--study-ids-file",
            str(study_ids),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 3, result.stderr
    summary = json.loads(result.stdout)
    assert summary["status"] == "NOT_READY"
    assert summary["ready_count"] == summary["not_ready_count"] == 1
    assert [(row["study_id"], row["status"]) for row in summary["studies"]] == [
        ("STUDY-CANARY", "READY"),
        ("STUDY-NOT-DECLARED", "NOT_READY"),
    ]
    assert (project / "01_evidence/STUDY-CANARY/sealed_job.json").is_file()
    assert (project / "01_evidence/STUDY-CANARY/atom_catalog.json").is_file()
    assert not (project / "01_evidence/STUDY-NOT-DECLARED").exists()


def test_title_only_researcher_candidate_reaches_the_source_path(tmp_path: Path) -> None:
    study_id = "RESEARCHER-TITLE-ONLY"
    project = _initialize(tmp_path)
    _write_prepare_json(
        project / "00_discovery/candidate_pool.json",
        {
            "candidates": [
                {
                    "candidate_id": study_id,
                    "doi": "",
                    "title": "A uniquely titled researcher supplied study",
                    "source_origin": "RESEARCHER_SUPPLIED",
                }
            ]
        },
    )
    _write_prepare_json(
        project / "00_discovery/screening_decisions.json",
        {"decisions": [{"candidate_id": study_id, "disposition": "INCLUDE_FOR_FULL_TEXT"}]},
    )
    _write_prepare_json(
        project / "00_discovery/acquisition_manifest.json",
        {"schema_version": "case02-acquisition-plan.v1", "downloads": []},
    )
    _write_prepare_json(
        project / "00_sources/reusable_library_audit.json",
        {
            "schema_version": "reusable-library-audit.v1",
            "canonical_artifact": "00_sources/reusable_library_audit.json",
            "request_set_digest": _request_set_digest([]),
            "required_parser_contract": "NOT_DECLARED",
            "results": [],
        },
    )

    result = _run_prepare(project, study_id)

    assert result.returncode == 3, result.stderr
    reason = json.loads(result.stdout)["reason_code"]
    assert reason == "ACQUISITION_FINAL_RECEIPT_MISSING"
    assert reason != "STUDY_NOT_DECLARED"


def test_run_batch_cli_pauses_for_provider_and_reports_separate_credit_fields(
    tmp_path: Path,
) -> None:
    study_id = "STUDY-CANARY"
    project = _canonical_prepare_project(tmp_path, study_id=study_id)
    project_id = json.loads(
        (project / "00_brief/review_state.json").read_text(encoding="utf-8")
    )["project_id"]
    study_ids = tmp_path / "study-ids.txt"
    study_ids.write_text(f"{study_id}\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "run-batch",
            "--project-dir",
            str(project),
            "--study-ids-file",
            str(study_ids),
            "--credits-before",
            "100",
            "--credits-after",
            "91",
            "--forecast-credits",
            "30",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 3, result.stderr
    summary = json.loads(result.stdout)
    assert summary["status"] == "WAITING_FOR_PROVIDER"
    assert summary["credits"] == {
        "forecast": {"estimated_credits": 30.0},
        "measured": {"after": 91, "before": 100, "consumed": 9},
    }
    study_root = project / f"01_evidence/{study_id}"
    assert summary["studies"] == [
        {
            "atom_catalog_sha256": hashlib.sha256(
                (study_root / "atom_catalog.json").read_bytes()
            ).hexdigest(),
            "last_completed_stage": "PREPARED",
            "project_id": project_id,
            "reason_code": "SEMANTIC_OUTPUT_MISSING",
            "sealed_job_sha256": hashlib.sha256(
                (study_root / "sealed_job.json").read_bytes()
            ).hexdigest(),
            "stage": "WAITING_FOR_PROVIDER",
            "study_id": study_id,
        }
    ]
    assert json.loads(
        (project / f"01_evidence/{study_id}/batch_state.json").read_text(encoding="utf-8")
    ) == summary["studies"][0]


def test_cli_init_reports_awaiting_brief_confirmation_without_discovery(
    tmp_path: Path,
) -> None:
    brief = tmp_path / "brief.json"
    brief.write_text('{"topic":"Synthetic review"}\n', encoding="utf-8")
    project_root = tmp_path / "review-projects"

    result = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "init",
            "--review-root",
            str(project_root),
            "--project-id",
            "synthetic-review",
            "--brief",
            str(brief),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "AWAITING_BRIEF_CONFIRMATION"
    project = project_root / "synthetic-review"
    assert json.loads((project / "00_brief" / "review_state.json").read_text())[
        "status"
    ] == "AWAITING_BRIEF_CONFIRMATION"
    assert not (project / "00_discovery").exists()


def test_makefile_has_focused_vertical_projection_gate() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "vertical-review-projection-check:" in makefile
    assert (
        "\t$(PYTHON) -m pytest tests/test_vertical_review_projection.py -q"
        in makefile
    )


def _wait_state_command(project: Path, *, timeout_seconds: str = "1") -> list[str]:
    return [
        sys.executable,
        str(CLI),
        "wait-state",
        "--project-dir",
        str(project),
        "--status",
        "BRIEF_CONFIRMED",
        "--stage",
        "ready_for_discovery",
        "--poll-seconds",
        "0.01",
        "--timeout-seconds",
        timeout_seconds,
    ]


def test_wait_state_returns_immediately_when_brief_is_already_confirmed(
    tmp_path: Path,
) -> None:
    project = _initialize(tmp_path)
    vertical_review.confirm_review_brief(project)

    result = subprocess.run(
        _wait_state_command(project),
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "command": "wait-state",
        "current_stage": "ready_for_discovery",
        "status": "BRIEF_CONFIRMED",
    }


def test_wait_state_unblocks_after_dashboard_confirmation(tmp_path: Path) -> None:
    project = _initialize(tmp_path)
    process = subprocess.Popen(
        _wait_state_command(project),
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(0.05)
    assert process.poll() is None

    vertical_review.confirm_review_brief(project)
    stdout, stderr = process.communicate(timeout=2)

    assert process.returncode == 0, stderr
    assert json.loads(stdout)["status"] == "BRIEF_CONFIRMED"


def test_wait_state_times_out_with_concrete_error(tmp_path: Path) -> None:
    project = _initialize(tmp_path)

    result = subprocess.run(
        _wait_state_command(project, timeout_seconds="0.03"),
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert json.loads(result.stderr) == {
        "command": "wait-state",
        "error_code": "WAIT_STATE_TIMEOUT",
        "project_saved": True,
        "resume_instruction": "完成工作台操作后，在 QoderWork 发送“继续当前综述项目”。",
        "status": "ERROR",
    }


def _typed_paper_candidate(project: Path, *, evidence_id: str = "EVIDENCE-CANARY") -> dict:
    parse = parse_quality_state(project, "STUDY-CANARY")
    return {
        "evidence_id": evidence_id,
        "source_id": "CANARY_MAIN",
        "epistemic_type": "experimental_observation",
        "statement": "A synthetic measured outcome was reported.",
        "locator": {
            "source_mode": "parsed_candidate",
            "page": 1,
            "section_or_item": "Results",
            "figure_or_table": None,
            "exact_quote": "Main evidence paragraph.",
        },
        "reported_conditions": ["Synthetic condition"],
        "quantitative_results": ["Synthetic result"],
        "limitations": ["Synthetic limitation"],
        "mechanism_grade": "not_applicable",
        "risk_classes": [],
        "bound_parse_object_digests": [parse["objects"][0]["object_digest"]],
    }


def _declare_canonical_study(project: Path) -> None:
    receipt_path = project / "00_sources/acquisition_final_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["studies"][0]["study_id"] = "STUDY-CANARY"
    _write_prepare_json(receipt_path, receipt)


def _paper_decision(row: dict) -> dict:
    return {
        "evidence_id": row["evidence_id"],
        "candidate_digest": row["candidate_digest"],
        "bound_parse_object_digests": row["bound_parse_object_digests"],
        "source_pdf_sha256": row["source_pdf_sha256"],
        "action": "approve",
        "reason": "Checked against the current source PDF.",
    }


def test_workflow_projection_requires_current_typed_paper_evidence(tmp_path: Path) -> None:
    project = _canonical_prepare_project(tmp_path, si_policy="NOT_REQUIRED")
    _declare_canonical_study(project)
    registered = register_paper_evidence_candidates(
        project,
        "STUDY-CANARY",
        _typed_paper_candidate(project),
    )

    before = workflow_state(project)
    apply_paper_evidence_decision(project, _paper_decision(registered["candidates"][0]))
    after = workflow_state(project)

    assert before["parse_ready"] is True
    assert before["paper_evidence_ready"] is False
    assert before["active_stage"] == "evidence"
    assert after["paper_evidence_ready"] is True
    assert after["active_stage"] == "synthesis"
    assert after["blockers"] == ["SYNTHESIS_NOT_APPROVED"]


def test_parsed_candidate_cannot_bind_digest_from_another_source(tmp_path: Path) -> None:
    project = _canonical_prepare_project(tmp_path, si_policy="NOT_REQUIRED")
    parse = parse_quality_state(project, "STUDY-CANARY")
    si_digest = next(
        row["object_digest"]
        for row in parse["objects"]
        if row["source_id"] == "CANARY_SI" and row["kind"] == "body_order"
    )
    invalid = {
        **_typed_paper_candidate(project),
        "bound_parse_object_digests": [si_digest],
    }
    before = _file_bytes(project)

    with pytest.raises(PaperEvidenceError, match="PARSE_OBJECT_SOURCE_MISMATCH"):
        register_paper_evidence_candidates(project, "STUDY-CANARY", invalid)

    assert _file_bytes(project) == before


def test_stale_parse_gate_invalidates_only_evidence_depending_on_changed_source(
    tmp_path: Path,
) -> None:
    project = _canonical_prepare_project(tmp_path, si_policy="NOT_REQUIRED")
    parse = parse_quality_state(project, "STUDY-CANARY")
    digests = {
        (row["source_id"], row["kind"]): row["object_digest"]
        for row in parse["objects"]
    }
    main = {
        **_typed_paper_candidate(project, evidence_id="EVIDENCE-MAIN"),
        "bound_parse_object_digests": [digests[("CANARY_MAIN", "reference_boundary")]],
    }
    si = {
        **_typed_paper_candidate(project, evidence_id="EVIDENCE-SI"),
        "source_id": "CANARY_SI",
        "statement": "A synthetic SI observation was reported.",
        "locator": {
            "source_mode": "parsed_candidate",
            "page": 1,
            "section_or_item": "Supporting information",
            "figure_or_table": None,
            "exact_quote": "Supporting information paragraph.",
        },
        "bound_parse_object_digests": [digests[("CANARY_SI", "formula_chemistry")]],
    }
    registered = register_paper_evidence_candidates(
        project,
        "STUDY-CANARY",
        {"candidates": [main, si]},
    )
    for row in registered["candidates"]:
        apply_paper_evidence_decision(project, _paper_decision(row))
    gate_path = project / "01_evidence/source_truth/STUDY-CANARY/parse_quality.json"
    gate_before = gate_path.read_bytes()

    si_markdown = project / "01_evidence/mineru/markdown/CANARY_SI.md"
    si_markdown.write_text("# Parsed SI\nChanged SI formula $x$.\n", encoding="utf-8")
    write_source_truth_bundle(project, "STUDY-CANARY")

    intermediate_evidence = paper_evidence_state(project)
    intermediate_workflow = workflow_state(project)
    intermediate_statuses = {
        row["evidence_id"]: row["status"] for row in intermediate_evidence["rows"]
    }

    assert intermediate_statuses == {
        "EVIDENCE-MAIN": "approved",
        "EVIDENCE-SI": "stale",
    }
    assert intermediate_workflow["parse_ready"] is False
    assert intermediate_workflow["paper_evidence_ready"] is False
    assert intermediate_workflow["active_stage"] == "parsing"
    assert intermediate_workflow["blockers"] == ["PARSE_QUALITY_REVIEW_REQUIRED"]
    assert gate_path.read_bytes() == gate_before

    refreshed_gate = write_parse_quality_gate(project, "STUDY-CANARY")
    refreshed_main = next(
        row
        for row in refreshed_gate["objects"]
        if row["source_id"] == "CANARY_MAIN" and row["kind"] == "reference_boundary"
    )
    assert refreshed_main["object_digest"] == digests[("CANARY_MAIN", "reference_boundary")]
    assert refreshed_main["status"] == "usable_with_review"
    assert refreshed_main["decision"] is None

    refreshed_evidence = paper_evidence_state(project)
    refreshed_workflow = workflow_state(project)
    refreshed_statuses = {
        row["evidence_id"]: row["status"] for row in refreshed_evidence["rows"]
    }
    assert refreshed_statuses == {
        "EVIDENCE-MAIN": "approved",
        "EVIDENCE-SI": "stale",
    }
    assert refreshed_workflow["parse_ready"] is False
    assert refreshed_workflow["paper_evidence_ready"] is False
    assert refreshed_workflow["active_stage"] == "parsing"
    assert refreshed_workflow["blockers"] == ["PARSE_QUALITY_REVIEW_REQUIRED"]


def test_explicit_parse_decision_downgrade_stales_dependent_parsed_evidence(
    tmp_path: Path,
) -> None:
    project = _canonical_prepare_project(tmp_path, si_policy="NOT_REQUIRED")
    parse = parse_quality_state(project, "STUDY-CANARY")
    dependency = next(
        row
        for row in parse["objects"]
        if row["source_id"] == "CANARY_MAIN" and row["kind"] == "reference_boundary"
    )
    candidate = {
        **_typed_paper_candidate(project),
        "bound_parse_object_digests": [dependency["object_digest"]],
    }
    registered = register_paper_evidence_candidates(
        project,
        "STUDY-CANARY",
        candidate,
    )["candidates"][0]
    apply_paper_evidence_decision(project, _paper_decision(registered))

    downgraded = apply_parse_quality_decision(
        project,
        "STUDY-CANARY",
        {
            "object_id": dependency["object_id"],
            "object_digest": dependency["object_digest"],
            "gate_digest": parse["gate_digest"],
            "action": "pdf_locator_only",
            "note": "Parsed evidence is no longer authorized for this object.",
        },
    )
    downgraded_dependency = next(
        row for row in downgraded["objects"] if row["object_id"] == dependency["object_id"]
    )
    assert downgraded_dependency["decision"]["action"] == "pdf_locator_only"

    evidence = paper_evidence_state(project)
    workflow = workflow_state(project)

    assert evidence["rows"][0]["status"] == "stale"
    assert evidence["rows"][0]["reason_code"] == "PARSE_OBJECT_DECISION_STALE"
    assert evidence["workflow_can_continue"] is False
    assert workflow["parse_ready"] is True
    assert workflow["paper_evidence_ready"] is False
    assert workflow["active_stage"] == "evidence"
    assert workflow["blockers"] == ["PAPER_EVIDENCE_NOT_APPROVED"]


def _run_paper_cli(command: str, project: Path, payload: dict, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    input_path = tmp_path / f"{command}.json"
    _write_prepare_json(input_path, payload)
    args = [
        sys.executable,
        str(CLI),
        command,
        "--project",
        str(project),
        "--input",
        str(input_path),
    ]
    if command == "register-paper-evidence":
        args.extend(["--study-id", "STUDY-CANARY"])
    return subprocess.run(
        args,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_paper_evidence_cli_reports_only_researcher_safe_summary(
    tmp_path: Path,
) -> None:
    project = _canonical_prepare_project(tmp_path, si_policy="NOT_REQUIRED")
    _declare_canonical_study(project)
    candidate = _typed_paper_candidate(project)

    registered = _run_paper_cli("register-paper-evidence", project, candidate, tmp_path)

    assert registered.returncode == 0, registered.stderr
    register_summary = json.loads(registered.stdout)
    assert set(register_summary) == {"candidate_count", "reason_code", "status"}
    assert register_summary == {
        "candidate_count": 1,
        "reason_code": "PAPER_EVIDENCE_REGISTERED",
        "status": "NEEDS_REVIEW",
    }
    candidate_set = json.loads(
        (
            project
            / "01_evidence/STUDY-CANARY/paper_evidence_candidates.json"
        ).read_text(encoding="utf-8")
    )
    row = candidate_set["candidates"][0]
    recorded = _run_paper_cli("record-paper-evidence", project, _paper_decision(row), tmp_path)

    assert recorded.returncode == 0, recorded.stderr
    record_summary = json.loads(recorded.stdout)
    assert set(record_summary) == {
        "approved_count",
        "needs_review_count",
        "reason_code",
        "rejected_count",
        "stale_count",
        "status",
        "total_count",
    }
    assert record_summary == {
        "approved_count": 1,
        "needs_review_count": 0,
        "reason_code": "PAPER_EVIDENCE_READY",
        "rejected_count": 0,
        "stale_count": 0,
        "status": "APPROVED",
        "total_count": 1,
    }
    combined = registered.stdout + recorded.stdout
    for private_value in (
        candidate["statement"],
        candidate["locator"]["exact_quote"],
        str(project),
        row["candidate_digest"],
        row["source_pdf_sha256"],
    ):
        assert private_value not in combined


def test_paper_evidence_cli_failure_uses_stable_safe_code(tmp_path: Path) -> None:
    project = _canonical_prepare_project(tmp_path, si_policy="NOT_REQUIRED")
    _declare_canonical_study(project)
    invalid = {**_typed_paper_candidate(project), "epistemic_type": "review_synthesis"}

    result = _run_paper_cli("register-paper-evidence", project, invalid, tmp_path)

    assert result.returncode == 2
    assert json.loads(result.stderr) == {
        "error_code": "EPISTEMIC_TYPE_INVALID",
        "status": "ERROR",
    }


def test_manual_pdf_evidence_cli_requires_pdf_locator_gate_and_hides_content(
    tmp_path: Path,
) -> None:
    project = _canonical_prepare_project(tmp_path, si_policy="NOT_REQUIRED")
    _declare_canonical_study(project)
    state = parse_quality_state(project, "STUDY-CANARY")
    for row in state["objects"]:
        if row["status"] == "usable":
            continue
        state = apply_parse_quality_decision(
            project,
            "STUDY-CANARY",
            {
                "object_id": row["object_id"],
                "object_digest": row["object_digest"],
                "gate_digest": state["gate_digest"],
                "action": "pdf_locator_only",
                "note": "Manual original-PDF evidence is required.",
            },
        )
    payload = {
        "study_id": "STUDY-CANARY",
        **_typed_paper_candidate(project),
        "locator": {
            "source_mode": "original_pdf_manual",
            "page": 1,
            "section_or_item": "Results",
            "figure_or_table": None,
            "exact_quote": "Manually verified source wording.",
        },
        "bound_parse_object_digests": [],
    }

    result = _run_paper_cli("register-manual-pdf-evidence", project, payload, tmp_path)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "candidate_count": 1,
        "reason_code": "MANUAL_PDF_EVIDENCE_REGISTERED",
        "status": "NEEDS_REVIEW",
    }
    assert payload["statement"] not in result.stdout
    assert payload["locator"]["exact_quote"] not in result.stdout
    assert str(project) not in result.stdout


def test_new_route_writer_packet_exposes_source_figures_and_no_generated_map(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _source_truth_project(tmp_path)
    write_source_truth_bundle(project, "scholarly-a")

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("new route must not call the legacy Pillow renderer")

    monkeypatch.setattr(vertical_review, "_build_comparative_evidence_figure", forbidden)
    packet = build_writer_packet(project)

    assert packet["figure_policy"] == "source_figures_or_synthesis_placeholders_only"
    assert packet["figures"]
    assert not (project / "03_figure_redraw/comparative_evidence_map.png").exists()
