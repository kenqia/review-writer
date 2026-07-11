#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = Path("/tmp/review_writer_phase7_validator_test")


def main() -> int:
    test_validator_accepts_grounded_section()
    test_validator_rejects_unsupported_citation_and_numbers()
    test_validator_skips_markdown_headings_and_tolerates_truncated_needs_marker()
    print("grounded_section_validation_tests: ok")
    return 0


def test_validator_accepts_grounded_section() -> None:
    pilot = subprocess.run(
        [
            sys.executable,
            "scripts/demo/run_retrieval_generation_pilot.py",
            "--retrieval-mode",
            "offline_fixture",
            "--generation-provider",
            "offline",
            "--output-root",
            str(OUT_ROOT),
            "--strict",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert pilot.returncode == 0, pilot.stderr + pilot.stdout
    report = json.loads((OUT_ROOT / "grounding_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "pass"
    assert report["claim_evidence_coverage"] == 1.0
    assert report["unsupported_claim_count"] == 0
    assert report["prompt_leakage_count"] == 0
    assert report["needs_human_review"] is True


def test_validator_rejects_unsupported_citation_and_numbers() -> None:
    section = OUT_ROOT / "bad_section.md"
    evidence = OUT_ROOT / "evidence_pack.json"
    section.write_text(
        "Bad section\n\nThis unsupported paragraph claims 95% yield and 99% ee [BAD].\n",
        encoding="utf-8",
    )
    evidence.write_text(
        json.dumps(
            {
                "section_id": "bad",
                "section_title": "Bad",
                "needs_human_review": True,
                "trusted_for_scientific_quality": False,
                "items": [
                    {
                        "paper_id": "F3I",
                        "chunk_id": "F3I-001",
                        "sanitized_text": "safe",
                        "score": 0.9,
                        "title": "safe",
                        "known_warnings": "warning",
                        "needs_human_review": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "scripts/validators/validate_grounded_section.py",
            "--section-md",
            str(section),
            "--evidence-pack-json",
            str(evidence),
            "--output-json",
            str(OUT_ROOT / "bad_grounding_report.json"),
            "--output-md",
            str(OUT_ROOT / "bad_grounding_report.md"),
            "--claim-map-json",
            str(OUT_ROOT / "bad_claim_evidence_map.json"),
            "--strict",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 1, result.stderr + result.stdout
    report = json.loads((OUT_ROOT / "bad_grounding_report.json").read_text(encoding="utf-8"))
    assert report["unsupported_citations"] == ["BAD"]
    assert report["unsupported_claim_count"] >= 1


def test_validator_skips_markdown_headings_and_tolerates_truncated_needs_marker() -> None:
    section = OUT_ROOT / "heading_and_truncated_needs.md"
    evidence = OUT_ROOT / "heading_evidence_pack.json"
    section.write_text(
        "### Representative strategies for asymmetric allene synthesis\n\n"
        "F3I frames allene-centered catalytic asymmetric synthesis as review/background evidence [F3I].\n\n"
        "F47A anchors a palladium allene method signal without numerical outcomes [F47A].\n\n"
        "[NEEDS_E",
        encoding="utf-8",
    )
    evidence.write_text(
        json.dumps(
            {
                "section_id": "heading",
                "section_title": "Heading",
                "needs_human_review": True,
                "trusted_for_scientific_quality": False,
                "items": [
                    {
                        "paper_id": "F3I",
                        "chunk_id": "F3I-001",
                        "sanitized_text": "safe",
                        "score": 0.9,
                        "title": "safe",
                        "known_warnings": "warning",
                        "needs_human_review": True,
                    },
                    {
                        "paper_id": "F47A",
                        "chunk_id": "F47A-001",
                        "sanitized_text": "safe",
                        "score": 0.9,
                        "title": "safe",
                        "known_warnings": "warning",
                        "needs_human_review": True,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "scripts/validators/validate_grounded_section.py",
            "--section-md",
            str(section),
            "--evidence-pack-json",
            str(evidence),
            "--output-json",
            str(OUT_ROOT / "heading_grounding_report.json"),
            "--output-md",
            str(OUT_ROOT / "heading_grounding_report.md"),
            "--claim-map-json",
            str(OUT_ROOT / "heading_claim_evidence_map.json"),
            "--strict",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads((OUT_ROOT / "heading_grounding_report.json").read_text(encoding="utf-8"))
    assert report["claim_evidence_coverage"] == 1.0
    assert report["unsupported_claim_count"] == 0


if __name__ == "__main__":
    raise SystemExit(main())
