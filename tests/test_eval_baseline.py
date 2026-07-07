#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = Path("/tmp/review_writer_real_lite_e2e")
RUNNER = ROOT / "scripts/eval/run_eval_baseline.py"
DEMO_RUNNER = ROOT / "scripts/demo/run_real_lite_e2e.py"
DEMO_ROOT = ROOT / "demo_projects/real_lite_allene_review"
BASELINE = ROOT / "evals/baselines/real_lite_v1.yaml"
EXPECTED = ROOT / "evals/fixtures/real_lite_expected_metrics.json"
REPORT_JSON = Path("/tmp/real_lite_eval_report_test.json")
REPORT_MD = Path("/tmp/real_lite_eval_report_test.md")


def main() -> int:
    ensure_output_root()
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--output-root",
            str(OUTPUT_ROOT),
            "--baseline",
            str(BASELINE),
            "--expected",
            str(EXPECTED),
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
        test_score_meets_minimum,
        test_safety_boundary_pass,
        test_workflow_completeness_pass,
        test_prompt_leakage_absence_pass,
        test_no_api_markers,
    ]
    failures: list[str] = []
    for check in checks:
        try:
            check()
            print(f"PASS {check.__name__}")
        except AssertionError as exc:
            failures.append(f"{check.__name__}: {exc}")
            print(f"FAIL {check.__name__}: {exc}")
    if failures:
        return 1
    print(f"eval baseline tests passed: {len(checks)}")
    return 0


def ensure_output_root() -> None:
    if (OUTPUT_ROOT / "run_summary.json").exists():
        return
    if OUTPUT_ROOT.exists():
        shutil.rmtree(OUTPUT_ROOT)
    result = subprocess.run(
        [
            sys.executable,
            str(DEMO_RUNNER),
            "--demo-root",
            str(DEMO_ROOT),
            "--output-root",
            str(OUTPUT_ROOT),
            "--strict",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)


def test_report_exists() -> None:
    assert REPORT_JSON.exists(), "JSON report missing"
    assert REPORT_MD.exists(), "Markdown report missing"


def test_score_meets_minimum() -> None:
    report = read_json(REPORT_JSON)
    expected = read_json(EXPECTED)
    assert report["score_total"] >= expected["minimum_score"], report
    assert report["status"] == "pass", report


def test_safety_boundary_pass() -> None:
    metric = metric_by_id("safety_boundary")
    assert metric["status"] == "pass", metric


def test_workflow_completeness_pass() -> None:
    metric = metric_by_id("workflow_completeness")
    assert metric["status"] == "pass", metric


def test_prompt_leakage_absence_pass() -> None:
    metric = metric_by_id("prompt_leakage_absence")
    assert metric["status"] == "pass", metric


def test_no_api_markers() -> None:
    report = read_json(REPORT_JSON)
    safety = report["safety"]
    assert safety["network"] == "not_used"
    assert safety["pdf_read"] == "not_used"
    assert safety["qwen"] == "not_used"
    assert safety["mineru_api"] == "not_used"
    assert safety["upload"] == "not_used"
    assert safety["promptfoo"] == "not_used"


def metric_by_id(metric_id: str) -> dict:
    report = read_json(REPORT_JSON)
    for metric in report["metrics"]:
        if metric["metric_id"] == metric_id:
            return metric
    raise AssertionError(f"metric not found: {metric_id}")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
