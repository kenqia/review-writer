#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_JSON = Path("/tmp/bailian_sdk_env_check_test.json")
REPORT_MD = Path("/tmp/bailian_sdk_env_check_test.md")


def main() -> int:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/rag/check_bailian_sdk_env.py",
            "--output-json",
            str(REPORT_JSON),
            "--output-md",
            str(REPORT_MD),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
    assert report["status"] in {"pass", "warn"}
    for module in [
        "alibabacloud_bailian20231229",
        "alibabacloud_tea_openapi",
        "alibabacloud_tea_util",
        "requests",
    ]:
        assert module in report["modules"]
    for env_name in ["ALIBABA_CLOUD_ACCESS_KEY_ID", "ALIBABA_CLOUD_ACCESS_KEY_SECRET", "WORKSPACE_ID"]:
        assert report["env"][env_name] in {"SET", "MISSING"}
    assert report["safety"]["network"] == "not_used"
    assert report["safety"]["key_values_printed"] == "no"
    combined = REPORT_JSON.read_text(encoding="utf-8").lower() + REPORT_MD.read_text(encoding="utf-8").lower()
    assert "ltai" not in combined and "sk-" not in combined and "token=" not in combined
    print("bailian_sdk_env_check_tests: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

