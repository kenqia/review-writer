#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DRY_JSON = Path("/tmp/bailian_minimal_lease_repro_test_dry.json")
MISSING_ENV_JSON = Path("/tmp/bailian_minimal_lease_repro_test_missing_env.json")
MISSING_CATEGORY_JSON = Path("/tmp/bailian_minimal_lease_repro_test_missing_category.json")
DISCOVERY_WITHOUT_RECOMMENDATION = Path("/tmp/bailian_category_discovery_without_recommendation.json")


def main() -> int:
    run_dry_repro()
    run_missing_env_repro()
    run_missing_category_repro()
    print("bailian_minimal_lease_repro_safety_tests: ok")
    return 0


def run_dry_repro() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/rag/bailian_minimal_lease_repro.py",
            "--endpoint",
            "bailian.cn-beijing.aliyuncs.com",
            "--category-id",
            "default",
            "--category-type",
            "UNSTRUCTURED",
            "--payload-md",
            "/tmp/bailian_small_kb_upload_payload.md",
            "--output-json",
            str(DRY_JSON),
            "--output-md",
            "/tmp/bailian_minimal_lease_repro_test_dry.md",
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
    assert report["category_type"] == "UNSTRUCTURED"
    assert report["file_name"] == "bailian_small_kb_upload_payload.md"
    assert report["lease_obtained"] is False
    assert report["upload_attempted"] is False
    assert report["knowledge_base_created"] is False
    text = DRY_JSON.read_text(encoding="utf-8").lower()
    assert "x-bailian-extra" not in text
    assert "authorization" not in text
    assert "sk-" not in text


def run_missing_env_repro() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/rag/bailian_minimal_lease_repro.py",
            "--endpoint",
            "bailian.cn-beijing.aliyuncs.com",
            "--category-id",
            "default",
            "--output-json",
            str(MISSING_ENV_JSON),
            "--output-md",
            "/tmp/bailian_minimal_lease_repro_test_missing_env.md",
            "--allow-network",
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


def run_missing_category_repro() -> None:
    DISCOVERY_WITHOUT_RECOMMENDATION.write_text(
        json.dumps({"status": "pass", "recommended_category_id": None}, ensure_ascii=False),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "scripts/rag/bailian_minimal_lease_repro.py",
            "--endpoint",
            "bailian.cn-beijing.aliyuncs.com",
            "--category-id-from",
            str(DISCOVERY_WITHOUT_RECOMMENDATION),
            "--output-json",
            str(MISSING_CATEGORY_JSON),
            "--output-md",
            "/tmp/bailian_minimal_lease_repro_test_missing_category.md",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads(MISSING_CATEGORY_JSON.read_text(encoding="utf-8"))
    assert report["status"] == "fail"
    assert report["error_type"] == "category_discovery_required"
    assert report["network_attempted"] is False
    assert report["upload_attempted"] is False
    assert report["knowledge_base_created"] is False


def without_bailian_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in [
        "ALIBABA_CLOUD_ACCESS_KEY_ID",
        "ALIBABA_CLOUD_ACCESS_KEY_SECRET",
        "WORKSPACE_ID",
    ]:
        env.pop(key, None)
    return env


if __name__ == "__main__":
    raise SystemExit(main())
