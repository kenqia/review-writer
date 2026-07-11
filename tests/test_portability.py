#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_JSON = Path("/tmp/portability_report_test.json")
REPORT_MD = Path("/tmp/portability_report_test.md")


def main() -> int:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/check_portability.py",
            "--output-json",
            str(REPORT_JSON),
            "--output-md",
            str(REPORT_MD),
            "--strict",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        return 1
    checks = [
        test_report_exists,
        test_no_errors,
        test_qoderwork_skills_have_no_personal_paths,
        test_local_validation_is_allowlisted,
    ]
    failures: list[str] = []
    for check in checks:
        try:
            check()
            print(f"PASS {check.__name__}")
        except AssertionError as exc:
            failures.append(f"{check.__name__}: {exc}")
            print(f"FAIL {check.__name__}: {exc}")
    return 1 if failures else 0


def test_report_exists() -> None:
    assert REPORT_JSON.exists()
    assert REPORT_MD.exists()


def test_no_errors() -> None:
    report = read_report()
    assert report["status"] == "pass", report
    assert not report["errors"], report["errors"]


def test_qoderwork_skills_have_no_personal_paths() -> None:
    text = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "qoderwork/skills").glob("*/SKILL.md"))
    forbidden = ["/home/kenqia", "/mnt/c/Users/26960", "C:\\Users\\26960", "Desktop\\review-writer", ".qoderworkcn"]
    hits = [item for item in forbidden if item in text]
    assert not hits, hits


def test_local_validation_is_allowlisted() -> None:
    report = read_report()
    allowed_paths = {item["path"] for item in report["allowed"]}
    assert "docs/local/KENQIA_LOCAL_VALIDATION.md" in allowed_paths


def read_report() -> dict:
    return json.loads(REPORT_JSON.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
