#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/audit/audit_clean_3paper_dataset.py"
REPORT = Path("/tmp/test_clean_3paper_audit.json")
DATASET_ROOT = ROOT / "demo_projects/clean_3paper_allene_review"


def main() -> int:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--dataset-root",
            str(DATASET_ROOT),
            "--output-json",
            str(REPORT),
            "--output-md",
            "/tmp/test_clean_3paper_audit.md",
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
        test_top3_shape,
        test_dataset_not_scientific_quality,
        test_no_forbidden_content,
        test_safety_markers,
        test_verified_draft_file,
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
    print(f"clean 3-paper audit tests passed: {len(checks)}")
    return 0


def test_top3_shape(report: dict) -> None:
    assert report["summary"]["top3_count"] == 3
    assert report["summary"]["ids"] == ["F3I", "F47A", "P403"]
    assert report["summary"]["human_verified_false_count"] == 3
    assert report["summary"]["upload_not_used_count"] == 3
    assert report["summary"]["api_unused_count"] == 3


def test_dataset_not_scientific_quality(report: dict) -> None:
    assert report["trusted_for_engineering_fixture"] is True
    assert report["trusted_for_scientific_quality"] is False


def test_no_forbidden_content(report: dict) -> None:
    assert report["blocking_issues"] == []


def test_safety_markers(report: dict) -> None:
    safety = report["safety"]
    assert safety["pdf_body_read"] == "not_used"
    assert safety["qwen"] == "not_used"
    assert safety["mineru_api"] == "not_used"
    assert safety["bailian"] == "not_used"
    assert safety["upload"] == "not_used"
    assert safety["knowledge_base"] == "not_created"


def test_verified_draft_file(report: dict) -> None:
    payload = json.loads((DATASET_ROOT / "inputs/selected_papers.verified_draft.json").read_text(encoding="utf-8"))
    assert [row["candidate_id"] for row in payload["papers"]] == ["F3I", "F47A", "P403"]
    assert all(row["human_verified"] is False for row in payload["papers"])


if __name__ == "__main__":
    raise SystemExit(main())
