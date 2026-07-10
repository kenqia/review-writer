#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_JSON = Path("/tmp/bailian_retrieval_qa_test.json")


def main() -> int:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/rag/bailian_retrieval_qa.py",
            "--index-id",
            "index_should_not_be_printed",
            "--questions",
            "evals/fixtures/rag_expected_questions.json",
            "--output-json",
            str(OUT_JSON),
            "--output-md",
            "/tmp/bailian_retrieval_qa_test.md",
            "--strict",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads(OUT_JSON.read_text(encoding="utf-8"))
    assert report["status"] == "dry_run"
    assert report["index_id_present"] is True
    assert report["index_id"] == "[REDACTED_TMP_ONLY]"
    assert report["matrix_results"]
    assert len({row["query_id"] for row in report["matrix_results"]}) == 4
    assert "official_minimal" in {row["mode"] for row in report["matrix_results"]}
    assert any(row["smoke_fact_found"] for row in report["matrix_results"])
    assert report["working_query"] == "review-writer Phase 6c smoke test"
    assert report["working_retrieval_mode"] in {
        "official_minimal",
        "hybrid_no_rerank",
        "sparse_exact_no_rerank",
        "dense_semantic_no_rerank",
        "rerank_qa",
    }
    assert report["root_cause_classification"] in {
        "query_mismatch",
        "reranking_or_threshold_filter",
        "index_readiness_delay",
        "response_parsing_bug_or_query_mode_fixed",
        "retrieve_service_or_index_content_mismatch",
    }
    assert report["recall_at_3"] >= 0.8
    assert report["citation_coverage"] == 1.0
    combined = result.stdout + OUT_JSON.read_text(encoding="utf-8") + Path("/tmp/bailian_retrieval_qa_test.md").read_text(encoding="utf-8")
    assert "index_should_not_be_printed" not in combined
    assert "OSSAccessKeyId" not in combined
    assert "Signature=" not in combined
    print("bailian_retrieval_qa_tests: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
