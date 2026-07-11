#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/demo/recommend_clean_3paper_candidates.py"
REPORT = Path("/tmp/test_clean_3paper_recommendations.json")


def main() -> int:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--paper-root",
            "chem_papers",
            "--real-lite-root",
            "demo_projects/real_lite_allene_review",
            "--output-json",
            str(REPORT),
            "--output-md",
            "/tmp/test_clean_3paper_recommendations.md",
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
        test_candidate_count,
        test_top3_balanced,
        test_no_human_verified_candidates,
        test_all_need_pdf_verification,
        test_no_external_actions,
        test_committed_candidate_file_matches_shape,
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
    print(f"clean 3-paper recommendation tests passed: {len(checks)}")
    return 0


def test_candidate_count(report: dict) -> None:
    assert 6 <= len(report["candidates"]) <= 10, len(report["candidates"])


def test_top3_balanced(report: dict) -> None:
    by_id = {row["candidate_id"]: row for row in report["candidates"]}
    selected = report["recommended_sets"][0]["selected_candidates"]
    assert selected == ["F3I", "F47A", "P403"], selected
    roles = {by_id[candidate_id]["role"] for candidate_id in selected}
    assert roles == {"review_background", "representative_method", "recent_progress"}, roles


def test_no_human_verified_candidates(report: dict) -> None:
    assert all(row["human_verified"] is False for row in report["candidates"])


def test_all_need_pdf_verification(report: dict) -> None:
    assert all(row["needs_pdf_read_verification"] is True for row in report["candidates"])


def test_no_external_actions(report: dict) -> None:
    safety = report["safety"]
    assert safety["network"] == "not_used"
    assert safety["pdf_body_read"] == "not_used"
    assert safety["qwen"] == "not_used"
    assert safety["mineru_api"] == "not_used"
    assert safety["upload"] == "not_used"
    assert safety["knowledge_base"] == "not_created"


def test_committed_candidate_file_matches_shape(report: dict) -> None:
    committed = ROOT / "demo_projects/clean_3paper_allene_review/inputs/selected_papers.candidates.json"
    assert committed.exists(), committed
    payload = json.loads(committed.read_text(encoding="utf-8"))
    assert payload["recommended_sets"][0]["selected_candidates"] == report["recommended_sets"][0]["selected_candidates"]
    assert all(row["human_verified"] is False for row in payload["candidates"])


if __name__ == "__main__":
    raise SystemExit(main())
