#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
FIXTURE = REPO_ROOT / "tests/fixtures/retrieval_generation/clean_3paper_retrieval_fixture.json"
OUT_ROOT = Path("/tmp/review_writer_phase7_test_offline")


def main() -> int:
    test_pipeline_builds_safe_evidence_pack()
    test_offline_generation_is_grounded()
    test_demo_script_offline_outputs_checkpoint()
    print("retrieval_generation_pipeline_tests: ok")
    return 0


def test_pipeline_builds_safe_evidence_pack() -> None:
    from review_writer.pipeline.retrieval_generation import build_evidence_pack, load_retrieval_fixture

    pack = build_evidence_pack(
        load_retrieval_fixture(FIXTURE),
        section_id="phase7-single-section",
        section_title="Representative strategies for asymmetric allene synthesis",
        max_evidence_items=3,
    )
    assert pack.needs_human_review is True
    assert pack.trusted_for_scientific_quality is False
    assert [item.paper_id for item in pack.items] == ["F3I", "F47A", "P403"]
    rendered = json.dumps(pack.to_safe_dict(), ensure_ascii=False)
    forbidden = ["signed", "workspace", "document_id", "pipeline_id", "file_path", "/home/", "http"]
    assert not any(token in rendered.lower() for token in forbidden)


def test_offline_generation_is_grounded() -> None:
    from review_writer.pipeline.retrieval_generation import (
        build_evidence_pack,
        generate_grounded_section,
        load_retrieval_fixture,
    )

    pack = build_evidence_pack(
        load_retrieval_fixture(FIXTURE),
        section_id="phase7-single-section",
        section_title="Representative strategies for asymmetric allene synthesis",
        max_evidence_items=3,
    )
    result = generate_grounded_section(pack, generation_provider="offline")
    assert result.provider == "offline"
    assert result.checkpoint == "Sections: ready_for_human_review"
    assert result.needs_human_review is True
    assert "[F3I]" in result.section_text
    assert "[F47A]" in result.section_text
    assert "[P403]" in result.section_text
    assert "prompt" not in result.section_text.lower()


def test_demo_script_offline_outputs_checkpoint() -> None:
    result = subprocess.run(
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
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads((OUT_ROOT / "phase7_retrieval_generation_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "pass"
    assert report["checkpoint"] == "Sections: ready_for_human_review"
    assert report["claim_evidence_coverage"] == 1.0
    assert report["unsupported_claim_count"] == 0
    assert report["safety"]["pdf_uploaded"] == "no"
    assert report["safety"]["full_text_uploaded"] == "no"


if __name__ == "__main__":
    raise SystemExit(main())
