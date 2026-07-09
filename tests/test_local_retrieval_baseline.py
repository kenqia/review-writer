#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_JSON = Path("/tmp/local_retrieval_baseline_test.json")
REPORT_MD = Path("/tmp/local_retrieval_baseline_test.md")


def main() -> int:
    cmd = [
        sys.executable,
        "scripts/rag/local_retrieval_baseline.py",
        "--manifest",
        "/tmp/bailian_no_upload_corpus_manifest.json",
        "--questions",
        "evals/fixtures/rag_expected_questions.json",
        "--output-json",
        str(REPORT_JSON),
        "--output-md",
        str(REPORT_MD),
        "--strict",
    ]
    result = subprocess.run(cmd, cwd=REPO_ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
    assert report["status"] in {"pass", "warn"}, report
    assert report["recall_at_3"] >= 0.8, report
    assert report["citation_coverage"] == 1.0, report
    assert report["recommendation"] == "proceed_to_bailian_pilot", report
    assert report["trusted_for_scientific_quality"] is False
    assert report["missed_questions"] == []
    assert report["safety"]["network"] == "not_used"
    assert report["safety"]["bailian_api"] == "not_used"
    assert report["safety"]["upload"] == "not_used"
    assert report["safety"]["knowledge_base"] == "not_created"
    assert len(report["per_question_results"]) >= 6
    print("local_retrieval_baseline_tests: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

