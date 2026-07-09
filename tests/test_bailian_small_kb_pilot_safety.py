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
    )
    assert blocked.returncode == 0, blocked.stderr + blocked.stdout
    blocked_report = json.loads(Path("/tmp/bailian_small_kb_pilot_test_blocked.json").read_text(encoding="utf-8"))
    assert blocked_report["status"] in {"blocked_manual_console_required", "fail"}
    assert blocked_report["error_type"] in {"missing_dependency_or_api_contract", "missing_env"}
    assert blocked_report["safety"]["upload"] == "not_used"
    print("bailian_small_kb_pilot_safety_tests: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
