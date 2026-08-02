"""Persistent, replaceable scheduler state for the next-phase run contract.

This module is deliberately a local state contract.  It does not launch Codex,
call a Dashboard/API, interpret scientific evidence, or retain a transport
session reference.  A fresh scheduler process can open the JSON ledger and
continue from the recorded state using only a bounded scheduler-session label.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping


SPEC_ID = "review-writer-next-phase-2026-08-01"
MAX_ATTEMPTS = 2
TIME_BUDGET_SECONDS = 43200
UNKNOWN = "UNKNOWN"

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
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_CODE_HEAD = re.compile(r"^[0-9a-f]{40,64}$")
_DIGEST_REF = re.compile(r"^sha256:[0-9a-f]{64}$")
_ARTIFACT_STATUS_WORDS = frozenset(
    {
        "ok",
        "blocked",
        "not_ready",
        "ready",
        "pass",
        "passed",
        "fail",
        "failed",
        "partial",
        "timeout",
        "environment_undetermined",
        "true",
        "false",
    }
)
_SESSION_REFERENCE = re.compile(
    r"(?i)^(?:captured-by-[a-z0-9-]+|opaque[-_]?(?:session|thread|turn)(?:[-_.][a-z0-9._-]+)*|(?:session|thread|turn)[-_][a-z0-9._-]+)$"
)
_PRIVATE_PATH = re.compile(r"(?:^|[\s=(])(?:/|[A-Za-z]:[\\/])")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?:api[_ -]?key|access[_ -]?token|secret|password|cookie|authorization)\s*="
)
_AUTHORITY_KEYS = frozenset(
    {
        "SPEC_ID",
        "FROZEN_CODE_HEAD",
        "AUTHORITATIVE_PROJECT_ID",
        "CORPUS_STUDY_COUNT",
        "CORE_STUDY_COUNT",
        "CORE_STUDY_IDS",
    }
)
_GATE_FIELDS = (
    "SCALED_CODE_READY",
    "SCALED_INPUT_READY",
    "SCALED_RUNTIME_READY",
    "SCALED_REVIEW_READY",
    "MAIN_PDF_READY",
    "SI_PDF_READY",
    "GENERIC_MAIN_READY",
    "GENERIC_SI_READY",
    "CHEMICAL_MAIN_READY",
    "CHEMICAL_CORE_SI_READY",
)
_COUNT_FIELDS = (
    "CONFIRMED_COUNT",
    "AI_PROVISIONAL_COUNT",
    "BLOCKED_COUNT",
    "CORPUS_STUDY_COUNT",
    "CORE_STUDY_COUNT",
    "BENCHMARK_ROUNDS",
)
_BOOL_STATE_FIELDS = (
    "SOURCE_TRUTH_CURRENT",
    "DOCX_READY",
    "PDF_READY",
)
_ARTIFACT_FIELDS = (
    "PER_STUDY_COVERAGE_ARTIFACT",
    "GAP_REGISTRY_ARTIFACT",
    "PAPER_EVIDENCE_CURRENT",
    "SYNTHESIS_CURRENT",
    "MANUSCRIPT_CURRENT",
    "CLAIM_SOURCE_AUDIT",
    "ARTIFACT_MANIFEST",
)
_SEMANTIC_REPORT_FIELDS = frozenset(
    set(TERMINATION_REPORT_FIELDS)
    - {
        "SPEC_ID",
        "RUN_ID",
        "T0",
        "TERMINATED_AT",
        "ELAPSED_SECONDS",
        "TIME_BUDGET_SECONDS",
        "ORCHESTRATOR_TAKEOVERS",
        "USER_ACTIONS_AFTER_T0",
        "PUSHED",
        "DEPLOYED",
        "PLAN_CHECKBOX_CHANGED",
        "SENSITIVE_DATA_EXPOSED",
    }
)
_MISSING = object()


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
    lineage: dict[str, str] = field(default_factory=dict)

    @staticmethod
    def render_value(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (list, tuple)):
            return "; ".join(str(item) for item in value) if value else "NONE"
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


def _key_variants(key: str) -> tuple[str, ...]:
    snake = key.lower()
    return (key, snake, snake.replace("_", "-"))


def _is_unknown_marker(value: Any) -> bool:
    return value is None or (
        isinstance(value, str)
        and value.strip().upper() in {"", "UNKNOWN", "NOT_AVAILABLE", "PRE_T0_PENDING_INPUT", "PRE_CODE_FREEZE"}
    )


def _private_value(value: str) -> bool:
    return bool(_PRIVATE_PATH.search(value) or "\n" in value or "\r" in value or _SECRET_ASSIGNMENT.search(value))


def _add_issue(issues: list[str], issue: str) -> None:
    if issue not in issues:
        issues.append(issue)


def _safe_text(value: Any, *, issues: list[str], issue: str) -> str:
    if _is_unknown_marker(value):
        return UNKNOWN
    if not isinstance(value, str):
        _add_issue(issues, issue)
        return UNKNOWN
    candidate = value.strip()
    if not candidate or _private_value(candidate) or len(candidate) > 512:
        _add_issue(issues, issue)
        return UNKNOWN
    return candidate


def _safe_identifier(value: Any, *, issues: list[str]) -> str:
    if _is_unknown_marker(value):
        return UNKNOWN
    if not isinstance(value, str) or not _SAFE_IDENTIFIER.fullmatch(value.strip()):
        _add_issue(issues, "AUTHORITY_UNKNOWN")
        return UNKNOWN
    return value.strip()


def _safe_code_head(value: Any, *, issues: list[str]) -> str:
    if _is_unknown_marker(value):
        _add_issue(issues, "AUTHORITY_UNKNOWN")
        return UNKNOWN
    if not isinstance(value, str) or not _CODE_HEAD.fullmatch(value.strip().lower()):
        _add_issue(issues, "AUTHORITY_UNKNOWN")
        return UNKNOWN
    return value.strip().lower()


def _safe_count(value: Any, *, issues: list[str], issue: str) -> int | str:
    if _is_unknown_marker(value):
        return UNKNOWN
    if isinstance(value, bool):
        _add_issue(issues, issue)
        return UNKNOWN
    try:
        candidate = int(value)
    except (TypeError, ValueError):
        _add_issue(issues, issue)
        return UNKNOWN
    if candidate < 0:
        _add_issue(issues, issue)
        return UNKNOWN
    return candidate


def _safe_score(value: Any, *, issues: list[str]) -> int | float | str:
    if _is_unknown_marker(value):
        return UNKNOWN
    if isinstance(value, bool):
        _add_issue(issues, "RUN_STATE_VALUE_INVALID")
        return UNKNOWN
    try:
        candidate = float(value)
    except (TypeError, ValueError):
        _add_issue(issues, "RUN_STATE_VALUE_INVALID")
        return UNKNOWN
    if not math.isfinite(candidate) or candidate < 0:
        _add_issue(issues, "RUN_STATE_VALUE_INVALID")
        return UNKNOWN
    return int(candidate) if candidate.is_integer() else candidate


def _safe_artifact_ref(value: Any, *, issues: list[str]) -> str:
    if _is_unknown_marker(value):
        return UNKNOWN
    if isinstance(value, Mapping):
        for key in ("artifact_ref", "relative_path", "path", "artifact_id"):
            if key in value:
                return _safe_artifact_ref(value[key], issues=issues)
        digest = value.get("sha256")
        if isinstance(digest, str) and _SHA256.fullmatch(digest.lower()):
            return f"sha256:{digest.lower()}"
        _add_issue(issues, "ARTIFACT_REFERENCE_INVALID")
        return UNKNOWN
    if isinstance(value, bool):
        _add_issue(issues, "ARTIFACT_REFERENCE_INVALID")
        return UNKNOWN
    if not isinstance(value, str):
        _add_issue(issues, "ARTIFACT_REFERENCE_INVALID")
        return UNKNOWN
    candidate = value.strip()
    normalized = candidate.replace(" ", "_").casefold()
    if normalized in _ARTIFACT_STATUS_WORDS or _SESSION_REFERENCE.fullmatch(candidate):
        _add_issue(issues, "ARTIFACT_REFERENCE_INVALID")
        return UNKNOWN
    if _DIGEST_REF.fullmatch(candidate.lower()):
        return candidate.lower()
    parts = candidate.split("/")
    if (
        not candidate
        or candidate.startswith("/")
        or "\\" in candidate
        or _private_value(candidate)
        or not _ARTIFACT_REF.fullmatch(candidate)
        or any(part in {"", ".", ".."} for part in parts)
        or ("/" not in candidate and not _SAFE_IDENTIFIER.fullmatch(candidate))
    ):
        _add_issue(issues, "ARTIFACT_REFERENCE_INVALID")
        return UNKNOWN
    return candidate


def _safe_list(value: Any, *, issues: list[str], issue: str, refs: bool = False) -> list[str] | str:
    if _is_unknown_marker(value):
        return UNKNOWN
    if isinstance(value, str):
        values = [item.strip() for item in value.split(",") if item.strip()]
    elif isinstance(value, (list, tuple)):
        values = list(value)
    else:
        _add_issue(issues, issue)
        return UNKNOWN
    if not values:
        return []
    result: list[str] = []
    for item in values:
        safe = (
            _safe_artifact_ref(item, issues=issues)
            if refs
            else _safe_text(item, issues=issues, issue=issue)
        )
        if safe != UNKNOWN:
            result.append(safe)
    return result or UNKNOWN


def _coerce_gate(value: Any, *, issues: list[str]) -> str:
    if _is_unknown_marker(value):
        return UNKNOWN
    if value is True or (isinstance(value, str) and value.strip().upper() in {"OK", "READY", "PASS", "PASSED", "TRUE"}):
        return "OK"
    if value is False or (isinstance(value, str) and value.strip().upper() in {"NOT_READY", "NOT READY", "FALSE"}):
        return "NOT_READY"
    if isinstance(value, str) and value.strip().upper() in {"BLOCKED", "FAILED", "FAIL", "PARTIAL"}:
        return value.strip().upper()
    _add_issue(issues, "RUN_STATE_VALUE_INVALID")
    return UNKNOWN


def _coerce_bool_state(value: Any, *, issues: list[str]) -> str:
    if _is_unknown_marker(value):
        return UNKNOWN
    if value is True or (isinstance(value, str) and value.strip().lower() in {"true", "ok", "ready", "pass", "passed"}):
        return "true"
    if value is False or (isinstance(value, str) and value.strip().lower() in {"false", "not_ready", "not ready", "blocked", "fail", "failed"}):
        return "false"
    _add_issue(issues, "RUN_STATE_VALUE_INVALID")
    return UNKNOWN


def _coerce_status_or_text(value: Any, *, issues: list[str]) -> str:
    if _is_unknown_marker(value):
        return UNKNOWN
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        candidate = value.strip()
        if candidate.upper() in {"PASS", "PASSED", "OK", "READY"}:
            return "OK"
        if candidate.upper() in {"FAIL", "FAILED"}:
            return "FAILED"
    return _safe_text(value, issues=issues, issue="RUN_STATE_VALUE_INVALID")


def _load_authority(path: Path | None) -> tuple[dict[str, Any], list[str]]:
    if path is None:
        return {}, ["AUTHORITY_UNKNOWN"]
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}, ["AUTHORITY_UNKNOWN"]
    parsed: Any = _MISSING
    if raw.lstrip().startswith("{"):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = _MISSING
    values: dict[str, Any] = {}
    if isinstance(parsed, Mapping):
        for key, value in parsed.items():
            normalized = str(key).upper().replace("-", "_")
            if normalized in _AUTHORITY_KEYS:
                values[normalized] = value
    else:
        for line in raw.splitlines():
            match = re.match(r"^\s*([A-Za-z][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$", line)
            if match and match.group(1).upper() in _AUTHORITY_KEYS:
                values[match.group(1).upper()] = match.group(2)
    if values.get("SPEC_ID") not in {None, SPEC_ID}:
        return {}, ["AUTHORITY_UNKNOWN"]
    if not values:
        return {}, ["AUTHORITY_UNKNOWN"]
    return values, []


def _load_run_state(path: Path | None) -> tuple[dict[str, Any], list[str]]:
    if path is None:
        return {}, ["RUN_STATE_UNKNOWN"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, ["RUN_STATE_UNKNOWN"]
    if not isinstance(payload, dict):
        return {}, ["RUN_STATE_UNKNOWN"]
    return payload, []


def _lookup_authority(authority: Mapping[str, Any], key: str) -> tuple[Any, str | None]:
    for variant in _key_variants(key):
        if variant in authority:
            return authority[variant], f"authority:{key}"
    return _MISSING, None


def _lookup_run_state(run_state: Mapping[str, Any], key: str) -> tuple[Any, str | None]:
    for variant in _key_variants(key):
        if variant in run_state:
            return run_state[variant], f"run_state:{key}"
    if key in _GATE_FIELDS:
        containers = ("gates", "gate_state", "readiness")
    elif key in _COUNT_FIELDS or key == "BENCHMARK_SCORE":
        containers = ("counts", "status_counts", "molecule_counts", "quality")
    elif key in _ARTIFACT_FIELDS or key == "OWNER_REPORTS":
        containers = ("artifacts", "artifact_refs", "release")
    else:
        containers = ("report", "summary", "quality", "checks", "verification")
    for container_name in containers:
        container = run_state.get(container_name)
        if not isinstance(container, Mapping):
            continue
        for variant in _key_variants(key):
            if variant in container:
                return container[variant], f"run_state:{container_name}.{key}"
    return _MISSING, None


def _merge_unique(*values: list[str] | str | None) -> list[str] | str:
    result: list[str] = []
    for value in values:
        if isinstance(value, str):
            if value != UNKNOWN and value not in result:
                result.append(value)
        elif isinstance(value, (list, tuple)):
            for item in value:
                if item != UNKNOWN and item not in result:
                    result.append(item)
    return result or UNKNOWN


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
        "termination_report_sha256": None,
        "termination_report_lineage": None,
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
    if state.get("termination_report_sha256") is not None and (
        not isinstance(state["termination_report_sha256"], str)
        or not _SHA256.fullmatch(state["termination_report_sha256"])
    ):
        raise LedgerCorrupt("termination report digest is invalid")
    lineage = state.get("termination_report_lineage")
    if lineage is not None:
        if not isinstance(lineage, dict):
            raise LedgerCorrupt("termination report lineage must be an object")
        for key, value in lineage.items():
            if key not in TERMINATION_REPORT_FIELDS or not isinstance(value, str) or not _SAFE_IDENTIFIER.fullmatch(value.replace(":", "-").replace(".", "-")):
                raise LedgerCorrupt("termination report lineage contains an unsafe value")
    for row in state["takeovers"]:
        if not isinstance(row, dict):
            raise LedgerCorrupt("takeover records must be objects")
        _validate_artifact_ref(row.get("handoff_artifact"), "handoff")
        if not isinstance(row.get("handoff_artifact_sha256"), str) or not _SHA256.fullmatch(row["handoff_artifact_sha256"]):
            raise LedgerCorrupt("takeover artifact digest is invalid")


class SchedulerSession:
    """A stateless facade over the persistent scheduler ledger."""

    def __init__(
        self,
        ledger_path: Path,
        session_label: str,
        *,
        authority_path: Path | None = None,
        run_state_path: Path | None = None,
    ) -> None:
        self.ledger_path = Path(ledger_path)
        self.session_label = _validate_label(session_label, "scheduler session label")
        self.authority_path = Path(authority_path) if authority_path is not None else None
        self.run_state_path = Path(run_state_path) if run_state_path is not None else None

    @classmethod
    def open(
        cls,
        ledger_path: Path,
        *,
        session_label: str,
        run_id: str | None = None,
        authority_path: Path | None = None,
        run_state_path: Path | None = None,
    ) -> "SchedulerSession":
        path = Path(ledger_path)
        label = _validate_label(session_label, "scheduler session label")
        if path.exists():
            state = cls(
                path,
                label,
                authority_path=authority_path,
                run_state_path=run_state_path,
            ).read()
            if run_id is not None and run_id != state["run_id"]:
                raise SchedulerContractError("run_id differs from persistent ledger")
        else:
            if run_id is None:
                raise SchedulerContractError("a new ledger requires an explicit run_id")
            _validate_label(run_id, "run_id")
            _atomic_json(path, _new_state(run_id))
        return cls(
            path,
            label,
            authority_path=authority_path,
            run_state_path=run_state_path,
        )

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
            report_digest = state.get("termination_report_sha256")
            if report_digest is not None:
                if hashlib.sha256(report_path.read_bytes()).hexdigest() != report_digest:
                    raise LedgerCorrupt("termination report artifact digest differs from ledger")

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

    def _build_semantic_report(
        self,
        state: Mapping[str, Any],
        *,
        blockers: list[str] | None,
        affected_objects: list[str] | None,
        completed_independent_work: list[str] | None,
        unique_recovery_action: str | None,
        reason_code: str,
        authority: Mapping[str, Any] | None,
        authority_path: Path | None,
        run_state: Mapping[str, Any] | None,
        run_state_path: Path | None,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        issues: list[str] = []
        if authority is None:
            authority, source_issues = _load_authority(authority_path or self.authority_path)
            for issue in source_issues:
                _add_issue(issues, issue)
        else:
            authority = {
                str(key).upper().replace("-", "_"): value
                for key, value in authority.items()
                if str(key).upper().replace("-", "_") in _AUTHORITY_KEYS
            }
            if not authority:
                _add_issue(issues, "AUTHORITY_UNKNOWN")
            if authority.get("SPEC_ID") not in {None, SPEC_ID}:
                authority = {}
                _add_issue(issues, "AUTHORITY_UNKNOWN")
        if run_state is None:
            run_state, source_issues = _load_run_state(run_state_path or self.run_state_path)
            for issue in source_issues:
                _add_issue(issues, issue)
        elif not isinstance(run_state, Mapping):
            run_state = {}
            _add_issue(issues, "RUN_STATE_UNKNOWN")

        fields: dict[str, Any] = {key: UNKNOWN for key in TERMINATION_REPORT_FIELDS}
        lineage: dict[str, str] = {
            key: "unknown-semantic-source" for key in TERMINATION_REPORT_FIELDS
        }
        fields.update(
            {
                "SPEC_ID": SPEC_ID,
                "RUN_ID": state["run_id"],
                "T0": state["t0"] or UNKNOWN,
                "TERMINATED_AT": _timestamp(None),
                "ELAPSED_SECONDS": 0,
                "TIME_BUDGET_SECONDS": TIME_BUDGET_SECONDS,
                "ORCHESTRATOR_TAKEOVERS": state["takeover_count"],
                "USER_ACTIONS_AFTER_T0": 0,
                "PUSHED": False,
                "DEPLOYED": False,
                "PLAN_CHECKBOX_CHANGED": False,
                "SENSITIVE_DATA_EXPOSED": False,
            }
        )
        lineage.update(
            {
                "SPEC_ID": "ledger:spec_id",
                "RUN_ID": "ledger:run_id",
                "T0": "ledger:t0",
                "TIME_BUDGET_SECONDS": "contract:fixed-budget",
                "ORCHESTRATOR_TAKEOVERS": "ledger:takeover_count",
                "USER_ACTIONS_AFTER_T0": "ledger:user_actions_after_t0",
                "PUSHED": "contract:local-only",
                "DEPLOYED": "contract:local-only",
                "PLAN_CHECKBOX_CHANGED": "contract:local-only",
                "SENSITIVE_DATA_EXPOSED": "contract:safety-invariant",
            }
        )

        raw, location = _lookup_authority(authority, "FROZEN_CODE_HEAD")
        fields["FROZEN_CODE_HEAD"] = _safe_code_head(raw, issues=issues) if raw is not _MISSING else UNKNOWN
        lineage["FROZEN_CODE_HEAD"] = location or "unknown:authority"
        raw, location = _lookup_authority(authority, "AUTHORITATIVE_PROJECT_ID")
        fields["AUTHORITATIVE_PROJECT_ID"] = _safe_identifier(raw, issues=issues) if raw is not _MISSING else UNKNOWN
        lineage["AUTHORITATIVE_PROJECT_ID"] = location or "unknown:authority"
        raw, location = _lookup_authority(authority, "CORPUS_STUDY_COUNT")
        fields["CORPUS_STUDY_COUNT"] = _safe_count(raw, issues=issues, issue="AUTHORITY_UNKNOWN") if raw is not _MISSING else UNKNOWN
        lineage["CORPUS_STUDY_COUNT"] = location or "unknown:authority"
        raw, location = _lookup_authority(authority, "CORE_STUDY_COUNT")
        if raw is not _MISSING:
            fields["CORE_STUDY_COUNT"] = _safe_count(raw, issues=issues, issue="AUTHORITY_UNKNOWN")
            lineage["CORE_STUDY_COUNT"] = location or "unknown:authority"
        else:
            raw, location = _lookup_authority(authority, "CORE_STUDY_IDS")
            if raw is not _MISSING and not _is_unknown_marker(raw):
                ids = _safe_list(raw, issues=issues, issue="AUTHORITY_UNKNOWN")
                if isinstance(ids, list):
                    fields["CORE_STUDY_COUNT"] = len(ids)
                    lineage["CORE_STUDY_COUNT"] = location or "unknown:authority"
                else:
                    lineage["CORE_STUDY_COUNT"] = "unknown:authority"
            else:
                lineage["CORE_STUDY_COUNT"] = "unknown:authority"
        if any(
            fields[key] == UNKNOWN
            for key in ("FROZEN_CODE_HEAD", "AUTHORITATIVE_PROJECT_ID", "CORPUS_STUDY_COUNT", "CORE_STUDY_COUNT")
        ):
            _add_issue(issues, "AUTHORITY_UNKNOWN")

        for key in _GATE_FIELDS:
            raw, location = _lookup_run_state(run_state, key)
            fields[key] = _coerce_gate(raw, issues=issues) if raw is not _MISSING else UNKNOWN
            lineage[key] = location or "unknown:run-state"
        for key in _COUNT_FIELDS[:3]:
            raw, location = _lookup_run_state(run_state, key)
            fields[key] = _safe_count(raw, issues=issues, issue="RUN_STATE_VALUE_INVALID") if raw is not _MISSING else UNKNOWN
            lineage[key] = location or "unknown:run-state"
        for key in _BOOL_STATE_FIELDS:
            raw, location = _lookup_run_state(run_state, key)
            fields[key] = _coerce_bool_state(raw, issues=issues) if raw is not _MISSING else UNKNOWN
            lineage[key] = location or "unknown:run-state"
        for key in _ARTIFACT_FIELDS:
            raw, location = _lookup_run_state(run_state, key)
            fields[key] = _safe_artifact_ref(raw, issues=issues) if raw is not _MISSING else UNKNOWN
            lineage[key] = location or "unknown:run-state"
        raw, location = _lookup_run_state(run_state, "PAPER_EVIDENCE_DISPOSITIONED")
        fields["PAPER_EVIDENCE_DISPOSITIONED"] = _coerce_gate(raw, issues=issues) if raw is not _MISSING else UNKNOWN
        lineage["PAPER_EVIDENCE_DISPOSITIONED"] = location or "unknown:run-state"
        raw, location = _lookup_run_state(run_state, "BENCHMARK_SCORE")
        fields["BENCHMARK_SCORE"] = _safe_score(raw, issues=issues) if raw is not _MISSING else UNKNOWN
        lineage["BENCHMARK_SCORE"] = location or "unknown:run-state"
        raw, location = _lookup_run_state(run_state, "BENCHMARK_ROUNDS")
        fields["BENCHMARK_ROUNDS"] = _safe_count(raw, issues=issues, issue="RUN_STATE_VALUE_INVALID") if raw is not _MISSING else UNKNOWN
        lineage["BENCHMARK_ROUNDS"] = location or "unknown:run-state"
        for key in ("BENCHMARK_HARD_FAILS", "MVP_BACKLOG"):
            raw, location = _lookup_run_state(run_state, key)
            fields[key] = _safe_list(raw, issues=issues, issue="RUN_STATE_VALUE_INVALID") if raw is not _MISSING else UNKNOWN
            lineage[key] = location or "unknown:run-state"
        raw, location = _lookup_run_state(run_state, "OWNER_REPORTS")
        fields["OWNER_REPORTS"] = _safe_list(raw, issues=issues, issue="ARTIFACT_REFERENCE_INVALID", refs=True) if raw is not _MISSING else UNKNOWN
        lineage["OWNER_REPORTS"] = location or "unknown:run-state"
        for key in ("FOCUSED_TESTS", "SMOKE", "QUALITY_CHECK", "GIT_SHOW_CHECK"):
            raw, location = _lookup_run_state(run_state, key)
            fields[key] = _coerce_status_or_text(raw, issues=issues) if raw is not _MISSING else UNKNOWN
            lineage[key] = location or "unknown:run-state"
        raw, location = _lookup_run_state(run_state, "GIT_STATUS")
        fields["GIT_STATUS"] = _safe_text(raw, issues=issues, issue="RUN_STATE_VALUE_INVALID") if raw is not _MISSING else UNKNOWN
        lineage["GIT_STATUS"] = location or "unknown:run-state"

        request_blockers = _safe_list(
            blockers,
            issues=issues,
            issue="TERMINATION_SEMANTIC_INVALID",
        )
        raw, location = _lookup_run_state(run_state, "BLOCKERS")
        state_blockers = (
            _safe_list(raw, issues=issues, issue="RUN_STATE_VALUE_INVALID")
            if raw is not _MISSING
            else UNKNOWN
        )
        fields["BLOCKERS"] = _merge_unique(request_blockers, state_blockers, issues)
        lineage["BLOCKERS"] = "termination-request-run-state-ledger"

        request_affected = _safe_list(
            affected_objects,
            issues=issues,
            issue="TERMINATION_SEMANTIC_INVALID",
        )
        raw, location = _lookup_run_state(run_state, "AFFECTED_OBJECTS")
        state_affected = (
            _safe_list(raw, issues=issues, issue="RUN_STATE_VALUE_INVALID")
            if raw is not _MISSING
            else UNKNOWN
        )
        affected = _merge_unique(request_affected, state_affected)
        if affected == UNKNOWN:
            affected = [state["task_id"] or UNKNOWN]
            if affected == [UNKNOWN]:
                _add_issue(issues, "RUN_STATE_UNKNOWN")
        fields["AFFECTED_OBJECTS"] = affected
        lineage["AFFECTED_OBJECTS"] = "termination-request-run-state-ledger"

        request_completed = _safe_list(
            completed_independent_work,
            issues=issues,
            issue="TERMINATION_SEMANTIC_INVALID",
        )
        raw, location = _lookup_run_state(run_state, "COMPLETED_INDEPENDENT_WORK")
        state_completed = (
            _safe_list(raw, issues=issues, issue="RUN_STATE_VALUE_INVALID")
            if raw is not _MISSING
            else UNKNOWN
        )
        fields["COMPLETED_INDEPENDENT_WORK"] = _merge_unique(request_completed, state_completed)
        lineage["COMPLETED_INDEPENDENT_WORK"] = "termination-request-run-state-ledger"

        request_recovery = _safe_text(
            unique_recovery_action,
            issues=issues,
            issue="TERMINATION_SEMANTIC_INVALID",
        )
        raw, location = _lookup_run_state(run_state, "UNIQUE_RECOVERY_ACTION")
        state_recovery = (
            _safe_text(raw, issues=issues, issue="RUN_STATE_VALUE_INVALID")
            if raw is not _MISSING
            else UNKNOWN
        )
        recovery = request_recovery if request_recovery != UNKNOWN else state_recovery
        if recovery == UNKNOWN:
            recovery = (
                "start a fresh scheduler session from the persistent ledger"
                if reason_code == "TIME_BUDGET_EXCEEDED"
                else "resolve the recorded blocker and start a fresh scheduler session from the persistent ledger"
            )
            lineage["UNIQUE_RECOVERY_ACTION"] = "contract:stable-recovery-action"
        else:
            lineage["UNIQUE_RECOVERY_ACTION"] = "termination-request" if request_recovery != UNKNOWN else "run_state:UNIQUE_RECOVERY_ACTION"
        fields["UNIQUE_RECOVERY_ACTION"] = recovery

        if issues:
            fields["BLOCKERS"] = _merge_unique(fields["BLOCKERS"], issues)
        return fields, lineage

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
        blockers: list[str] | None = None,
        affected_objects: list[str] | None = None,
        completed_independent_work: list[str] | None = None,
        unique_recovery_action: str | None = None,
        at: datetime | None = None,
        elapsed_seconds: int | None = None,
        authority: Mapping[str, Any] | None = None,
        run_state: Mapping[str, Any] | None = None,
        authority_path: Path | None = None,
        run_state_path: Path | None = None,
    ) -> TerminationReport:
        if reason_code not in SPEC_FAILURE_CODES:
            raise InvalidReasonCode(f"unsupported Spec failure category: {reason_code}")
        if blockers is not None and (not isinstance(blockers, list) or not all(isinstance(item, str) and item.strip() for item in blockers)):
            raise ValueError("blockers must be a non-empty list of strings")
        if affected_objects is not None and (not isinstance(affected_objects, list) or not all(isinstance(item, str) and item.strip() for item in affected_objects)):
            raise ValueError("affected_objects must be a non-empty list of strings")
        if completed_independent_work is not None and (not isinstance(completed_independent_work, list) or not all(isinstance(item, str) and item.strip() for item in completed_independent_work)):
            raise ValueError("completed_independent_work must be a non-empty list of strings")
        if unique_recovery_action is not None and (not isinstance(unique_recovery_action, str) or not unique_recovery_action.strip()):
            raise ValueError("unique_recovery_action must be a non-empty string")
        state = self.read()
        existing_artifact = state["termination_report_artifact"]
        if existing_artifact:
            return self._read_report(
                self.ledger_path.parent / existing_artifact,
                lineage=state.get("termination_report_lineage"),
            )
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
        fields, lineage = self._build_semantic_report(
            state,
            blockers=blockers,
            affected_objects=affected_objects,
            completed_independent_work=completed_independent_work,
            unique_recovery_action=unique_recovery_action,
            reason_code=reason_code,
            authority=authority,
            authority_path=authority_path,
            run_state=run_state,
            run_state_path=run_state_path,
        )
        fields["REASON_CODE"] = reason_code
        fields["TERMINATED_AT"] = terminated_at
        fields["ELAPSED_SECONDS"] = elapsed
        lineage["REASON_CODE"] = "ledger:termination_reason_code"
        lineage["TERMINATED_AT"] = "ledger:terminated_at"
        lineage["ELAPSED_SECONDS"] = "ledger:t0-and-terminated_at"
        relative_artifact = "termination-report.txt"
        report_path = self.ledger_path.parent / relative_artifact
        report = TerminationReport(fields=fields, path=report_path, lineage=lineage)
        _atomic_write(report_path, report.to_text())
        state["status"] = "TERMINATED"
        state["termination_report_artifact"] = relative_artifact
        state["termination_report_sha256"] = hashlib.sha256(report_path.read_bytes()).hexdigest()
        state["termination_report_lineage"] = lineage
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

    def _read_report(
        self,
        path: Path,
        *,
        lineage: Mapping[str, str] | None = None,
    ) -> TerminationReport:
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
        if any(fields[key] == "" for key in _SEMANTIC_REPORT_FIELDS):
            raise LedgerCorrupt("termination report has an unpopulated semantic field")
        for key in (*_COUNT_FIELDS, "ELAPSED_SECONDS", "TIME_BUDGET_SECONDS", "ORCHESTRATOR_TAKEOVERS", "USER_ACTIONS_AFTER_T0"):
            if fields[key] != UNKNOWN:
                try:
                    fields[key] = int(fields[key])
                except ValueError as error:
                    raise LedgerCorrupt(f"termination report {key} is not an integer") from error
        if fields["BENCHMARK_SCORE"] != UNKNOWN:
            try:
                score = float(fields["BENCHMARK_SCORE"])
            except ValueError as error:
                raise LedgerCorrupt("termination report benchmark score is invalid") from error
            fields["BENCHMARK_SCORE"] = int(score) if score.is_integer() else score
        for key in ("PUSHED", "DEPLOYED", "PLAN_CHECKBOX_CHANGED", "SENSITIVE_DATA_EXPOSED"):
            if fields[key] not in {"true", "false"}:
                raise LedgerCorrupt(f"termination report {key} is not boolean")
            fields[key] = fields[key] == "true"
        for key in (
            "BLOCKERS",
            "AFFECTED_OBJECTS",
            "COMPLETED_INDEPENDENT_WORK",
            "BENCHMARK_HARD_FAILS",
            "MVP_BACKLOG",
            "OWNER_REPORTS",
        ):
            if fields[key] != UNKNOWN:
                fields[key] = [] if fields[key] == "NONE" else fields[key].split("; ")
        if fields["TIME_BUDGET_SECONDS"] != TIME_BUDGET_SECONDS:
            raise LedgerCorrupt("termination report budget differs from the fixed Spec budget")
        if fields["REASON_CODE"] not in SPEC_FAILURE_CODES:
            raise LedgerCorrupt("termination report has an unsupported Spec reason code")
        if fields["USER_ACTIONS_AFTER_T0"] != 0:
            raise LedgerCorrupt("termination report USER_ACTIONS_AFTER_T0 is not zero")
        if fields["FROZEN_CODE_HEAD"] != UNKNOWN and not _CODE_HEAD.fullmatch(fields["FROZEN_CODE_HEAD"]):
            raise LedgerCorrupt("termination report frozen code head is invalid")
        if fields["AUTHORITATIVE_PROJECT_ID"] != UNKNOWN and not _SAFE_IDENTIFIER.fullmatch(fields["AUTHORITATIVE_PROJECT_ID"]):
            raise LedgerCorrupt("termination report project identifier is invalid")
        for key in _ARTIFACT_FIELDS:
            value = fields[key]
            if value != UNKNOWN:
                issues: list[str] = []
                safe = _safe_artifact_ref(value, issues=issues)
                if safe != value or issues:
                    raise LedgerCorrupt(f"termination report {key} is not a safe stable reference")
        for value in fields.values():
            rendered = TerminationReport.render_value(value)
            if _private_value(rendered):
                raise LedgerCorrupt("termination report contains a private path or secret assignment")
        safe_lineage = dict(lineage or {})
        return TerminationReport(fields=fields, path=path, lineage=safe_lineage)
