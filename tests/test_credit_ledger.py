from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from review_writer.project.credit_ledger import (
    CREDIT_LEDGER_PATH,
    CreditLedgerError,
    record_credit_event,
)


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

