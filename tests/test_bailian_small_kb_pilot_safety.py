#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DRY_JSON = Path("/tmp/bailian_small_kb_pilot_test_dry.json")
DRY_MD = Path("/tmp/bailian_small_kb_pilot_test_dry.md")
SDK_DRY_JSON = Path("/tmp/bailian_small_kb_pilot_test_sdk_dry.json")


def main() -> int:
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
            str(DRY_JSON),
            "--output-md",
            str(DRY_MD),
            "--strict",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads(DRY_JSON.read_text(encoding="utf-8"))
    assert report["status"] == "dry_run"
    assert report["payload_status"] == "pass"
    assert report["safety"]["upload"] == "not_used"
    assert report["safety"]["knowledge_base"] == "not_created"
    assert Path(report["official_upload_md"]).exists()
    text = DRY_JSON.read_text(encoding="utf-8").lower() + DRY_MD.read_text(encoding="utf-8").lower()
    assert "sk-" not in text and "token=" not in text and "secret=" not in text
    sdk_dry = subprocess.run(
        [
            sys.executable,
            "scripts/rag/bailian_small_kb_pilot.py",
            "--payload-jsonl",
            "/tmp/bailian_small_kb_payload.jsonl",
            "--questions",
            "evals/fixtures/rag_expected_questions.json",
            "--output-json",
            str(SDK_DRY_JSON),
            "--output-md",
            "/tmp/bailian_small_kb_pilot_test_sdk_dry.md",
            "--use-official-sdk",
            "--strict",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert sdk_dry.returncode == 0, sdk_dry.stderr + sdk_dry.stdout
    sdk_dry_report = json.loads(SDK_DRY_JSON.read_text(encoding="utf-8"))
    assert sdk_dry_report["status"] == "dry_run"
    assert sdk_dry_report["official_sdk"]["enabled"] is True
    assert sdk_dry_report["config"]["category_type"] == "UNSTRUCTURED"
    assert sdk_dry_report["config"]["use_internal_endpoint"] is False
    assert sdk_dry_report["config"]["parser"] == "DASHSCOPE_DOCMIND"
    assert sdk_dry_report["parse_status"] is None
    assert sdk_dry_report["parse_error_present"] is False
    assert sdk_dry_report["manual_cleanup_required"] is False
    assert sdk_dry_report["skipped_because_upstream_parse_failed"] is False
    assert sdk_dry_report["safety"]["upload"] == "not_used"
    blocked = subprocess.run(
        [
            sys.executable,
            "scripts/rag/bailian_small_kb_pilot.py",
            "--payload-jsonl",
            "/tmp/bailian_small_kb_payload.jsonl",
            "--questions",
            "evals/fixtures/rag_expected_questions.json",
            "--output-json",
            "/tmp/bailian_small_kb_pilot_test_blocked.json",
            "--output-md",
            "/tmp/bailian_small_kb_pilot_test_blocked.md",
            "--allow-network",
            "--allow-upload",
            "--use-official-sdk",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        env=_without_bailian_env(),
    )
    assert blocked.returncode == 0, blocked.stderr + blocked.stdout
    blocked_report = json.loads(Path("/tmp/bailian_small_kb_pilot_test_blocked.json").read_text(encoding="utf-8"))
    assert blocked_report["status"] == "fail"
    assert blocked_report["error_type"] in {"missing_dependency_or_api_contract", "missing_env"}
    assert blocked_report["safety"]["upload"] == "not_used"
    cleanup_dry = subprocess.run(
        [
            sys.executable,
            "scripts/rag/bailian_small_kb_pilot.py",
            "--payload-jsonl",
            "/tmp/bailian_small_kb_payload.jsonl",
            "--questions",
            "evals/fixtures/rag_expected_questions.json",
            "--output-json",
            "/tmp/bailian_small_kb_pilot_test_cleanup_dry.json",
            "--output-md",
            "/tmp/bailian_small_kb_pilot_test_cleanup_dry.md",
            "--use-official-sdk",
            "--cleanup",
            "--cleanup-index-id",
            "fake-index-id",
            "--strict",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert cleanup_dry.returncode == 0, cleanup_dry.stderr + cleanup_dry.stdout
    cleanup_report = json.loads(Path("/tmp/bailian_small_kb_pilot_test_cleanup_dry.json").read_text(encoding="utf-8"))
    assert cleanup_report["status"] == "dry_run"
    assert cleanup_report["cleanup_requested"] is True
    assert cleanup_report["cleanup_index_id_provided"] is True
    print("bailian_small_kb_pilot_safety_tests: ok")
    return 0


def _without_bailian_env() -> dict[str, str]:
    import os

    env = os.environ.copy()
    for key in [
        "ALIBABA_CLOUD_ACCESS_KEY_ID",
        "ALIBABA_CLOUD_ACCESS_KEY_SECRET",
        "WORKSPACE_ID",
        "DASHSCOPE_API_KEY",
        "BAILIAN_WORKSPACE_ID",
    ]:
        env.pop(key, None)
    return env


if __name__ == "__main__":
    raise SystemExit(main())
