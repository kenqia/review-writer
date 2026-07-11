#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = Path("/tmp/review_writer_phase7_validator_test")
FIXTURE_ROOT = REPO_ROOT / "tests/fixtures/retrieval_generation"


def main() -> int:
    test_validator_accepts_grounded_section()
    test_validator_rejects_unsupported_citation_and_numbers()
    test_validator_skips_markdown_headings_and_accepts_complete_needs_marker()
    test_validator_rejects_malformed_needs_marker()
    test_validator_rejects_unsupported_generalization_with_valid_citation()
    test_validator_rejects_mechanism_claim_and_sentence_fragment()
    test_sanitized_qwen_real_section_fixture_validates()
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


def test_validator_skips_markdown_headings_and_accepts_complete_needs_marker() -> None:
    section = OUT_ROOT / "heading_and_truncated_needs.md"
    evidence = OUT_ROOT / "heading_evidence_pack.json"
    section.write_text(
        "### Representative strategies for asymmetric allene synthesis\n\n"
        "F3I frames allene-centered catalytic asymmetric synthesis as review/background evidence [F3I].\n\n"
        "F47A anchors a palladium allene method signal without numerical outcomes [F47A].\n\n"
        "[NEEDS_EVIDENCE: verify source-level details before adding numerical claims.]",
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
    assert report["malformed_marker_count"] == 0


def test_validator_rejects_malformed_needs_marker() -> None:
    report = run_validation_for_section("[NEEDS_E")
    assert report["status"] == "fail"
    assert report["malformed_marker_count"] == 1


def test_validator_rejects_unsupported_generalization_with_valid_citation() -> None:
    report = run_validation_for_section(
        "Palladium-catalyzed allene synthesis is one of the most robust and broadly applicable strategies in modern organic chemistry [F47A]."
    )
    assert report["status"] == "fail"
    assert report["unsupported_claim_count"] == 1


def test_validator_rejects_mechanism_claim_and_sentence_fragment() -> None:
    mechanism = run_validation_for_section("The reaction proceeds through a well-defined pi-allyl palladium mechanism [F47A].")
    assert mechanism["status"] == "fail"
    fragment = run_validation_for_section("F47A anchors a palladium allene method signal without")
    assert fragment["status"] == "fail"
    assert fragment["sentence_fragment_count"] == 1


def run_validation_for_section(section_text: str) -> dict:
    section = OUT_ROOT / "negative_control_section.md"
    evidence = OUT_ROOT / "negative_control_evidence_pack.json"
    section.write_text(section_text + "\n", encoding="utf-8")
    evidence.write_text(
        json.dumps(
            {
                "section_id": "negative",
                "section_title": "Negative",
                "needs_human_review": True,
                "trusted_for_scientific_quality": False,
                "items": [
                    {
                        "paper_id": "F47A",
                        "chunk_id": "F47A-001",
                        "sanitized_text": "F47A anchors a palladium allene method signal; exact outcomes remain manual-review tasks.",
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
            str(OUT_ROOT / "negative_grounding_report.json"),
            "--output-md",
            str(OUT_ROOT / "negative_grounding_report.md"),
            "--claim-map-json",
            str(OUT_ROOT / "negative_claim_evidence_map.json"),
            "--strict",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 1, result.stderr + result.stdout
    return json.loads((OUT_ROOT / "negative_grounding_report.json").read_text(encoding="utf-8"))


def test_sanitized_qwen_real_section_fixture_validates() -> None:
    section_fixture = FIXTURE_ROOT / "qwen_real_section_sanitized.md"
    expected_fixture = FIXTURE_ROOT / "qwen_real_section_expected.json"
    if not section_fixture.exists() or not expected_fixture.exists():
        return
    expected = json.loads(expected_fixture.read_text(encoding="utf-8"))
    result = subprocess.run(
        [
            sys.executable,
            "scripts/validators/validate_grounded_section.py",
            "--section-md",
            str(section_fixture),
            "--evidence-pack-json",
            str(FIXTURE_ROOT / "clean_3paper_retrieval_fixture.json"),
            "--output-json",
            str(OUT_ROOT / "qwen_fixture_grounding_report.json"),
            "--output-md",
            str(OUT_ROOT / "qwen_fixture_grounding_report.md"),
            "--claim-map-json",
            str(OUT_ROOT / "qwen_fixture_claim_evidence_map.json"),
            "--strict",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads((OUT_ROOT / "qwen_fixture_grounding_report.json").read_text(encoding="utf-8"))
    validation = expected["expected_validation"]
    assert report["status"] == validation["status"]
    assert report["claim_evidence_coverage"] == validation["claim_evidence_coverage"]
    assert report["unsupported_claim_count"] == validation["unsupported_claim_count"]
    assert report["unsupported_citations"] == validation["unsupported_citations"]
    assert report["prompt_leakage_count"] == validation["prompt_leakage_count"]
    assert report["needs_human_review"] is validation["needs_human_review"]


if __name__ == "__main__":
    raise SystemExit(main())
