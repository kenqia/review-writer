#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
JSONL = Path("/tmp/bailian_small_kb_payload.jsonl")
MD = Path("/tmp/bailian_small_kb_payload.md")
MANIFEST = Path("/tmp/bailian_small_kb_payload_manifest.json")


def main() -> int:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/rag/build_bailian_small_kb_payload.py",
            "--clean-root",
            "demo_projects/clean_3paper_allene_review",
            "--output-jsonl",
            str(JSONL),
            "--output-md",
            str(MD),
            "--output-manifest",
            str(MANIFEST),
            "--strict",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    rows = [json.loads(line) for line in JSONL.read_text(encoding="utf-8").splitlines() if line.strip()]
    report = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert report["status"] == "pass", report
    assert len(rows) == 3
    for row in rows:
        assert row["needs_human_review"] is True
        assert row["trusted_for_scientific_quality"] is False
        assert row["upload_scope"] == "small_kb_pilot"
        assert len(row["compact_text"]) <= 1200
    text = JSONL.read_text(encoding="utf-8").lower()
    forbidden = [".pdf", ".png", ".jpg", ".jpeg", ".webp", "/home/", "/mnt/", "api_key", "token:", "secret:"]
    assert not any(token in text for token in forbidden), text
    print("bailian_small_kb_payload_tests: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

