"""Persistent, replaceable scheduler state for the next-phase run contract.

This module is deliberately a local state contract.  It does not launch Codex,
call a Dashboard/API, interpret scientific evidence, or retain a transport
session reference.  A fresh scheduler process can open the JSON ledger and
continue from the recorded state using only a bounded scheduler-session label.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping


SPEC_ID = "review-writer-next-phase-2026-08-01"
MAX_ATTEMPTS = 2
TIME_BUDGET_SECONDS = 43200

SPEC_FAILURE_CODES = frozenset(
    {
        "CODE_BLOCKED",
        "INPUT_BLOCKED",
        "PARSE_BLOCKED",
        "ORCHESTRATION_BLOCKED",
        "SCIENTIFIC_DECISION_BLOCKED",
        "CONTENT_EVIDENCE_BLOCKED",
        "SYNTHESIS_BLOCKED",
        "BENCHMARK_BLOCKED",
        "EXPORT_BLOCKED",
        "AUDIT_BLOCKED",
        "TIME_BUDGET_EXCEEDED",
    }
)

TERMINATION_REPORT_FIELDS = (
    "SPEC_ID",
    "RUN_ID",
    "FROZEN_CODE_HEAD",
    "AUTHORITATIVE_PROJECT_ID",
    "CORPUS_STUDY_COUNT",
    "CORE_STUDY_COUNT",
    "T0",
    "TERMINATED_AT",
    "ELAPSED_SECONDS",
    "TIME_BUDGET_SECONDS",
    "SCALED_CODE_READY",
    "SCALED_INPUT_READY",
    "SCALED_RUNTIME_READY",
    "SCALED_REVIEW_READY",
    "BLOCKERS",
    "REASON_CODE",
    "AFFECTED_OBJECTS",
    "COMPLETED_INDEPENDENT_WORK",
    "UNIQUE_RECOVERY_ACTION",
    "MAIN_PDF_READY",
    "SI_PDF_READY",
    "GENERIC_MAIN_READY",
    "GENERIC_SI_READY",
    "CHEMICAL_MAIN_READY",
    "CHEMICAL_CORE_SI_READY",
    "SOURCE_TRUTH_CURRENT",
    "CONFIRMED_COUNT",
    "AI_PROVISIONAL_COUNT",
    "BLOCKED_COUNT",
    "PER_STUDY_COVERAGE_ARTIFACT",
    "GAP_REGISTRY_ARTIFACT",
    "PAPER_EVIDENCE_CURRENT",
    "PAPER_EVIDENCE_DISPOSITIONED",
    "SYNTHESIS_CURRENT",
    "MANUSCRIPT_CURRENT",
    "CLAIM_SOURCE_AUDIT",
    "BENCHMARK_SCORE",
    "BENCHMARK_HARD_FAILS",
    "BENCHMARK_ROUNDS",
    "DOCX_READY",
    "PDF_READY",
    "ARTIFACT_MANIFEST",
    "ORCHESTRATOR_TAKEOVERS",
    "USER_ACTIONS_AFTER_T0",
    "OWNER_REPORTS",
    "FOCUSED_TESTS",
    "SMOKE",
    "QUALITY_CHECK",
    "GIT_SHOW_CHECK",
    "GIT_STATUS",
    "MVP_BACKLOG",
    "PUSHED",
    "DEPLOYED",
    "PLAN_CHECKBOX_CHANGED",
    "SENSITIVE_DATA_EXPOSED",
)

_ATTEMPT_TERMINAL_STATUSES = {"PASS", "BLOCKED", "TIMEOUT", "FAILED"}
_SESSION_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_TASK_ID = re.compile(r"^[A-Z][A-Z0-9-]{1,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ARTIFACT_REF = re.compile(r"^[A-Za-z0-9._/-]+$")


class SchedulerContractError(RuntimeError):
    """Base class for fail-closed scheduler contract violations."""


class AttemptLimitExceeded(SchedulerContractError):
    pass


class ImmutableTaskChanged(SchedulerContractError):
    pass


class AttemptInProgress(SchedulerContractError):
    pass


class DuplicateSessionTakeover(SchedulerContractError):
    pass


class InvalidReasonCode(SchedulerContractError):
    pass


class T0NotReady(SchedulerContractError):
    pass


class T0AlreadyRecorded(SchedulerContractError):
    pass


class PostT0UserActionRejected(SchedulerContractError):
    pass


class LedgerCorrupt(SchedulerContractError):
    pass


_TERMINAL_RUN_STATUSES = {"COMPLETE", "TERMINATED"}


@dataclass(frozen=True)
class TerminationReport:
    """The exact Spec 6.3 report plus its stable project-relative artifact path."""

    fields: dict[str, Any]
    path: Path

    @staticmethod
    def render_value(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (list, tuple)):
            return "; ".join(str(item) for item in value)
        return str(value)

    def to_text(self) -> str:
        return "\n".join(
            f"{key}={self.render_value(self.fields[key])}"
            for key in TERMINATION_REPORT_FIELDS
        ) + "\n"


def immutable_task_digest(task: Any) -> str:
    """Return the content digest used to prove that attempts share one task."""

    encoded = json.dumps(
        task,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime | None) -> str:
    current = value or _utc_now()
    if current.tzinfo is None:
        raise ValueError("scheduler timestamps must be timezone-aware")
    return current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise LedgerCorrupt("ledger timestamp is not timezone-aware")
    return parsed.astimezone(timezone.utc)


def _validate_label(value: str, kind: str) -> str:
    if not isinstance(value, str) or not _SESSION_LABEL.fullmatch(value):
        raise ValueError(f"invalid {kind}")
    return value


def _validate_task(task_id: str, task_digest: str) -> None:
    if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
        raise ValueError("invalid task_id")
    if not isinstance(task_digest, str) or not _SHA256.fullmatch(task_digest):
        raise ValueError("task_digest must be a lowercase SHA-256 hex digest")


def _validate_artifact_ref(value: str, kind: str) -> None:
    parts = value.split("/") if isinstance(value, str) else []
    if (
        not isinstance(value, str)
        or not value
        or value.startswith("/")
        or "\\" in value
        or not _ARTIFACT_REF.fullmatch(value)
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise LedgerCorrupt(f"invalid relative {kind} artifact reference")


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=str(path.parent),
        text=True,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    _atomic_write(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _new_state(run_id: str) -> dict[str, Any]:
    return {
        "schema_version": "scheduler-takeover-ledger.v1",
        "spec_id": SPEC_ID,
        "run_id": run_id,
        "status": "CREATED",
        "task_id": None,
        "task_digest": None,
        "attempt_count": 0,
        "max_attempts": MAX_ATTEMPTS,
        "attempts": [],
        "current_scheduler_session": None,
        "takeover_count": 0,
        "takeovers": [],
        "t0": None,
        "t0_gates": {
            "INPUT_READY": "NOT_READY",
            "CODE_FREEZE_READY": "NOT_READY",
            "RUNTIME_READY": "NOT_READY",
        },
        "user_actions_after_t0": 0,
        "termination_report_artifact": None,
    }


def _validate_state(state: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "spec_id",
        "run_id",
        "status",
        "task_id",
        "task_digest",
        "attempt_count",
        "max_attempts",
        "attempts",
        "current_scheduler_session",
        "takeover_count",
        "takeovers",
        "t0",
        "t0_gates",
        "user_actions_after_t0",
        "termination_report_artifact",
    }
    missing = required - set(state)
    if missing:
        raise LedgerCorrupt(f"ledger missing fields: {sorted(missing)}")
    if state["schema_version"] != "scheduler-takeover-ledger.v1":
        raise LedgerCorrupt("unsupported scheduler ledger schema")
    if state["spec_id"] != SPEC_ID:
        raise LedgerCorrupt("ledger Spec ID differs from approved Spec")
    if not isinstance(state["run_id"], str):
        raise LedgerCorrupt("invalid ledger run_id")
    _validate_label(state["run_id"], "run_id")
    if state["status"] not in {"CREATED", "RUNNING", "READY_FOR_RETRY", "COMPLETE", "TERMINATED"}:
        raise LedgerCorrupt("invalid scheduler ledger status")
    if state["max_attempts"] != MAX_ATTEMPTS:
        raise LedgerCorrupt("immutable task attempt cap is not fixed at two")
    if not isinstance(state["attempt_count"], int) or state["attempt_count"] < 0 or state["attempt_count"] > MAX_ATTEMPTS:
        raise LedgerCorrupt("invalid attempt count")
    if not isinstance(state["takeover_count"], int) or state["takeover_count"] < 0:
        raise LedgerCorrupt("invalid takeover count")
    if not isinstance(state["attempts"], list) or not isinstance(state["takeovers"], list):
        raise LedgerCorrupt("ledger history fields must be lists")
    if state["attempt_count"] != len(state["attempts"]):
        raise LedgerCorrupt("attempt count does not match attempt records")
    if state["takeover_count"] != len(state["takeovers"]):
        raise LedgerCorrupt("takeover count does not match takeover records")
    if not isinstance(state["user_actions_after_t0"], int) or state["user_actions_after_t0"] != 0:
        raise LedgerCorrupt("USER_ACTIONS_AFTER_T0 must remain zero")
    if state["task_id"] is None:
        if state["task_digest"] is not None or state["attempt_count"] != 0:
            raise LedgerCorrupt("unstarted ledger has task state")
    else:
        if not isinstance(state["task_id"], str) or not _TASK_ID.fullmatch(state["task_id"]):
            raise LedgerCorrupt("invalid ledger task_id")
        if not isinstance(state["task_digest"], str) or not _SHA256.fullmatch(state["task_digest"]):
            raise LedgerCorrupt("invalid ledger task_digest")
    if state["t0"] is not None:
        _parse_timestamp(state["t0"])
    if state["current_scheduler_session"] is not None:
        _validate_label(state["current_scheduler_session"], "scheduler session label")
    if state["termination_report_artifact"] is not None:
        _validate_artifact_ref(state["termination_report_artifact"], "termination report")
    for row in state["takeovers"]:
        if not isinstance(row, dict):
            raise LedgerCorrupt("takeover records must be objects")
        _validate_artifact_ref(row.get("handoff_artifact"), "handoff")
        if not isinstance(row.get("handoff_artifact_sha256"), str) or not _SHA256.fullmatch(row["handoff_artifact_sha256"]):
            raise LedgerCorrupt("takeover artifact digest is invalid")


class SchedulerSession:
    """A stateless facade over the persistent scheduler ledger."""

    def __init__(self, ledger_path: Path, session_label: str) -> None:
        self.ledger_path = Path(ledger_path)
        self.session_label = _validate_label(session_label, "scheduler session label")

    @classmethod
    def open(
        cls,
        ledger_path: Path,
        *,
        session_label: str,
        run_id: str | None = None,
    ) -> "SchedulerSession":
        path = Path(ledger_path)
        label = _validate_label(session_label, "scheduler session label")
        if path.exists():
            state = cls(path, label).read()
            if run_id is not None and run_id != state["run_id"]:
                raise SchedulerContractError("run_id differs from persistent ledger")
        else:
            if run_id is None:
                raise SchedulerContractError("a new ledger requires an explicit run_id")
            _validate_label(run_id, "run_id")
            _atomic_json(path, _new_state(run_id))
        return cls(path, label)

    def read(self) -> dict[str, Any]:
        try:
            state = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise LedgerCorrupt(f"cannot read scheduler ledger: {error}") from error
        if not isinstance(state, dict):
            raise LedgerCorrupt("scheduler ledger must be a JSON object")
        _validate_state(state)
        self._validate_artifacts(state)
        return copy.deepcopy(state)

    def _write(self, state: Mapping[str, Any]) -> None:
        _validate_state(state)
        _atomic_json(self.ledger_path, state)

    def _validate_artifacts(self, state: Mapping[str, Any]) -> None:
        for row in state["takeovers"]:
            path = self.ledger_path.parent / row["handoff_artifact"]
            if not path.is_file():
                raise LedgerCorrupt("takeover handoff artifact is missing")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != row["handoff_artifact_sha256"]:
                raise LedgerCorrupt("takeover handoff artifact digest differs from ledger")
        if state["termination_report_artifact"] is not None:
            report_path = self.ledger_path.parent / state["termination_report_artifact"]
            if not report_path.is_file():
                raise LedgerCorrupt("termination report artifact is missing")

    def start_attempt(
        self,
        *,
        task_id: str,
        task_digest: str,
        at: datetime | None = None,
    ) -> int:
        _validate_task(task_id, task_digest)
        state = self.read()
        if state["status"] in _TERMINAL_RUN_STATUSES:
            raise SchedulerContractError("terminal run cannot start another attempt")
        if state["task_id"] is not None:
            self._require_current_session(state)
        if state["task_id"] is None:
            state["task_id"] = task_id
            state["task_digest"] = task_digest
        elif state["task_id"] != task_id or state["task_digest"] != task_digest:
            raise ImmutableTaskChanged("immutable task identity or digest changed")
        if state["attempts"] and state["attempts"][-1]["status"] == "RUNNING":
            raise AttemptInProgress("finish the current immutable-task attempt first")
        if state["attempt_count"] >= MAX_ATTEMPTS:
            raise AttemptLimitExceeded("immutable task has reached the two-attempt cap")
        attempt_number = state["attempt_count"] + 1
        state["attempts"].append(
            {
                "attempt": attempt_number,
                "status": "RUNNING",
                "started_at": _timestamp(at),
                "finished_at": None,
                "scheduler_session": self.session_label,
            }
        )
        state["attempt_count"] = attempt_number
        state["current_scheduler_session"] = self.session_label
        state["status"] = "RUNNING"
        self._write(state)
        return attempt_number

    def finish_attempt(self, *, status: str, at: datetime | None = None) -> None:
        if status not in _ATTEMPT_TERMINAL_STATUSES:
            raise ValueError(f"invalid attempt status: {status}")
        state = self.read()
        self._require_current_session(state)
        if not state["attempts"] or state["attempts"][-1]["status"] != "RUNNING":
            raise SchedulerContractError("no running attempt to finish")
        state["attempts"][-1]["status"] = status
        state["attempts"][-1]["finished_at"] = _timestamp(at)
        state["status"] = "COMPLETE" if status == "PASS" else "READY_FOR_RETRY"
        self._write(state)

    def takeover(self, *, at: datetime | None = None) -> dict[str, Any]:
        """Replace the previous scheduler with this fresh session and persist proof."""

        state = self.read()
        if state["status"] in _TERMINAL_RUN_STATUSES:
            raise SchedulerContractError("terminal run cannot be taken over")
        previous = state["current_scheduler_session"]
        if previous is None:
            raise SchedulerContractError("cannot take over before an attempt is recorded")
        known_sessions = {
            previous,
            *(
                session
                for row in state["takeovers"]
                for session in (
                    row.get("from_scheduler_session"),
                    row.get("to_scheduler_session"),
                )
            ),
        }
        if self.session_label in known_sessions:
            raise DuplicateSessionTakeover("takeover requires a fresh scheduler session")
        takeover_number = state["takeover_count"] + 1
        relative_artifact = f"handoffs/handoff-{takeover_number:04d}.json"
        artifact = {
            "schema_version": "scheduler-handoff.v1",
            "event": "fresh_session_takeover",
            "handoff_id": f"handoff-{takeover_number:04d}",
            "from_scheduler_session": previous,
            "to_scheduler_session": self.session_label,
            "run_id": state["run_id"],
            "task_id": state["task_id"],
            "task_digest": state["task_digest"],
            "attempt_count": state["attempt_count"],
            "state": state["status"],
            "t0": state["t0"],
            "time_budget_seconds": TIME_BUDGET_SECONDS,
            "user_actions_after_t0": 0,
            "recorded_at": _timestamp(at),
        }
        artifact_path = self.ledger_path.parent / relative_artifact
        _atomic_json(artifact_path, artifact)
        artifact_digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        state["takeovers"].append(
            {
                "takeover": takeover_number,
                "from_scheduler_session": previous,
                "to_scheduler_session": self.session_label,
                "recorded_at": artifact["recorded_at"],
                "handoff_artifact": relative_artifact,
                "handoff_artifact_sha256": artifact_digest,
            }
        )
        state["takeover_count"] = takeover_number
        state["current_scheduler_session"] = self.session_label
        self._write(state)
        return copy.deepcopy(state["takeovers"][-1])

    def record_t0(
        self,
        *,
        input_ready: bool,
        code_freeze_ready: bool,
        runtime_ready: bool,
        at: datetime | None = None,
    ) -> str:
        state = self.read()
        if state["status"] in _TERMINAL_RUN_STATUSES:
            raise SchedulerContractError("terminal run cannot record T0")
        self._require_current_session(state)
        if state["t0"] is not None:
            raise T0AlreadyRecorded("T0 is immutable once recorded")
        if not all(value is True for value in (input_ready, code_freeze_ready, runtime_ready)):
            raise T0NotReady("T0 requires INPUT_READY, CODE_FREEZE_READY, and RUNTIME_READY")
        state["t0"] = _timestamp(at)
        state["t0_gates"] = {
            "INPUT_READY": "OK",
            "CODE_FREEZE_READY": "OK",
            "RUNTIME_READY": "OK",
        }
        state["user_actions_after_t0"] = 0
        self._write(state)
        return state["t0"]

    def record_user_action(self, action_label: str) -> None:
        """Reject post-T0 actions without mutating the zero-valued invariant."""

        if not isinstance(action_label, str) or not action_label.strip():
            raise ValueError("action_label must be a non-empty string")
        state = self.read()
        if state["t0"] is not None:
            raise PostT0UserActionRejected("USER_ACTIONS_AFTER_T0 must remain 0")

    def check_budget(self, *, at: datetime | None = None) -> TerminationReport | None:
        state = self.read()
        self._require_current_session(state)
        if state["t0"] is None:
            return None
        elapsed = self._elapsed_seconds(state, at)
        if elapsed < TIME_BUDGET_SECONDS:
            return None
        return self.terminate(
            reason_code="TIME_BUDGET_EXCEEDED",
            blockers=["12-hour unattended scheduler budget exhausted"],
            affected_objects=[state["task_id"] or "run"],
            completed_independent_work=["persistent scheduler ledger replay"],
            unique_recovery_action="start a fresh scheduler session from the ledger",
            at=at,
        )

    def terminate(
        self,
        *,
        reason_code: str,
        blockers: list[str],
        affected_objects: list[str],
        completed_independent_work: list[str],
        unique_recovery_action: str,
        at: datetime | None = None,
        elapsed_seconds: int | None = None,
    ) -> TerminationReport:
        if reason_code not in SPEC_FAILURE_CODES:
            raise InvalidReasonCode(f"unsupported Spec failure category: {reason_code}")
        if not isinstance(blockers, list) or not blockers or not all(isinstance(item, str) and item.strip() for item in blockers):
            raise ValueError("blockers must be a non-empty list of strings")
        if not isinstance(affected_objects, list) or not affected_objects or not all(isinstance(item, str) and item.strip() for item in affected_objects):
            raise ValueError("affected_objects must be a non-empty list of strings")
        if not isinstance(completed_independent_work, list) or not completed_independent_work or not all(isinstance(item, str) and item.strip() for item in completed_independent_work):
            raise ValueError("completed_independent_work must be a non-empty list of strings")
        if not isinstance(unique_recovery_action, str) or not unique_recovery_action.strip():
            raise ValueError("unique_recovery_action must be a non-empty string")
        state = self.read()
        existing_artifact = state["termination_report_artifact"]
        if existing_artifact:
            return self._read_report(self.ledger_path.parent / existing_artifact)
        if reason_code == "TIME_BUDGET_EXCEEDED" and state["t0"] is None:
            raise SchedulerContractError("time-budget termination requires recorded T0")
        self._require_current_session(state)
        terminated_at = _timestamp(at)
        # Keep the legacy keyword for callers, but never trust it for the
        # budget or report.  The persisted T0 and the termination timestamp
        # are the only authoritative elapsed-time inputs.
        elapsed = self._elapsed_seconds(state, at)
        if elapsed >= TIME_BUDGET_SECONDS:
            reason_code = "TIME_BUDGET_EXCEEDED"
        if reason_code == "TIME_BUDGET_EXCEEDED" and elapsed < TIME_BUDGET_SECONDS:
            raise SchedulerContractError("TIME_BUDGET_EXCEEDED requires the full fixed budget")
        fields: dict[str, Any] = {key: "" for key in TERMINATION_REPORT_FIELDS}
        fields.update(
            {
                "SPEC_ID": SPEC_ID,
                "RUN_ID": state["run_id"],
                "T0": state["t0"] or "",
                "TERMINATED_AT": terminated_at,
                "ELAPSED_SECONDS": elapsed,
                "TIME_BUDGET_SECONDS": TIME_BUDGET_SECONDS,
                "SCALED_CODE_READY": "NOT_READY",
                "SCALED_INPUT_READY": "NOT_READY",
                "SCALED_RUNTIME_READY": "NOT_READY",
                "SCALED_REVIEW_READY": "NOT_READY",
                "BLOCKERS": blockers,
                "REASON_CODE": reason_code,
                "AFFECTED_OBJECTS": affected_objects,
                "COMPLETED_INDEPENDENT_WORK": completed_independent_work,
                "UNIQUE_RECOVERY_ACTION": unique_recovery_action,
                "ORCHESTRATOR_TAKEOVERS": state["takeover_count"],
                "USER_ACTIONS_AFTER_T0": 0,
                "PUSHED": False,
                "DEPLOYED": False,
                "PLAN_CHECKBOX_CHANGED": False,
                "SENSITIVE_DATA_EXPOSED": False,
            }
        )
        relative_artifact = "termination-report.txt"
        report_path = self.ledger_path.parent / relative_artifact
        report = TerminationReport(fields=fields, path=report_path)
        _atomic_write(report_path, report.to_text())
        state["status"] = "TERMINATED"
        state["termination_report_artifact"] = relative_artifact
        state["terminated_at"] = terminated_at
        state["termination_reason_code"] = reason_code
        if state["attempts"] and state["attempts"][-1]["status"] == "RUNNING":
            state["attempts"][-1]["status"] = "TIMEOUT" if reason_code == "TIME_BUDGET_EXCEEDED" else "BLOCKED"
            state["attempts"][-1]["finished_at"] = terminated_at
        self._write(state)
        return report

    def _require_current_session(self, state: Mapping[str, Any]) -> None:
        if state["current_scheduler_session"] != self.session_label:
            raise SchedulerContractError(
                "fresh scheduler session must take over before mutating run state"
            )

    def _elapsed_seconds(self, state: Mapping[str, Any], at: datetime | None) -> int:
        if state["t0"] is None:
            return 0
        current = at or _utc_now()
        if current.tzinfo is None:
            raise ValueError("scheduler timestamps must be timezone-aware")
        return max(0, int((current.astimezone(timezone.utc) - _parse_timestamp(state["t0"])).total_seconds()))

    def _read_report(self, path: Path) -> TerminationReport:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as error:
            raise LedgerCorrupt(f"termination report artifact is missing: {error}") from error
        if len(lines) != len(TERMINATION_REPORT_FIELDS):
            raise LedgerCorrupt("termination report field count differs from Spec")
        fields: dict[str, Any] = {}
        for key, line in zip(TERMINATION_REPORT_FIELDS, lines):
            prefix = f"{key}="
            if not line.startswith(prefix):
                raise LedgerCorrupt(f"termination report field order differs from Spec: {key}")
            fields[key] = line[len(prefix):]
        for key in ("ELAPSED_SECONDS", "TIME_BUDGET_SECONDS", "ORCHESTRATOR_TAKEOVERS", "USER_ACTIONS_AFTER_T0"):
            fields[key] = int(fields[key])
        for key in ("PUSHED", "DEPLOYED", "PLAN_CHECKBOX_CHANGED", "SENSITIVE_DATA_EXPOSED"):
            fields[key] = fields[key] == "true"
        for key in ("BLOCKERS", "AFFECTED_OBJECTS", "COMPLETED_INDEPENDENT_WORK", "BENCHMARK_HARD_FAILS", "MVP_BACKLOG"):
            fields[key] = [] if fields[key] == "" else fields[key].split("; ")
        if fields["TIME_BUDGET_SECONDS"] != TIME_BUDGET_SECONDS:
            raise LedgerCorrupt("termination report budget differs from the fixed Spec budget")
        if fields["REASON_CODE"] not in SPEC_FAILURE_CODES:
            raise LedgerCorrupt("termination report has an unsupported Spec reason code")
        if fields["USER_ACTIONS_AFTER_T0"] != 0:
            raise LedgerCorrupt("termination report USER_ACTIONS_AFTER_T0 is not zero")
        return TerminationReport(fields=fields, path=path)
