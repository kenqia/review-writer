#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/demo/extract_clean_3paper_claims_figures.py"
DATASET_ROOT = ROOT / "demo_projects/clean_3paper_allene_review"
REPORT = Path("/tmp/test_clean_3paper_claims_figures.json")


def main() -> int:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--dataset-root",
            str(DATASET_ROOT),
            "--paper-root",
            "chem_papers",
            "--output-json",
            str(REPORT),
            "--output-md",
            "/tmp/test_clean_3paper_claims_figures.md",
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
        test_counts_are_reasonable,
        test_all_drafts_need_human_review,
        test_needs_manual_extraction_present,
        test_safety_markers,
        test_committed_outputs_written,
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
    print(f"clean 3-paper claims/figures tests passed: {len(checks)}")
    return 0


def test_counts_are_reasonable(report: dict) -> None:
    by_id = {row["paper_id"]: row for row in report["papers"]}
    assert set(by_id) == {"F3I", "F47A", "P403"}
    for row in by_id.values():
        assert 0 <= len(row["claims"]) <= 4
        assert 0 <= len(row["figure_notes"]) <= 3
    assert report["summary"]["claim_count"] >= 6
    assert report["summary"]["figure_note_count"] == 3


def test_all_drafts_need_human_review(report: dict) -> None:
    for item in report["claims"]:
        assert item["human_verified"] is False
        assert item["needs_human_review"] is True
    for item in report["figure_notes"]:
        assert item["human_verified"] is False
        assert item["needs_human_review"] is True


def test_needs_manual_extraction_present(report: dict) -> None:
    assert report["summary"]["needs_manual_extraction_count"] >= 3
    assert any(item["evidence_source"] == "needs_manual_extraction" for item in report["claims"])
    assert all(item["source"] == "needs_manual_extraction" for item in report["figure_notes"])


def test_safety_markers(report: dict) -> None:
    safety = report["safety"]
    assert safety["network"] == "not_used"
    assert safety["pdf_body_text_extracted"] == "not_used"
    assert safety["qwen"] == "not_used"
    assert safety["mineru_api"] == "not_used"
    assert safety["bailian"] == "not_used"
    assert safety["upload"] == "not_used"
    assert safety["knowledge_base"] == "not_created"
    assert safety["image_api"] == "not_used"
    assert report["trusted_for_scientific_quality"] is False


def test_committed_outputs_written(report: dict) -> None:
    claims = json.loads((DATASET_ROOT / "expected/expected_claims.draft.json").read_text(encoding="utf-8"))
    figures = json.loads((DATASET_ROOT / "expected/expected_figures.draft.json").read_text(encoding="utf-8"))
    assert len(claims["claims"]) == report["summary"]["claim_count"]
    assert len(figures["figure_notes"]) == report["summary"]["figure_note_count"]
    assert all(item["human_verified"] is False for item in claims["claims"])
    assert all(item["needs_human_review"] is True for item in figures["figure_notes"])


if __name__ == "__main__":
    raise SystemExit(main())
