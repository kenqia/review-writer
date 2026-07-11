#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_JSON = Path("/tmp/bailian_transport_matrix_test.json")


def main() -> int:
    env = os.environ.copy()
    env["HTTPS_PROXY"] = "http://proxy-secret.example:12345"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/rag/bailian_transport_matrix.py",
            "--endpoint",
            "bailian.cn-beijing.aliyuncs.com",
            "--category-id",
            "default",
            "--output-json",
            str(OUT_JSON),
            "--output-md",
            "/tmp/bailian_transport_matrix_test.md",
            "--strict",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads(OUT_JSON.read_text(encoding="utf-8"))
    assert report["overall_status"] == "dry_run"
    assert len(report["modes"]) == 3
    assert {item["mode"] for item in report["modes"]} == {"inherited_proxy", "no_proxy", "explicit_proxy"}
    assert report["upload_attempted"] is False
    assert report["knowledge_base_created"] is False
    assert all(item["network_attempted"] is False for item in report["modes"])
    text = OUT_JSON.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "proxy-secret.example" not in text
    assert "x-bailian-extra" not in lowered
    assert "authorization" not in lowered
    print("bailian_transport_matrix_safety_tests: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
