#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = Path("/tmp/review_writer_clean_3paper_e2e")
RUNNER = ROOT / "scripts/eval/run_clean_3paper_eval.py"
DEMO_RUNNER = ROOT / "scripts/demo/run_clean_3paper_e2e.py"
DEMO_ROOT = ROOT / "demo_projects/clean_3paper_allene_review"
BASELINE = ROOT / "evals/baselines/clean_3paper_v1.yaml"
EXPECTED = ROOT / "evals/fixtures/clean_3paper_expected_metrics.json"
REPORT_JSON = Path("/tmp/clean_3paper_eval_report_test.json")
REPORT_MD = Path("/tmp/clean_3paper_eval_report_test.md")


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
        test_report_passes,
        test_required_metrics_pass,
        test_safety_markers,
        test_human_review_flags,
        test_output_eval_files_written,
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
    print(f"clean 3-paper eval tests passed: {len(checks)}")
    return 0


def ensure_output_root() -> None:
    if (OUTPUT_ROOT / "run_summary.json").exists():
        return
    if OUTPUT_ROOT.exists():
        shutil.rmtree(OUTPUT_ROOT)
    result = subprocess.run(
        [sys.executable, str(DEMO_RUNNER), "--demo-root", str(DEMO_ROOT), "--output-root", str(OUTPUT_ROOT), "--strict"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)


def test_report_passes() -> None:
    report = read_json(REPORT_JSON)
    expected = read_json(EXPECTED)
    assert report["status"] == "pass", report
    assert report["score_total"] >= expected["minimum_score"], report


def test_required_metrics_pass() -> None:
    report = read_json(REPORT_JSON)
    metrics = {row["metric_id"]: row for row in report["metrics"]}
    for metric_id in read_json(EXPECTED)["required_metrics"]:
        assert metrics[metric_id]["status"] == "pass", metrics[metric_id]


def test_safety_markers() -> None:
    safety = read_json(REPORT_JSON)["safety"]
    assert safety["network"] == "not_used"
    assert safety["pdf_read"] == "not_used"
    assert safety["qwen"] == "not_used"
    assert safety["mineru_api"] == "not_used"
    assert safety["upload"] == "not_used"
    assert safety["knowledge_base"] == "not_created"


def test_human_review_flags() -> None:
    report = read_json(REPORT_JSON)
    assert report["trusted_for_scientific_quality"] is False
    assert report["needs_human_review"] is True


def test_output_eval_files_written() -> None:
    assert (OUTPUT_ROOT / "eval/clean_3paper_eval_report.json").exists()
    assert (OUTPUT_ROOT / "eval/clean_3paper_eval_report.md").exists()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
