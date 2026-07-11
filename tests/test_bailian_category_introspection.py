#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_JSON = Path("/tmp/bailian_category_introspection_test.json")


def main() -> int:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/rag/bailian_category_introspection.py",
            "--output-json",
            str(OUT_JSON),
            "--output-md",
            "/tmp/bailian_category_introspection_test.md",
            "--strict",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads(OUT_JSON.read_text(encoding="utf-8"))
    assert report["status"] in {"pass", "warn"}
    assert "has_list_category_request" in report
    assert "has_list_category_with_options" in report
    assert "has_create_category_request" in report
    text = OUT_JSON.read_text(encoding="utf-8").lower()
    assert "access_key_secret" not in text
    assert "authorization" not in text
    print("bailian_category_introspection_tests: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
