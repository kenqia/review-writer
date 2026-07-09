#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DRY_JSON = Path("/tmp/bailian_small_kb_pilot_test_dry.json")
DRY_MD = Path("/tmp/bailian_small_kb_pilot_test_dry.md")


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
    text = DRY_JSON.read_text(encoding="utf-8").lower() + DRY_MD.read_text(encoding="utf-8").lower()
    assert "sk-" not in text and "token:" not in text and "secret:" not in text
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
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert blocked.returncode == 0, blocked.stderr + blocked.stdout
    blocked_report = json.loads(Path("/tmp/bailian_small_kb_pilot_test_blocked.json").read_text(encoding="utf-8"))
    assert blocked_report["status"] in {"blocked_manual_console_required", "fail"}
    assert blocked_report["safety"]["upload"] == "not_used"
    print("bailian_small_kb_pilot_safety_tests: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
