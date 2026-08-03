from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from review_writer.project.credit_ledger import (
    CREDIT_LEDGER_PATH,
    CreditLedgerError,
    credit_ledger_summary,
    record_credit_event,
)
from review_writer.project import credit_ledger


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas/operations/credit_event.v1.schema.json"
CLI = ROOT / "scripts/run_vertical_review.py"


def _ledger_bytes(project: Path) -> bytes:
    return (project / CREDIT_LEDGER_PATH).read_bytes()


def _ledger_rows(project: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in _ledger_bytes(project).decode("utf-8").splitlines()
        if line.strip()
    ]


def test_credit_ledger_records_reported_baseline(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    event = record_credit_event(
        project,
        stage="three_paper_complete_loop",
        before=2004,
        after=1351,
        source="manual_dashboard",
        study_ids=["study-01", "study-02", "study-03"],
        input_digest="a" * 64,
        output_digest="b" * 64,
        forecast=650,
    )

    assert event["consumed"] == 653
    assert event["before"] == 2004
    assert event["after"] == 1351
    assert _ledger_rows(project) == [event]
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(event)
    serialized = json.dumps(event, sort_keys=True).casefold()
    assert all(term not in serialized for term in ("account", "token", "cookie", "session", "auth"))


def test_credit_ledger_summary_is_explicitly_unavailable_when_missing(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    assert credit_ledger_summary(project) == {
        "status": "unavailable",
        "continuity": "unavailable",
        "event_count": 0,
        "measured": None,
        "forecast": None,
        "forecast_variance": None,
        "remaining": None,
        "cache": {"status": "unavailable", "hits": None, "misses": None},
        "retries": {"status": "unavailable", "count": None, "events": []},
    }


def test_credit_ledger_summary_uses_validated_chain_without_guessing_operations(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    record_credit_event(
        project,
        stage="three_paper_complete_loop",
        before=2004,
        after=1351,
        source="manual_dashboard",
        forecast=650,
    )

    assert credit_ledger_summary(project) == {
        "status": "available",
        "continuity": "verified",
        "event_count": 1,
        "measured": {"before": 2004, "after": 1351, "consumed": 653},
        "forecast": 650,
        "forecast_variance": 3,
        "remaining": 1351,
        "cache": {"status": "unavailable", "hits": None, "misses": None},
        "retries": {"status": "unavailable", "count": None, "events": []},
    }


def test_credit_ledger_summary_fails_closed_on_invalid_chain(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    record_credit_event(
        project,
        stage="source_review",
        before=100,
        after=90,
        source="manual_dashboard",
    )
    ledger = project / CREDIT_LEDGER_PATH
    ledger.write_text(ledger.read_text(encoding="utf-8").replace('"after":90', '"after":91'), encoding="utf-8")

    with pytest.raises(CreditLedgerError):
        credit_ledger_summary(project)


def test_credit_ledger_rejects_broken_continuity_without_append(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    record_credit_event(
        project,
        stage="source_review",
        before=2004,
        after=1351,
        source="manual_dashboard",
    )
    before = _ledger_bytes(project)

    with pytest.raises(CreditLedgerError, match="CREDIT_CONTINUITY_INVALID"):
        record_credit_event(
            project,
            stage="synthesis",
            before=1400,
            after=1300,
            source="manual_dashboard",
        )

    assert _ledger_bytes(project) == before


@pytest.mark.parametrize(
    ("before", "after"),
    [(1350, 1400), (-1, 0), (True, 0)],
)
def test_credit_ledger_rejects_invalid_measurement_without_writing(
    tmp_path: Path,
    before: int,
    after: int,
) -> None:
    project = tmp_path / "project"
    project.mkdir()

    with pytest.raises(CreditLedgerError, match="CREDIT_MEASUREMENT_INVALID"):
        record_credit_event(
            project,
            stage="source_review",
            before=before,
            after=after,
            source="manual_dashboard",
        )

    assert not (project / CREDIT_LEDGER_PATH).exists()


def test_record_credits_cli_appends_one_schema_valid_event(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    result = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "record-credits",
            "--project",
            str(project),
            "--stage",
            "manual_three_paper_run",
            "--before",
            "2004",
            "--after",
            "1351",
            "--source",
            "manual_dashboard",
            "--study-id",
            "study-01",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "command": "record-credits",
        "consumed": 653,
        "event_id": _ledger_rows(project)[0]["event_id"],
        "status": "RECORDED",
    }
    assert len(_ledger_rows(project)) == 1


def test_credit_ledger_rejects_symlinked_output_parent_without_external_writes(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (project / "06_evaluation").symlink_to(outside, target_is_directory=True)

    with pytest.raises(CreditLedgerError, match="CREDIT_LEDGER_INVALID"):
        record_credit_event(
            project,
            stage="source_review",
            before=2004,
            after=1351,
            source="manual_dashboard",
        )

    assert list(outside.iterdir()) == []


def test_credit_ledger_rechecks_containment_after_ledger_parse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    original_read = credit_ledger._read_ledger

    def swap_parent_after_parse(path: Path, **kwargs: object) -> list[dict[str, object]]:
        rows = original_read(path, **kwargs)
        evaluation = project / "06_evaluation"
        (evaluation / ".credit_ledger.lock").unlink()
        evaluation.rmdir()
        evaluation.symlink_to(outside, target_is_directory=True)
        return rows

    monkeypatch.setattr(credit_ledger, "_read_ledger", swap_parent_after_parse)

    with pytest.raises(CreditLedgerError, match="CREDIT_LEDGER_INVALID"):
        record_credit_event(
            project,
            stage="source_review",
            before=2004,
            after=1351,
            source="manual_dashboard",
        )

    assert list(outside.iterdir()) == []
    assert os.path.lexists(project / "06_evaluation")


def test_credit_ledger_rejects_hardlinked_ledger_without_external_writes(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    record_credit_event(
        project,
        stage="source_review",
        before=2004,
        after=1351,
        source="manual_dashboard",
    )
    ledger = project / CREDIT_LEDGER_PATH
    outside = tmp_path / "outside-ledger.jsonl"
    os.link(ledger, outside)
    before = outside.read_bytes()

    with pytest.raises(CreditLedgerError, match="CREDIT_LEDGER_INVALID"):
        record_credit_event(
            project,
            stage="synthesis",
            before=1351,
            after=1300,
            source="manual_dashboard",
        )

    assert outside.read_bytes() == before


def test_credit_ledger_rejects_hardlinked_lock_without_external_writes(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    record_credit_event(
        project,
        stage="source_review",
        before=2004,
        after=1351,
        source="manual_dashboard",
    )
    lock = project / "06_evaluation/.credit_ledger.lock"
    outside = tmp_path / "outside-lock"
    os.link(lock, outside)
    before = outside.read_bytes()

    with pytest.raises(CreditLedgerError, match="CREDIT_LEDGER_INVALID"):
        record_credit_event(
            project,
            stage="synthesis",
            before=1351,
            after=1300,
            source="manual_dashboard",
        )

    assert outside.read_bytes() == before


def test_credit_ledger_rolls_back_partial_append_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    record_credit_event(
        project,
        stage="source_review",
        before=2004,
        after=1351,
        source="manual_dashboard",
    )
    before = _ledger_bytes(project)
    original_write = credit_ledger.os.write
    calls = 0

    def partial_then_fail(descriptor: int, content: bytes) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            return original_write(descriptor, content[:1])
        raise OSError("injected append failure")

    monkeypatch.setattr(credit_ledger.os, "write", partial_then_fail)

    with pytest.raises(CreditLedgerError, match="CREDIT_LEDGER_WRITE_FAILED"):
        record_credit_event(
            project,
            stage="synthesis",
            before=1351,
            after=1300,
            source="manual_dashboard",
        )

    assert _ledger_bytes(project) == before


def test_credit_ledger_rolls_back_when_post_append_validation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    record_credit_event(
        project,
        stage="source_review",
        before=2004,
        after=1351,
        source="manual_dashboard",
    )
    before = _ledger_bytes(project)
    original_assert = credit_ledger._assert_directory_handle
    calls = 0

    def fail_post_append(storage: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 5:
            raise CreditLedgerError("CREDIT_LEDGER_INVALID")
        original_assert(storage)

    monkeypatch.setattr(credit_ledger, "_assert_directory_handle", fail_post_append)

    with pytest.raises(CreditLedgerError, match="CREDIT_LEDGER_INVALID"):
        record_credit_event(
            project,
            stage="synthesis",
            before=1351,
            after=1300,
            source="manual_dashboard",
        )

    assert _ledger_bytes(project) == before


def test_credit_ledger_rejects_file_replacement_between_read_and_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    record_credit_event(
        project,
        stage="source_review",
        before=2004,
        after=1351,
        source="manual_dashboard",
    )
    ledger = project / CREDIT_LEDGER_PATH
    original = ledger.read_bytes()
    displaced = tmp_path / "displaced-ledger.jsonl"
    original_read = credit_ledger._read_ledger

    def replace_after_read(path: Path, **kwargs: object) -> list[dict[str, object]]:
        rows = original_read(path, **kwargs)
        path.rename(displaced)
        path.write_bytes(b"")
        return rows

    monkeypatch.setattr(credit_ledger, "_read_ledger", replace_after_read)

    with pytest.raises(CreditLedgerError, match="CREDIT_LEDGER_INVALID"):
        record_credit_event(
            project,
            stage="synthesis",
            before=1351,
            after=1300,
            source="manual_dashboard",
        )

    assert displaced.read_bytes() == original
    assert ledger.read_bytes() == b""
