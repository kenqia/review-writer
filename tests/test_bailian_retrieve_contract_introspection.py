#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_JSON = Path("/tmp/bailian_retrieve_contract_introspection_test.json")


def main() -> int:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/rag/bailian_retrieve_contract_introspection.py",
            "--output-json",
            str(OUT_JSON),
            "--output-md",
            "/tmp/bailian_retrieve_contract_introspection_test.md",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads(OUT_JSON.read_text(encoding="utf-8"))
    assert "RetrieveRequest" in report["models"]
    assert "RetrieveResponseBodyDataNodes" in report["models"]
    assert "retrieve_with_options" in report["client_methods"]
    supported = report["retrieve_request_supported_fields"]
    for field in [
        "query",
        "index_id",
        "dense_similarity_top_k",
        "sparse_similarity_top_k",
        "enable_reranking",
        "rerank_top_n",
        "rerank_min_score",
        "enable_rewrite",
        "save_retriever_history",
    ]:
        assert field in supported
    text = OUT_JSON.read_text(encoding="utf-8").lower()
    assert "access_key_secret" not in text
    assert "authorization" not in text
    print("bailian_retrieve_contract_introspection_tests: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
