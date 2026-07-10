#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT = Path("/tmp/bailian_payload_parse_readiness_test.json")


def main() -> int:
    build_payload()
    result = subprocess.run(
        [
            sys.executable,
            "scripts/rag/check_bailian_payload_parse_readiness.py",
            "--payload-md",
            "/tmp/bailian_small_kb_upload_payload.md",
            "--output-json",
            str(REPORT),
            "--output-md",
            "/tmp/bailian_payload_parse_readiness_test.md",
            "--strict",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    assert report["status"] == "pass"
    assert report["exists"] is True
    assert report["extension"] == ".md"
    assert report["contains_smoke_fact"] is True
    assert report["has_h1_title"] is True
    assert report["section_heading_count"] >= 2
    assert report["has_explicit_fact_line"] is True
    assert report["forbidden_marker_found"] is False
    text = Path("/tmp/bailian_small_kb_upload_payload.md").read_text(encoding="utf-8")
    assert "# Bailian Small Knowledge Base Smoke Test" in text
    assert "Project name: review-writer Phase 6c smoke test." in text
    assert ".pdf" not in text.lower()
    assert "api_key=" not in text.lower()
    assert "token=" not in text.lower()
    print("bailian_payload_parse_readiness_tests: ok")
    return 0


def build_payload() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/rag/build_bailian_small_kb_payload.py",
            "--clean-root",
            "demo_projects/clean_3paper_allene_review",
            "--output-jsonl",
            "/tmp/bailian_small_kb_payload.jsonl",
            "--output-md",
            "/tmp/bailian_small_kb_payload.md",
            "--output-manifest",
            "/tmp/bailian_small_kb_payload_manifest.json",
            "--strict",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout


if __name__ == "__main__":
    raise SystemExit(main())
