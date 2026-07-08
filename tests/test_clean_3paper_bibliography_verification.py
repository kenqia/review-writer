#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/demo/verify_clean_3paper_bibliography.py"
REPORT = Path("/tmp/test_clean_3paper_bibliography_verification.json")
DATASET_ROOT = ROOT / "demo_projects/clean_3paper_allene_review"


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
            "/tmp/test_clean_3paper_bibliography_verification.md",
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
        test_default_no_network,
        test_top3_shape,
        test_required_fields,
        test_human_review_boundary,
        test_no_external_actions,
        test_dataset_outputs_exist,
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
    print(f"clean 3-paper bibliography verification tests passed: {len(checks)}")
    return 0


def test_default_no_network(report: dict) -> None:
    assert report["summary"]["allow_network_metadata"] is False
    assert report["summary"]["network_metadata"] == "not_used"
    assert report["safety"]["network"] == "not_used"


def test_top3_shape(report: dict) -> None:
    assert [row["candidate_id"] for row in report["papers"]] == ["F3I", "F47A", "P403"]


def test_required_fields(report: dict) -> None:
    for row in report["papers"]:
        assert row["verified_title_draft"]
        assert row["metadata_confidence"] in {"low", "medium", "high"}
        assert row["verification_status"] in {
            "bibliographic_verified_draft",
            "needs_human_review",
            "insufficient_metadata",
        }
        assert "conflicts" in row
        assert "missing_fields" in row
        doi = row["doi_draft"]
        assert doi == "unknown" or doi.startswith("10.")


def test_human_review_boundary(report: dict) -> None:
    assert all(row["human_verified"] is False for row in report["papers"])
    assert all(row["needs_human_review"] is True for row in report["papers"])


def test_no_external_actions(report: dict) -> None:
    safety = report["safety"]
    assert safety["pdf_upload"] == "not_used"
    assert safety["qwen"] == "not_used"
    assert safety["mineru_api"] == "not_used"
    assert safety["bailian"] == "not_used"
    assert safety["knowledge_base"] == "not_created"
    assert safety["image_api"] == "not_used"


def test_dataset_outputs_exist(report: dict) -> None:
    assert (DATASET_ROOT / "inputs/bibliography_verification_summary.json").exists()
    assert (DATASET_ROOT / "inputs/bibliography_verification_summary.md").exists()
    for candidate_id in ["F3I", "F47A", "P403"]:
        assert (DATASET_ROOT / f"inputs/verified_metadata/{candidate_id}.metadata.verified_draft.json").exists()


if __name__ == "__main__":
    raise SystemExit(main())
