from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "agent-orchestration"))

from scheduler_contract import (  # noqa: E402
    MAX_ATTEMPTS,
    SPEC_FAILURE_CODES,
    TERMINATION_REPORT_FIELDS,
    TIME_BUDGET_SECONDS,
    UNKNOWN,
    ImmutableTaskChanged,
    PostT0UserActionRejected,
    SchedulerContractError,
    SchedulerSession,
    AttemptLimitExceeded,
    immutable_task_digest,
)


UTC = timezone.utc
START = datetime(2026, 8, 2, 1, 0, tzinfo=UTC)


def _task_digest() -> str:
    return immutable_task_digest(
        {"task_id": "CONTENT-001", "objective": "bounded immutable task"}
    )


def _start_session(path: Path, label: str = "fresh-session-0") -> SchedulerSession:
    session = SchedulerSession.open(path, session_label=label, run_id="run-001")
    session.start_attempt(
        task_id="CONTENT-001",
        task_digest=_task_digest(),
        at=START,
    )
    return session


def test_two_fresh_sessions_take_over_from_persistent_ledger(tmp_path: Path) -> None:
    ledger_path = tmp_path / "scheduler-ledger.json"
    _start_session(ledger_path)

    second = SchedulerSession.open(ledger_path, session_label="fresh-session-1")
    second.takeover(at=START + timedelta(minutes=5))
    third = SchedulerSession.open(ledger_path, session_label="fresh-session-2")
    third.takeover(at=START + timedelta(minutes=10))

    state = third.read()
    assert state["takeover_count"] == 2
    assert len(state["takeovers"]) == 2
    assert state["current_scheduler_session"] == "fresh-session-2"
    assert all(
        (ledger_path.parent / row["handoff_artifact"]).is_file()
        for row in state["takeovers"]
    )
    for row in state["takeovers"]:
        artifact = json.loads(
            (ledger_path.parent / row["handoff_artifact"]).read_text(encoding="utf-8")
        )
        assert artifact["event"] == "fresh_session_takeover"
        assert artifact["task_id"] == "CONTENT-001"
        assert artifact["task_digest"] == _task_digest()
        assert artifact["user_actions_after_t0"] == 0


def test_immutable_task_is_limited_to_two_attempts(tmp_path: Path) -> None:
    ledger_path = tmp_path / "scheduler-ledger.json"
    session = _start_session(ledger_path)
    session.finish_attempt(status="BLOCKED", at=START + timedelta(minutes=1))
    session.start_attempt(
        task_id="CONTENT-001",
        task_digest=_task_digest(),
        at=START + timedelta(minutes=2),
    )
    session.finish_attempt(status="BLOCKED", at=START + timedelta(minutes=3))

    with pytest.raises(AttemptLimitExceeded):
        session.start_attempt(
            task_id="CONTENT-001",
            task_digest=_task_digest(),
            at=START + timedelta(minutes=4),
        )

    assert session.read()["attempt_count"] == MAX_ATTEMPTS == 2


def test_immutable_task_digest_cannot_change_between_attempts(tmp_path: Path) -> None:
    ledger_path = tmp_path / "scheduler-ledger.json"
    session = _start_session(ledger_path)
    session.finish_attempt(status="BLOCKED", at=START + timedelta(minutes=1))

    with pytest.raises(ImmutableTaskChanged):
        session.start_attempt(
            task_id="CONTENT-001",
            task_digest=immutable_task_digest(
                {"task_id": "CONTENT-001", "objective": "changed task"}
            ),
            at=START + timedelta(minutes=2),
        )


def test_timeout_uses_fixed_43200_second_budget_and_report(tmp_path: Path) -> None:
    ledger_path = tmp_path / "scheduler-ledger.json"
    session = _start_session(ledger_path)
    session.record_t0(
        input_ready=True,
        code_freeze_ready=True,
        runtime_ready=True,
        at=START,
    )

    with pytest.raises(SchedulerContractError):
        session.terminate(
            reason_code="TIME_BUDGET_EXCEEDED",
            blockers=["too early"],
            affected_objects=["CONTENT-001"],
            completed_independent_work=["none"],
            unique_recovery_action="wait for the fixed budget",
            at=START + timedelta(seconds=TIME_BUDGET_SECONDS - 1),
        )

    assert session.check_budget(at=START + timedelta(seconds=TIME_BUDGET_SECONDS - 1)) is None
    report = session.check_budget(at=START + timedelta(seconds=TIME_BUDGET_SECONDS))

    assert report is not None
    assert report.fields["REASON_CODE"] == "TIME_BUDGET_EXCEEDED"
    assert report.fields["ELAPSED_SECONDS"] == TIME_BUDGET_SECONDS
    assert report.fields["TIME_BUDGET_SECONDS"] == 43200
    assert report.fields["USER_ACTIONS_AFTER_T0"] == 0
    assert report.path.is_file()


