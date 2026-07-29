"""Append-only, account-free credit measurements for one local review project."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

if os.name == "nt":
    import msvcrt
else:
    import fcntl


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schemas/operations/credit_event.v1.schema.json"
CREDIT_LEDGER_PATH = Path("06_evaluation/credit_ledger.jsonl")
_LOCK_PATH = Path("06_evaluation/.credit_ledger.lock")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CreditLedgerError(ValueError):
    """A stable, fail-closed credit ledger error."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _event_id(payload: dict[str, Any]) -> str:
    material = {key: value for key, value in payload.items() if key != "event_id"}
    return hashlib.sha256(_canonical_bytes(material)).hexdigest()


def _validator() -> Draft202012Validator:
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CreditLedgerError("CREDIT_SCHEMA_INVALID") from exc
    return Draft202012Validator(schema)


def _validate_event(event: dict[str, Any]) -> None:
    errors = sorted(_validator().iter_errors(event), key=lambda error: list(error.path))
    if errors or event["consumed"] != event["before"] - event["after"]:
        raise CreditLedgerError("CREDIT_EVENT_INVALID")
    if event["event_id"] != _event_id(event):
        raise CreditLedgerError("CREDIT_EVENT_DIGEST_INVALID")


def _safe_project(project: Path) -> Path:
    supplied = Path(project)
    if supplied.is_symlink() or not supplied.is_dir():
        raise CreditLedgerError("CREDIT_PROJECT_INVALID")
    try:
        return supplied.resolve(strict=True)
    except OSError as exc:
        raise CreditLedgerError("CREDIT_PROJECT_INVALID") from exc


def _is_reparse(path: Path) -> bool:
    """Reject links and platform reparse points before touching project storage."""
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
        return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    except OSError:
        return False


def _assert_project_path(project: Path, path: Path) -> None:
    current = project
    try:
        relative = path.relative_to(project)
    except ValueError as exc:
        raise CreditLedgerError("CREDIT_LEDGER_INVALID") from exc
    for part in relative.parts:
        current = current / part
        if _is_reparse(current):
            raise CreditLedgerError("CREDIT_LEDGER_INVALID")
    try:
        path.resolve(strict=False).relative_to(project)
    except (OSError, ValueError) as exc:
        raise CreditLedgerError("CREDIT_LEDGER_INVALID") from exc


def _validate_inputs(
    *,
    stage: str,
    before: int,
    after: int,
    source: str,
    study_ids: Sequence[str],
    input_digest: str | None,
    output_digest: str | None,
    forecast: int | float | None,
) -> list[str]:
    if (
        isinstance(before, bool)
        or isinstance(after, bool)
        or not isinstance(before, int)
        or not isinstance(after, int)
        or before < 0
        or after < 0
        or after > before
    ):
        raise CreditLedgerError("CREDIT_MEASUREMENT_INVALID")
    if not isinstance(stage, str) or not _SAFE_NAME.fullmatch(stage):
        raise CreditLedgerError("CREDIT_STAGE_INVALID")
    if not isinstance(source, str) or not _SAFE_NAME.fullmatch(source):
        raise CreditLedgerError("CREDIT_SOURCE_INVALID")
    identifiers = list(study_ids)
    if (
        any(not isinstance(value, str) or not _SAFE_NAME.fullmatch(value) for value in identifiers)
        or len(identifiers) != len(set(identifiers))
    ):
        raise CreditLedgerError("CREDIT_STUDY_IDS_INVALID")
    for digest in (input_digest, output_digest):
        if digest is not None and (not isinstance(digest, str) or not _SHA256.fullmatch(digest)):
            raise CreditLedgerError("CREDIT_DIGEST_INVALID")
    if forecast is not None and (
        isinstance(forecast, bool)
        or not isinstance(forecast, (int, float))
        or not math.isfinite(forecast)
        or forecast < 0
    ):
        raise CreditLedgerError("CREDIT_FORECAST_INVALID")
    return identifiers


@contextmanager
def _ledger_lock(project: Path) -> Iterator[None]:
    lock_path = project / _LOCK_PATH
    _assert_project_path(project, lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    _assert_project_path(project, lock_path)
    if lock_path.is_symlink() or (os.path.lexists(lock_path) and not lock_path.is_file()):
        raise CreditLedgerError("CREDIT_LEDGER_INVALID")
    with lock_path.open("a+b") as lock:
        if os.name == "nt":
            lock.seek(0, os.SEEK_END)
            if lock.tell() == 0:
                lock.write(b"\0")
                lock.flush()
                os.fsync(lock.fileno())
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _read_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if path.is_symlink() or not path.is_file():
        raise CreditLedgerError("CREDIT_LEDGER_INVALID")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise CreditLedgerError("CREDIT_LEDGER_INVALID") from exc
    rows: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            raise CreditLedgerError("CREDIT_LEDGER_INVALID")
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CreditLedgerError("CREDIT_LEDGER_INVALID") from exc
        if not isinstance(row, dict):
            raise CreditLedgerError("CREDIT_LEDGER_INVALID")
        _validate_event(row)
        previous = rows[-1] if rows else None
        if row["previous_event_id"] != (previous["event_id"] if previous else None):
            raise CreditLedgerError("CREDIT_LEDGER_CHAIN_INVALID")
        if previous is not None and row["before"] != previous["after"]:
            raise CreditLedgerError("CREDIT_CONTINUITY_INVALID")
        rows.append(row)
    return rows


def _append_line(path: Path, event: dict[str, Any]) -> None:
    if path.is_symlink() or (os.path.lexists(path) and not path.is_file()):
        raise CreditLedgerError("CREDIT_LEDGER_INVALID")
    content = _canonical_bytes(event) + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
        try:
            offset = 0
            while offset < len(content):
                offset += os.write(descriptor, content[offset:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise CreditLedgerError("CREDIT_LEDGER_WRITE_FAILED") from exc


def record_credit_event(
    project: Path,
    *,
    stage: str = "unspecified",
    before: int,
    after: int,
    source: str,
    study_ids: Sequence[str] = (),
    input_digest: str | None = None,
    output_digest: str | None = None,
    forecast: int | float | None = None,
) -> dict[str, Any]:
    """Append one measured event after validating the existing ledger and continuity."""
    identifiers = _validate_inputs(
        stage=stage,
        before=before,
        after=after,
        source=source,
        study_ids=study_ids,
        input_digest=input_digest,
        output_digest=output_digest,
        forecast=forecast,
    )
    project_path = _safe_project(project)
    ledger_path = project_path / CREDIT_LEDGER_PATH
    _assert_project_path(project_path, ledger_path)
    with _ledger_lock(project_path):
        _assert_project_path(project_path, ledger_path)
        rows = _read_ledger(ledger_path)
        _assert_project_path(project_path, ledger_path)
        if rows and before != rows[-1]["after"]:
            raise CreditLedgerError("CREDIT_CONTINUITY_INVALID")
        event: dict[str, Any] = {
            "schema_version": "credit-event.v1",
            "event_id": "0" * 64,
            "previous_event_id": rows[-1]["event_id"] if rows else None,
            "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "stage": stage,
            "study_ids": identifiers,
            "input_digest": input_digest,
            "output_digest": output_digest,
            "forecast": forecast,
            "before": before,
            "after": after,
            "consumed": before - after,
            "measurement_source": source,
        }
        event["event_id"] = _event_id(event)
        _validate_event(event)
        _append_line(ledger_path, event)
        return event
