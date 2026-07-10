#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(REPO_ROOT))

from review_writer.retrieval.bailian_official_client import (  # noqa: E402
    BailianOfficialClient,
    BailianOfficialConfig,
    validate_rerank_config,
)


def main() -> int:
    test_default_request_has_no_rerank()
    test_allowed_rerank_modes()
    test_invalid_rerank_mode()
    test_invalid_rerank_instruct()
    test_cli_invalid_rerank_fails_fast()
    print("bailian_create_index_request_tests: ok")
    return 0


def test_default_request_has_no_rerank() -> None:
    kwargs = BailianOfficialClient(BailianOfficialConfig()).create_index_request_kwargs("file-test")
    assert kwargs["document_ids"] == ["file-test"]
    assert "category_ids" not in kwargs
    assert "rerank_mode" not in kwargs
    assert "rerank_instruct" not in kwargs


def test_allowed_rerank_modes() -> None:
    for mode in ["qa", "similar"]:
        kwargs = BailianOfficialClient(BailianOfficialConfig(rerank_mode=mode)).create_index_request_kwargs("file-test")
        assert kwargs["rerank_mode"] == mode
        assert "rerank_instruct" not in kwargs
    kwargs = BailianOfficialClient(
        BailianOfficialConfig(rerank_mode="custom", rerank_instruct="short instruction")
    ).create_index_request_kwargs("file-test")
    assert kwargs["rerank_mode"] == "custom"
    assert kwargs["rerank_instruct"] == "short instruction"


def test_invalid_rerank_mode() -> None:
    err = validate_rerank_config("bad", None)
    assert err and err["error_type"] == "invalid_rerank_mode"


def test_invalid_rerank_instruct() -> None:
    err = validate_rerank_config("qa", "not allowed")
    assert err and err["error_type"] == "invalid_rerank_instruct"
    err = validate_rerank_config(None, "not allowed")
    assert err and err["error_type"] == "invalid_rerank_instruct"


def test_cli_invalid_rerank_fails_fast() -> None:
    build = subprocess.run(
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
    assert build.returncode == 0, build.stderr + build.stdout
    result = subprocess.run(
        [
            sys.executable,
            "scripts/rag/bailian_small_kb_pilot.py",
            "--payload-jsonl",
            "/tmp/bailian_small_kb_payload.jsonl",
            "--questions",
            "evals/fixtures/rag_expected_questions.json",
            "--output-json",
            "/tmp/bailian_create_index_invalid_rerank.json",
            "--output-md",
            "/tmp/bailian_create_index_invalid_rerank.md",
            "--use-official-sdk",
            "--rerank-mode",
            "bad",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    text = Path("/tmp/bailian_create_index_invalid_rerank.json").read_text(encoding="utf-8")
    assert '"error_type": "invalid_rerank_mode"' in text


if __name__ == "__main__":
    raise SystemExit(main())
