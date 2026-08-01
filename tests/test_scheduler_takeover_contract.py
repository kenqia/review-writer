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
    assert report.fields["BLOCKERS"] == ["scheduler ledger unreadable"]
    assert report.fields["USER_ACTIONS_AFTER_T0"] == 0
    assert report.path.read_text(encoding="utf-8").splitlines() == [
        f"{key}={report.render_value(report.fields[key])}"
        for key in TERMINATION_REPORT_FIELDS
    ]


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
