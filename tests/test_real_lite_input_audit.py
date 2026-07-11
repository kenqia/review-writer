#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/audit/audit_real_lite_inputs.py"
DEMO_ROOT = ROOT / "demo_projects/real_lite_allene_review"
REPORT = Path("/tmp/test_real_lite_input_audit.json")


def main() -> int:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--demo-root",
            str(DEMO_ROOT),
            "--output-json",
            str(REPORT),
            "--output-md",
            "/tmp/test_real_lite_input_audit.md",
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
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    checks = [
        test_status_warn_not_fail,
        test_selected_count,
        test_engineering_fixture_trusted,
        test_quality_not_trusted,
        test_each_paper_has_pointer_warning,
        test_safety_markers,
    ]
    failures: list[str] = []
    for check in checks:
        try:
            check(report)
            print(f"PASS {check.__name__}")
        except AssertionError as exc:
            failures.append(f"{check.__name__}: {exc}")
            print(f"FAIL {check.__name__}: {exc}")
    if failures:
        return 1
    print(f"real-lite input audit tests passed: {len(checks)}")
    return 0


def test_status_warn_not_fail(report: dict) -> None:
    assert report["status"] == "warn", report["status"]
    assert not report["blocking_issues"], report["blocking_issues"]


def test_selected_count(report: dict) -> None:
    assert report["selected_count"] == 5, report["selected_count"]


def test_engineering_fixture_trusted(report: dict) -> None:
    assert report["trusted_for_engineering_fixture"] is True


def test_quality_not_trusted(report: dict) -> None:
    assert report["trusted_for_quality"] is False
    assert report["summary"]["doi_missing_count"] >= 3
    assert report["summary"]["human_unchecked_count"] >= 3


def test_each_paper_has_pointer_warning(report: dict) -> None:
    for row in report["per_paper_findings"]:
        assert row["content_list_pointer_only"] is True, row
        assert row["figures_pointer_only"] is True, row
        assert row["source_paths_are_placeholders"] is True, row


def test_safety_markers(report: dict) -> None:
    assert report["safety"]["network"] == "not_used"
    assert report["safety"]["pdf_read"] == "not_used"
    assert report["safety"]["qwen"] == "not_used"
    assert report["safety"]["mineru_api"] == "not_used"
    assert report["safety"]["upload"] == "not_used"


if __name__ == "__main__":
    raise SystemExit(main())
