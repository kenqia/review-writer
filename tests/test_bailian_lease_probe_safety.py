#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
DRY_JSON = Path("/tmp/bailian_lease_probe_test_dry.json")
DRY_MD = Path("/tmp/bailian_lease_probe_test_dry.md")
MISSING_ENV_JSON = Path("/tmp/bailian_lease_probe_test_missing_env.json")


def main() -> int:
    build_payload()
    run_dry_probe()
    run_missing_env_probe()
    test_redaction()
    print("bailian_lease_probe_safety_tests: ok")
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
    assert Path("/tmp/bailian_small_kb_upload_payload.md").exists()


def run_dry_probe() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/rag/bailian_lease_probe.py",
            "--payload-md",
            "/tmp/bailian_small_kb_upload_payload.md",
            "--output-json",
            str(DRY_JSON),
            "--output-md",
            str(DRY_MD),
            "--endpoint",
            "bailian.cn-beijing.aliyuncs.com",
            "--region",
            "cn-beijing",
            "--category-id",
            "default",
            "--strict",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads(DRY_JSON.read_text(encoding="utf-8"))
    assert report["status"] == "dry_run"
    assert report["operation_name"] == "ApplyFileUploadLease"
    assert report["endpoint"] == "bailian.cn-beijing.aliyuncs.com"
    assert report["region"] == "cn-beijing"
    assert report["category_id"] == "default"
    assert report["lease_obtained"] is False
    assert report["upload_attempted"] is False
    assert report["knowledge_base_created"] is False
    text = (DRY_JSON.read_text(encoding="utf-8") + DRY_MD.read_text(encoding="utf-8")).lower()
    assert "x-bailian-extra" not in text
    assert "authorization" not in text
    assert "sk-" not in text


def run_missing_env_probe() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/rag/bailian_lease_probe.py",
            "--payload-md",
            "/tmp/bailian_small_kb_upload_payload.md",
            "--output-json",
            str(MISSING_ENV_JSON),
            "--output-md",
            "/tmp/bailian_lease_probe_test_missing_env.md",
            "--endpoint",
            "bailian.cn-beijing.aliyuncs.com",
            "--region",
            "cn-beijing",
            "--category-id",
            "default",
            "--allow-network",
            "--use-official-sdk",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        env=without_bailian_env(),
    )
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads(MISSING_ENV_JSON.read_text(encoding="utf-8"))
    assert report["status"] == "fail"
    assert report["error_type"] in {"missing_env", "missing_dependency_or_api_contract"}
    assert report["network_attempted"] is False
    assert report["upload_attempted"] is False
    assert report["knowledge_base_created"] is False
    assert "recommended_fix" in report


def test_redaction() -> None:
    from review_writer.retrieval.bailian_official_client import redact_sensitive

    sample = "access_key=SHOULD_NOT_APPEAR secret=SHOULD_NOT_APPEAR https://example.invalid/path?Signature=abc"
    redacted = redact_sensitive(sample)
    assert "SHOULD_NOT_APPEAR" not in redacted
    assert "https://example.invalid" not in redacted


def without_bailian_env() -> dict[str, str]:
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
