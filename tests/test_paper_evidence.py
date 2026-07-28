from __future__ import annotations

from pathlib import Path

import pytest

from review_writer.project.legacy_evidence_adapter import adapt_legacy_evidence
from review_writer.project.paper_evidence import (
    PaperEvidenceError,
    apply_paper_evidence_decision,
    current_source_pdf_sha256,
    paper_evidence_state,
    register_manual_pdf_evidence,
    register_paper_evidence_candidates,
    require_paper_evidence_ready,
)
from review_writer.project.parse_quality import (
    apply_parse_quality_decision,
    parse_quality_state,
    write_parse_quality_gate,
)
from review_writer.project.source_truth import write_source_truth_bundle
from test_source_truth import _source_truth_project


STUDY_ID = "scholarly-a"


def _approve_parse(project: Path, *, pdf_locator_only: bool = False) -> dict:
    write_source_truth_bundle(project, STUDY_ID)
    state = write_parse_quality_gate(project, STUDY_ID)
    for row in state["objects"]:
        if row["status"] == "usable":
            continue
        state = apply_parse_quality_decision(
            project,
            STUDY_ID,
            {
                "object_id": row["object_id"],
                "object_digest": row["object_digest"],
                "gate_digest": state["gate_digest"],
                "action": (
                    "pdf_locator_only" if pdf_locator_only else "approve_candidate_extraction"
                ),
                "note": "Compared with the original PDF.",
            },
        )
    return state


@pytest.fixture
def project(tmp_path: Path) -> Path:
    value = _source_truth_project(tmp_path)
    _approve_parse(value)
    return value


def candidate(*, epistemic_type: str = "experimental_observation") -> dict:
    return {
        "evidence_id": "EVIDENCE-001",
        "source_id": "stud-a",
        "epistemic_type": epistemic_type,
        "statement": "The reported intervention produced the measured outcome.",
        "locator": {
            "source_mode": "parsed_candidate",
            "page": 1,
            "section_or_item": "Results",
            "figure_or_table": None,
            "exact_quote": "The measured outcome was observed.",
        },
        "reported_conditions": ["Synthetic condition"],
        "quantitative_results": ["Synthetic result"],
        "limitations": ["Single-study observation"],
        "mechanism_grade": "not_applicable",
        "risk_classes": ["MECHANISM_CAUSALITY"],
    }


def candidate_without_type() -> dict:
    value = candidate()
    value.pop("epistemic_type")
    return value


def pdf_locator_only_project(tmp_path: Path) -> Path:
    value = _source_truth_project(tmp_path)
    _approve_parse(value, pdf_locator_only=True)
    return value


def manual_pdf_payload(*, page: int) -> dict:
    value = candidate()
    value["locator"] = {
        **value["locator"],
        "source_mode": "original_pdf_manual",
        "page": page,
    }
    return {"study_id": STUDY_ID, **value}


def legacy_card(*, decision: str) -> dict:
    return {
        "claim_id": "legacy-claim-1",
        "claim_text": "A legacy candidate statement.",
        "decision": decision,
        "evidence_refs": [
            {
                "source_id": "legacy-source",
                "page": 2,
                "section_or_item": "Results",
                "exact_quote": "Legacy source wording.",
            }
        ],
        "risk_categories": ["MECHANISM_CAUSALITY"],
    }


def _decision(row: dict, *, action: str = "approve", **extra: object) -> dict:
    return {
        "evidence_id": row["evidence_id"],
        "candidate_digest": row["candidate_digest"],
        "bound_parse_object_digests": row["bound_parse_object_digests"],
        "source_pdf_sha256": row["source_pdf_sha256"],
        "action": action,
        "reason": "Checked against the cited source.",
        **extra,
    }


def _register(project: Path, payload: dict | None = None) -> dict:
    result = register_paper_evidence_candidates(project, STUDY_ID, payload or candidate())
    return result["candidates"][0]


