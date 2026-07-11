#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/demo/verify_clean_3paper_pdfs.py"
REPORT = Path("/tmp/test_clean_3paper_pdf_verification.json")


def main() -> int:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--dataset-root",
            "demo_projects/clean_3paper_allene_review",
            "--paper-root",
            "chem_papers",
            "--output-json",
            str(REPORT),
            "--output-md",
            "/tmp/test_clean_3paper_pdf_verification.md",
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
        test_top3_found,
        test_statuses_are_draft,
        test_only_top3_paths,
        test_safety_markers,
        test_no_human_verified,
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
    print(f"clean 3-paper PDF verification tests passed: {len(checks)}")
    return 0


def test_top3_found(report: dict) -> None:
    assert report["summary"]["found_count"] == 3, report["summary"]
    assert [row["candidate_id"] for row in report["papers"]] == ["F3I", "F47A", "P403"]
    assert all(row["pdf_exists"] is True for row in report["papers"])


def test_statuses_are_draft(report: dict) -> None:
    assert all(row["verification_status"] == "verified_draft" for row in report["papers"])
    assert report["summary"]["verification_level"] == "verified_draft_not_final"


def test_only_top3_paths(report: dict) -> None:
    paths = [row["pdf_path"] for row in report["papers"]]
    assert len(paths) == 3
    assert any("3i-" in path for path in paths)
    assert any("47a-" in path for path in paths)
    assert any("secondary-phosphine-oxides" in path for path in paths)


def test_safety_markers(report: dict) -> None:
    safety = report["safety"]
    assert safety["network"] == "not_used"
    assert safety["qwen"] == "not_used"
    assert safety["mineru_api"] == "not_used"
    assert safety["bailian"] == "not_used"
    assert safety["upload"] == "not_used"
    assert safety["knowledge_base"] == "not_created"
    assert safety["image_api"] == "not_used"
    assert report["summary"]["full_chem_papers_scan"] == "not_used"


def test_no_human_verified(report: dict) -> None:
    assert all(row["human_verified"] is False for row in report["papers"])
    assert all(row["needs_human_review"] is True for row in report["papers"])


if __name__ == "__main__":
    raise SystemExit(main())
