#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/audit/audit_real_lite_outputs.py"
DEMO_ROOT = ROOT / "demo_projects/real_lite_allene_review"
OUTPUT_ROOT = Path("/tmp/test_review_writer_real_lite_output_audit")
REPORT = Path("/tmp/test_real_lite_output_audit.json")


def main() -> int:
    if OUTPUT_ROOT.exists():
        shutil.rmtree(OUTPUT_ROOT)
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--output-root",
            str(OUTPUT_ROOT),
            "--input-demo-root",
            str(DEMO_ROOT),
            "--output-json",
            str(REPORT),
            "--output-md",
            "/tmp/test_real_lite_output_audit.md",
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
        test_engineering_status_pass,
        test_content_quality_needs_review,
        test_scientific_quality_not_trusted,
        test_core_artifacts_checked,
        test_eval_and_quality_pass,
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
    print(f"real-lite output audit tests passed: {len(checks)}")
    return 0


def test_engineering_status_pass(report: dict) -> None:
    assert report["engineering_status"] == "pass", report
    assert report["trusted_for_demo"] is True


def test_content_quality_needs_review(report: dict) -> None:
    assert report["content_quality_status"] == "needs_human_review", report["content_quality_status"]
    assert report["warnings"], report


def test_scientific_quality_not_trusted(report: dict) -> None:
    assert report["trusted_for_scientific_quality"] is False


def test_core_artifacts_checked(report: dict) -> None:
    checks = report["checks"]
    assert checks["literature_matrix_papers"] == 5, checks
    assert checks["section_blueprint_sections"] >= 1, checks
    assert checks["checkpoint_count"] == 9, checks
    assert checks["figure_count"] >= 1, checks
    assert checks["figures_pointer_or_placeholder"] is True, checks


def test_eval_and_quality_pass(report: dict) -> None:
    checks = report["checks"]
    assert checks["quality_report_status"] in {"pass", "warn"}, checks
    assert checks["eval_status"] == "pass", checks
    assert checks["eval_score"] >= 80, checks


def test_safety_markers(report: dict) -> None:
    assert report["safety"]["network"] == "not_used"
    assert report["safety"]["pdf_read"] == "not_used"
    assert report["safety"]["qwen"] == "not_used"
    assert report["safety"]["mineru_api"] == "not_used"
    assert report["safety"]["upload"] == "not_used"


if __name__ == "__main__":
    raise SystemExit(main())