def test_paper_evidence_requires_epistemic_type(project: Path) -> None:
    with pytest.raises(PaperEvidenceError, match="EPISTEMIC_TYPE_REQUIRED"):
        register_paper_evidence_candidates(project, STUDY_ID, candidate_without_type())


def test_review_synthesis_is_forbidden_in_single_paper_evidence(project: Path) -> None:
    with pytest.raises(PaperEvidenceError, match="EPISTEMIC_TYPE_INVALID"):
        register_paper_evidence_candidates(
            project,
            STUDY_ID,
            candidate(epistemic_type="review_synthesis"),
        )


def test_pdf_locator_only_accepts_manual_hash_bound_evidence(tmp_path: Path) -> None:
    project = pdf_locator_only_project(tmp_path)
    row = register_manual_pdf_evidence(project, manual_pdf_payload(page=1))

    assert row["locator"]["source_mode"] == "original_pdf_manual"
    assert row["source_pdf_sha256"] == current_source_pdf_sha256(project)


def test_legacy_approved_claim_becomes_unapproved_candidate() -> None:
    adapted = adapt_legacy_evidence(legacy_card(decision="APPROVED"))

    assert adapted["origin"] == "legacy_candidate"
    assert adapted["status"] == "needs_review"
    assert "epistemic_type" not in adapted


def test_candidate_registration_writes_strict_unapproved_contract(project: Path) -> None:
    row = _register(project)

    assert row["study_id"] == STUDY_ID
    assert row["decision"] is None
    assert len(row["candidate_digest"]) == 64
    assert row["bound_parse_object_digests"]
    assert (
        project / f"01_evidence/{STUDY_ID}/paper_evidence_candidates.json"
    ).is_file()
    projection = paper_evidence_state(project)
    assert projection["reason_code"] == "PAPER_EVIDENCE_REVIEW_REQUIRED"
    assert projection["workflow_can_continue"] is False


def test_mechanism_grade_is_independent_from_epistemic_type(project: Path) -> None:
    payload = {**candidate(), "mechanism_grade": "direct_support"}

    row = _register(project, payload)

    assert row["epistemic_type"] == "experimental_observation"
    assert row["mechanism_grade"] == "direct_support"


def test_locator_page_must_exist_in_current_source(project: Path) -> None:
    payload = candidate()
    payload["locator"] = {**payload["locator"], "page": 2}

    with pytest.raises(PaperEvidenceError, match="LOCATOR_PAGE_INVALID"):
        register_paper_evidence_candidates(project, STUDY_ID, payload)


def test_current_hash_bound_approval_unlocks_paper_evidence(project: Path) -> None:
    row = _register(project)

    approved = apply_paper_evidence_decision(project, _decision(row))

    assert approved["status"] == "approved"
    assert paper_evidence_state(project)["workflow_can_continue"] is True
    assert require_paper_evidence_ready(project) == paper_evidence_state(project)[
        "projection_digest"
    ]


def test_revise_and_approve_requires_and_projects_replacement(project: Path) -> None:
    row = _register(project)
    payload = _decision(row, action="revise_and_approve")

    with pytest.raises(PaperEvidenceError, match="REPLACEMENT_STATEMENT_REQUIRED"):
        apply_paper_evidence_decision(project, payload)

    revised = apply_paper_evidence_decision(
        project,
        {**payload, "replacement_statement": "A narrower researcher-approved statement."},
    )
    assert revised["statement"] == "A narrower researcher-approved statement."
    assert revised["candidate_digest"] == row["candidate_digest"]


def test_reject_is_settled_but_cannot_supply_required_approved_evidence(project: Path) -> None:
    row = _register(project)

    rejected = apply_paper_evidence_decision(project, _decision(row, action="reject"))
    state = paper_evidence_state(project)

    assert rejected["status"] == "rejected"
    assert state["reason_code"] == "PAPER_EVIDENCE_APPROVED_ROW_MISSING"
    assert state["workflow_can_continue"] is False


