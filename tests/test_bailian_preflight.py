#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_JSON = Path("/tmp/bailian_rag_preflight_test.json")
REPORT_MD = Path("/tmp/bailian_rag_preflight_test.md")
MANIFEST_JSON = Path("/tmp/bailian_no_upload_corpus_manifest.json")


def main() -> int:
    cmd = [
        sys.executable,
        "scripts/rag/bailian_preflight.py",
        "--clean-root",
        "demo_projects/clean_3paper_allene_review",
        "--config",
        "rag/bailian/preflight_config.example.yaml",
        "--output-json",
        str(REPORT_JSON),
        "--output-md",
        str(REPORT_MD),
        "--strict",
    ]
    result = subprocess.run(cmd, cwd=REPO_ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST_JSON.read_text(encoding="utf-8"))
    assert report["status"] == "pass", report
    assert report["selected_count"] == 3
    assert len(report["allowed_items"]) == 3
    assert report["blocked_items"] == []
    assert manifest["no_upload"] is True
    assert manifest["api_used"] is False
    assert manifest["knowledge_base_created"] is False
    assert manifest["upload_status"] == "not_uploaded"
    text = MANIFEST_JSON.read_text(encoding="utf-8").lower()
    forbidden = [".pdf", ".png", ".jpg", ".jpeg", ".webp", "raw_mineru_markdown", "full_pdf_text"]
    assert not any(token in text for token in forbidden), text
    assert "/home/" not in text and "/mnt/" not in text and "c:\\users\\" not in text
    assert "api_key" not in text and "token:" not in text and "sk-" not in text
    p403 = next(item for item in manifest["items"] if item["paper_id"] == "P403")
    assert "warning" in p403 and p403["warning"]
    for item in manifest["items"]:
        assert item["upload_status"] == "not_uploaded"
        assert item["api_used"] is False
        assert item["knowledge_base_created"] is False
        assert item["needs_human_review"] is True
        assert item["trusted_for_scientific_quality"] is False
    print("bailian_preflight_tests: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