def test_caller_elapsed_cannot_earn_timeout_before_persisted_t0_budget(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "scheduler-ledger.json"
    session = _start_session(ledger_path)
    session.record_t0(
        input_ready=True,
        code_freeze_ready=True,
        runtime_ready=True,
        at=START,
    )

    with pytest.raises(SchedulerContractError):
        session.terminate(
            reason_code="TIME_BUDGET_EXCEEDED",
            blockers=["caller supplied an early timeout"],
            affected_objects=["CONTENT-001"],
            completed_independent_work=["none"],
            unique_recovery_action="wait for the fixed budget",
            at=START + timedelta(seconds=1),
            elapsed_seconds=TIME_BUDGET_SECONDS,
        )

    assert session.read()["termination_report_artifact"] is None


def test_persisted_t0_budget_overrides_underreported_elapsed_and_reason(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "scheduler-ledger.json"
    session = _start_session(ledger_path)
    session.record_t0(
        input_ready=True,
        code_freeze_ready=True,
        runtime_ready=True,
        at=START,
    )

    report = session.terminate(
        reason_code="ORCHESTRATION_BLOCKED",
        blockers=["caller underreported elapsed time"],
        affected_objects=["CONTENT-001"],
        completed_independent_work=["none"],
        unique_recovery_action="start a fresh scheduler session from the ledger",
        at=START + timedelta(seconds=TIME_BUDGET_SECONDS + 1),
        elapsed_seconds=1,
    )

    assert report.fields["REASON_CODE"] == "TIME_BUDGET_EXCEEDED"
    assert report.fields["ELAPSED_SECONDS"] == TIME_BUDGET_SECONDS + 1


def test_blocker_writes_exact_spec_termination_report_with_precise_reason(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "scheduler-ledger.json"
    session = _start_session(ledger_path)
    report = session.terminate(
        reason_code="ORCHESTRATION_BLOCKED",
        blockers=["scheduler ledger unreadable"],
        affected_objects=["CONTENT-001"],
        completed_independent_work=["focused contract tests"],
        unique_recovery_action="restore the ledger and start a fresh scheduler session",
        at=START + timedelta(minutes=2),
    )

    assert report.fields["REASON_CODE"] in SPEC_FAILURE_CODES
    assert tuple(report.fields) == TERMINATION_REPORT_FIELDS
    assert report.fields["REASON_CODE"] == "ORCHESTRATION_BLOCKED"
    assert report.fields["BLOCKERS"][:1] == ["scheduler ledger unreadable"]
    assert "AUTHORITY_UNKNOWN" in report.fields["BLOCKERS"]
    assert "RUN_STATE_UNKNOWN" in report.fields["BLOCKERS"]
    assert report.fields["USER_ACTIONS_AFTER_T0"] == 0
    assert report.path.read_text(encoding="utf-8").splitlines() == [
        f"{key}={report.render_value(report.fields[key])}"
        for key in TERMINATION_REPORT_FIELDS
    ]


def test_termination_report_persists_authority_and_run_state_semantics(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "scheduler-ledger.json"
    authority_path = tmp_path / "authority.txt"
    authority_path.write_text(
        "\n".join(
            (
                "SPEC_ID=review-writer-next-phase-2026-08-01",
                "FROZEN_CODE_HEAD=" + "a" * 40,
                "AUTHORITATIVE_PROJECT_ID=olefin-review-v1",
                "CORPUS_STUDY_COUNT=24",
                "CORE_STUDY_IDS=study-001,study-002,study-003",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    run_state_path = tmp_path / "run-state.json"
    run_state_path.write_text(
        json.dumps(
            {
                "gates": {
                    "SCALED_CODE_READY": "OK",
                    "SCALED_INPUT_READY": "BLOCKED",
                    "SCALED_RUNTIME_READY": "OK",
                    "SCALED_REVIEW_READY": "UNKNOWN",
                },
                "counts": {
                    "CONFIRMED_COUNT": 17,
                    "AI_PROVISIONAL_COUNT": 4,
                    "BLOCKED_COUNT": 3,
                },
                "artifacts": {
                    "PER_STUDY_COVERAGE_ARTIFACT": "reports/per-study-coverage.json",
                    "GAP_REGISTRY_ARTIFACT": "reports/gap-registry.json",
                    "PAPER_EVIDENCE_CURRENT": "evidence/paper-evidence.json",
                    "ARTIFACT_MANIFEST": "release/artifact-manifest.json",
                },
                "PAPER_EVIDENCE_DISPOSITIONED": "OK",
                "SYNTHESIS_CURRENT": "synthesis/current.json",
                "MANUSCRIPT_CURRENT": "manuscript/current.md",
                "CLAIM_SOURCE_AUDIT": "audit/claim-source.json",
                "BENCHMARK_SCORE": 88,
                "BENCHMARK_HARD_FAILS": [],
                "BENCHMARK_ROUNDS": 1,
                "DOCX_READY": True,
                "PDF_READY": False,
                "OWNER_REPORTS": ["reports/owner-001.json"],
                "FOCUSED_TESTS": "2 passed",
                "SMOKE": "PASS",
                "QUALITY_CHECK": "PASS",
                "GIT_SHOW_CHECK": "PASS",
                "GIT_STATUS": "clean",
                "MVP_BACKLOG": ["third theme deferred"],
                "blockers": ["INPUT_BUNDLE_INCOMPLETE"],
                "affected_objects": ["study-003"],
                "completed_independent_work": ["scheduler replay", "source audit"],
                "unique_recovery_action": "complete the missing input bundle",
            }
        ),
        encoding="utf-8",
    )

    session = SchedulerSession.open(
        ledger_path,
        session_label="fresh-session-0",
        run_id="run-001",
        authority_path=authority_path,
        run_state_path=run_state_path,
    )
    session.start_attempt(
        task_id="CONTENT-001",
        task_digest=_task_digest(),
        at=START,
    )
    session.record_t0(
        input_ready=True,
        code_freeze_ready=True,
        runtime_ready=True,
        at=START,
    )
    report = session.terminate(
        reason_code="INPUT_BLOCKED",
        blockers=["input bundle is incomplete"],
        affected_objects=["CONTENT-001"],
        completed_independent_work=["focused contract tests"],
        unique_recovery_action="complete the missing input bundle",
        at=START + timedelta(minutes=2),
    )

    assert report.fields["FROZEN_CODE_HEAD"] == "a" * 40
    assert report.fields["AUTHORITATIVE_PROJECT_ID"] == "olefin-review-v1"
    assert report.fields["CORPUS_STUDY_COUNT"] == 24
    assert report.fields["CORE_STUDY_COUNT"] == 3
    assert report.fields["T0"] == "2026-08-02T01:00:00Z"
    assert report.fields["ELAPSED_SECONDS"] == 120
    assert report.fields["SCALED_CODE_READY"] == "OK"
    assert report.fields["SCALED_INPUT_READY"] == "BLOCKED"
    assert report.fields["SCALED_REVIEW_READY"] == "UNKNOWN"
    assert report.fields["PER_STUDY_COVERAGE_ARTIFACT"] == "reports/per-study-coverage.json"
    assert report.fields["GAP_REGISTRY_ARTIFACT"] == "reports/gap-registry.json"
    assert report.fields["CONFIRMED_COUNT"] == 17
    assert report.fields["BENCHMARK_SCORE"] == 88
    assert report.fields["DOCX_READY"] == "true"
    assert report.fields["PDF_READY"] == "false"
    assert report.fields["AFFECTED_OBJECTS"] == ["CONTENT-001", "study-003"]
    assert report.fields["COMPLETED_INDEPENDENT_WORK"] == [
        "focused contract tests",
        "scheduler replay",
        "source audit",
    ]
    assert report.fields["UNIQUE_RECOVERY_ACTION"] == "complete the missing input bundle"
    assert report.lineage["FROZEN_CODE_HEAD"] == "authority:FROZEN_CODE_HEAD"
    assert report.lineage["SCALED_CODE_READY"] == "run_state:gates.SCALED_CODE_READY"

    reopened = SchedulerSession.open(ledger_path, session_label="fresh-session-1")
    replayed = reopened.terminate(
        reason_code="ORCHESTRATION_BLOCKED",
        blockers=["a different caller must not rewrite the report"],
        affected_objects=["different-object"],
        completed_independent_work=["different work"],
        unique_recovery_action="different recovery",
        at=START + timedelta(minutes=3),
    )
    assert replayed.fields == report.fields
    assert replayed.lineage == report.lineage
    assert "/" not in report.path.read_text(encoding="utf-8").split("FROZEN_CODE_HEAD=", 1)[1].splitlines()[0]


def test_missing_authority_and_absolute_artifact_are_unknown_and_blocked(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "scheduler-ledger.json"
    run_state_path = tmp_path / "run-state.json"
    run_state_path.write_text(
        json.dumps(
            {
                "gates": {"SCALED_CODE_READY": True},
                "artifacts": {"ARTIFACT_MANIFEST": "/private/project/manifest.json"},
            }
        ),
        encoding="utf-8",
    )
    session = SchedulerSession.open(
        ledger_path,
        session_label="fresh-session-0",
        run_id="run-001",
        run_state_path=run_state_path,
    )
    session.start_attempt(task_id="CONTENT-001", task_digest=_task_digest(), at=START)
    report = session.terminate(
        reason_code="ORCHESTRATION_BLOCKED",
        blockers=["authority record is unavailable"],
        affected_objects=["CONTENT-001"],
        completed_independent_work=["ledger replay"],
        unique_recovery_action="record authority before resuming",
        at=START + timedelta(minutes=1),
    )

    assert report.fields["FROZEN_CODE_HEAD"] == "UNKNOWN"
    assert report.fields["AUTHORITATIVE_PROJECT_ID"] == "UNKNOWN"
    assert report.fields["CORPUS_STUDY_COUNT"] == "UNKNOWN"
    assert report.fields["CORE_STUDY_COUNT"] == "UNKNOWN"
    assert report.fields["SCALED_CODE_READY"] == "OK"
    assert report.fields["ARTIFACT_MANIFEST"] == "UNKNOWN"
    assert any("AUTHORITY_UNKNOWN" in blocker for blocker in report.fields["BLOCKERS"])
    assert any("ARTIFACT_REFERENCE_INVALID" in blocker for blocker in report.fields["BLOCKERS"])
    rendered = report.path.read_text(encoding="utf-8")
    assert "/private/project/manifest.json" not in rendered
    assert "/home/" not in rendered


@pytest.mark.parametrize(
    "invalid_reference",
    [
        True,
        False,
        "OK",
        "BLOCKED",
        "NOT_READY",
        "READY",
        "PASS",
        "FAILED",
        "TIMEOUT",
        "ENVIRONMENT_UNDETERMINED",
        "true",
        "false",
        "captured-by-orchestrator",
        "opaque-session-marker",
        "/private/project/manifest.json",
        "/home/private/project/manifest.json",
    ],
    ids=lambda value: str(value).replace("/", "-").replace(" ", "-"),
)
def test_artifact_reference_contract_rejects_pseudo_references(
    tmp_path: Path,
    invalid_reference: object,
) -> None:
    ledger_path = tmp_path / "scheduler-ledger.json"
    run_state_path = tmp_path / "run-state.json"
    run_state_path.write_text(
        json.dumps(
            {
                "artifacts": {"ARTIFACT_MANIFEST": invalid_reference},
                "PAPER_EVIDENCE_DISPOSITIONED": "OK",
            }
        ),
        encoding="utf-8",
    )
    session = SchedulerSession.open(
        ledger_path,
        session_label="fresh-session-0",
        run_id="run-001",
        run_state_path=run_state_path,
    )
    session.start_attempt(task_id="CONTENT-001", task_digest=_task_digest(), at=START)

    report = session.terminate(
        reason_code="ORCHESTRATION_BLOCKED",
        blockers=["artifact reference is not authoritative"],
        affected_objects=["CONTENT-001"],
        completed_independent_work=["ledger replay"],
        unique_recovery_action="record a stable artifact reference",
        at=START + timedelta(minutes=1),
    )

    assert report.fields["ARTIFACT_MANIFEST"] == UNKNOWN
    assert report.fields["PAPER_EVIDENCE_DISPOSITIONED"] == "OK"
    assert "ARTIFACT_REFERENCE_INVALID" in report.fields["BLOCKERS"]
    assert "ARTIFACT_MANIFEST=UNKNOWN" in report.path.read_text(encoding="utf-8")

    reopened = SchedulerSession.open(ledger_path, session_label="fresh-session-1")
    replayed = reopened.terminate(
        reason_code="ORCHESTRATION_BLOCKED",
        blockers=["replay must not promote a pseudo-reference"],
        affected_objects=["CONTENT-001"],
        completed_independent_work=["ledger replay"],
        unique_recovery_action="record a stable artifact reference",
        at=START + timedelta(minutes=2),
    )
    assert replayed.fields["ARTIFACT_MANIFEST"] == UNKNOWN


def test_t0_rejects_user_action_and_keeps_fixed_zero(tmp_path: Path) -> None:
    ledger_path = tmp_path / "scheduler-ledger.json"
    session = _start_session(ledger_path)
    session.record_t0(
        input_ready=True,
        code_freeze_ready=True,
        runtime_ready=True,
        at=START,
    )

    with pytest.raises(PostT0UserActionRejected):
        session.record_user_action("researcher decision")

    state = session.read()
    assert state["t0"] == "2026-08-02T01:00:00Z"
    assert state["user_actions_after_t0"] == 0