def test_decision_rejects_any_noncurrent_binding(project: Path) -> None:
    row = _register(project)

    with pytest.raises(PaperEvidenceError, match="EVIDENCE_DECISION_STALE"):
        apply_paper_evidence_decision(
            project,
            {**_decision(row), "source_pdf_sha256": "0" * 64},
        )


def test_exact_decision_rerun_is_idempotent_across_other_evidence(project: Path) -> None:
    first = candidate()
    second = candidate()
    second.update({"evidence_id": "EVIDENCE-002", "statement": "A second observation."})
    result = register_paper_evidence_candidates(
        project,
        STUDY_ID,
        {"candidates": [first, second]},
    )
    first_row, second_row = result["candidates"]
    apply_paper_evidence_decision(project, _decision(first_row))
    apply_paper_evidence_decision(project, _decision(second_row))

    apply_paper_evidence_decision(project, _decision(first_row))

    decisions = (project / "01_evidence/paper_evidence_decisions.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(decisions) == 2


def test_parse_object_change_stales_only_dependent_row(project: Path) -> None:
    gate = parse_quality_state(project, STUDY_ID)
    by_kind = {row["kind"]: row["object_digest"] for row in gate["objects"]}
    first = {
        **candidate(),
        "bound_parse_object_digests": [by_kind["formula_chemistry"]],
    }
    second = {
        **candidate(),
        "evidence_id": "EVIDENCE-002",
        "statement": "A second observation.",
        "bound_parse_object_digests": [by_kind["body_order"]],
    }
    result = register_paper_evidence_candidates(
        project,
        STUDY_ID,
        {"candidates": [first, second]},
    )
    for row in result["candidates"]:
        apply_paper_evidence_decision(project, _decision(row))
    markdown = project / "01_evidence/mineru/markdown/10_1000_example.md"
    markdown.write_text("# Canonical\nBody with $x$.\n", encoding="utf-8")
    _approve_parse(project)

    state = paper_evidence_state(project)
    statuses = {row["evidence_id"]: row["status"] for row in state["rows"]}

    assert statuses == {"EVIDENCE-001": "stale", "EVIDENCE-002": "approved"}
    assert state["workflow_can_continue"] is False


def test_unknown_fields_and_duplicate_ids_fail_closed(project: Path) -> None:
    with pytest.raises(PaperEvidenceError, match="PAPER_EVIDENCE_UNKNOWN_FIELD"):
        register_paper_evidence_candidates(project, STUDY_ID, {**candidate(), "extra": True})
    with pytest.raises(PaperEvidenceError, match="EVIDENCE_ID_DUPLICATE"):
        register_paper_evidence_candidates(
            project,
            STUDY_ID,
            {"candidates": [candidate(), candidate()]},
        )


def test_candidate_output_symlink_is_rejected(project: Path, tmp_path: Path) -> None:
    target = tmp_path / "outside.json"
    target.write_text("{}\n", encoding="utf-8")
    candidate_path = project / f"01_evidence/{STUDY_ID}/paper_evidence_candidates.json"
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.symlink_to(target)

    with pytest.raises(PaperEvidenceError, match="PAPER_EVIDENCE_PATH_INVALID"):
        register_paper_evidence_candidates(project, STUDY_ID, candidate())

    assert target.read_text(encoding="utf-8") == "{}\n"


def test_manual_pdf_registration_is_forbidden_when_parse_is_automatic(project: Path) -> None:
    with pytest.raises(PaperEvidenceError, match="MANUAL_PDF_EVIDENCE_NOT_ALLOWED"):
        register_manual_pdf_evidence(project, manual_pdf_payload(page=1))


def test_legacy_adapter_does_not_invent_governed_fields() -> None:
    source = legacy_card(decision="APPROVED")
    original = dict(source)

    adapted = adapt_legacy_evidence(source)

    assert adapted["legacy_origin"] == "legacy_evidence_card"
    assert adapted["needs_reverification"] is True
    assert not {
        "epistemic_type",
        "bound_parse_object_digests",
        "counter_evidence",
        "comparison_axis",
        "decision",
    }.intersection(adapted)
    assert source == original
