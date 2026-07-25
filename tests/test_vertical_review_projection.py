from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

import review_writer.project.vertical_review as vertical_review
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


def _candidate(study_id: str, claims: list[dict]) -> dict:
    return {
        "schema_version": "evidence-candidate.v2",
        "job_id": f"JOB-{study_id}",
        "study_id": study_id,
        "claims": claims,
    }


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


def test_ambiguous_reviewer_blocks_low_risk_claim(tmp_path: Path) -> None:
    project = _initialize(tmp_path)

    result = register_study(
        project,
        _candidate("STUDY-AMBIGUOUS", [_claim("CLAIM-AMBIGUOUS")]),
        _r0("STUDY-AMBIGUOUS"),
        _reviewer("STUDY-AMBIGUOUS", verdict="AMBIGUOUS"),
    )

    assert result["claim_projection"][0]["decision"] == "BLOCKED"


@pytest.mark.parametrize(
    ("tamper", "code"),
    [
        ("candidate_job", "CANDIDATE_JOB_ID_INVALID"),
        ("r0_job", "R0_BINDING_INVALID"),
        ("r0_candidate_job", "R0_BINDING_INVALID"),
        ("reviewer_job", "REVIEWER_BINDING_INVALID"),
        ("reviewer_study", "REVIEWER_BINDING_INVALID"),
        ("reviewer_verdict", "REVIEWER_BINDING_INVALID"),
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
    else:
        reviewer["verdict"] = ""

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

    packet = build_writer_packet(project)

    assert [claim["claim_id"] for claim in packet["claims"]] == ["CLAIM-APPROVED"]
    assert all(claim["decision"] == "APPROVED" for claim in packet["claims"])
    assert packet["approved_claim_count"] == 1
    assert packet["human_required_count"] == 1
    assert packet["blocked_count"] == 1
    assert packet["known_exclusions"]
    assert {row["claim_id"] for row in packet["known_exclusions"]} == {
        "CLAIM-BLOCKED",
        "CLAIM-HUMAN",
    }


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
    build_writer_packet(project)
    assert writer_path.is_file()

    rebuild_projection(project)
    assert not writer_path.exists()

    build_writer_packet(project)
    apply_risk_decisions(
        project,
        {"decisions": [_bound_decision(project, "CLAIM-FRESHNESS", "EXCLUDE")]},
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
    build_writer_packet(project)
    assert writer_path.is_file()

    register_study(
        project,
        _candidate(study_id, [_claim(claim_id, text="Replacement text.")]),
        _r0(study_id),
        _reviewer(study_id),
    )

    assert not writer_path.exists()
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
    expected = hashlib.sha256(
        json.dumps(
            result["claim_projection"],
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
    build_risk_packet(project)

    projection = apply_risk_decisions(
        project,
        {
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


def test_apply_risk_decision_persists_current_review_target_digest(tmp_path: Path) -> None:
    project = _initialize(tmp_path)
    result = register_study(
        project,
        _candidate("STUDY-DECISION-DIGEST", [_claim("CLAIM-DECISION-DIGEST", risk_level="R3")]),
        _r0("STUDY-DECISION-DIGEST"),
        _reviewer("STUDY-DECISION-DIGEST"),
    )
    digest = result["claim_projection"][0]["review_target_digest"]

    apply_risk_decisions(
        project,
        {
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
    decision = _bound_decision(project, "CLAIM-COMMIT-FAILURE", "APPROVE")
    writer_path = project / "02_claims" / "writer_packet.json"
    projection_path = project / "02_claims" / "claim_projection.jsonl"
    decisions_path = project / "03_review" / "risk_decisions.json"
    build_writer_packet(project)
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
            apply_risk_decisions(project, {"decisions": [decision]})

    assert decisions_path.read_bytes() == decisions_before
    assert projection_path.read_bytes() != projection_before
    staged = json.loads(projection_path.read_text().splitlines()[0])
    assert staged["decision"] == "APPROVED"
    assert not writer_path.exists()
    for consumer in (build_writer_packet, build_risk_packet, benchmark_metrics):
        with pytest.raises(VerticalReviewError) as error:
            consumer(project)
        assert error.value.code == "PROJECTION_INVALID"

    recovered = apply_risk_decisions(project, {"decisions": [decision]})

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
    apply_risk_decisions(
        project,
        {"decisions": [old_decision]},
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
    packet = build_writer_packet(project)
    assert packet["claims"] == []
    assert packet["human_required_count"] == 1
    build_risk_packet(project)
    before = _authoritative_bytes(project)

    with pytest.raises(VerticalReviewError) as error:
        apply_risk_decisions(project, {"decisions": [old_decision]})

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
    build_risk_packet(project)
    build_writer_packet(project)
    before = _authoritative_bytes(project)

    with pytest.raises(VerticalReviewError) as error:
        apply_risk_decisions(
            project,
            {"decisions": [{"claim_id": "CLAIM-MISSING-DIGEST", "action": "APPROVE"}]},
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
    current_digest = _bound_decision(project, "CLAIM-RISK", "APPROVE")[
        "review_target_digest"
    ]
    bound_decisions = copy.deepcopy(decisions)
    for row in bound_decisions["decisions"]:
        row["review_target_digest"] = (
            current_digest if row.get("claim_id") == "CLAIM-RISK" else "unknown-target"
        )

    with pytest.raises(VerticalReviewError) as error:
        apply_risk_decisions(project, bound_decisions)

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
    assert second == first
    assert risk_path.read_bytes() == first_bytes


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
    build_risk_packet(project)
    apply_risk_decisions(
        project,
        {"decisions": [_bound_decision(project, "CLAIM-IMMUTABLE", "APPROVE")]},
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
        "init",
        "prepare-study",
        "prepare-batch",
        "register-study",
        "build-risk-packet",
        "apply-risk-decisions",
        "build-writer-packet",
        "metrics",
    ):
        assert command in help_result.stdout

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


def test_makefile_has_focused_vertical_projection_gate() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "vertical-review-projection-check:" in makefile
    assert (
        "\t$(PYTHON) -m pytest tests/test_vertical_review_projection.py -q"
        in makefile
    )
