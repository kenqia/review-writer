#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_JSON = Path("/tmp/bailian_endpoint_diagnostics_test.json")
OUT_MD = Path("/tmp/bailian_endpoint_diagnostics_test.md")


def main() -> int:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/rag/bailian_endpoint_diagnostics.py",
            "--endpoint",
            "localhost",
            "--port",
            "9",
            "--output-json",
            str(OUT_JSON),
            "--output-md",
            str(OUT_MD),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        env={**os.environ, "HTTP_PROXY": "http://proxy-secret.invalid:1234"},
    )
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads(OUT_JSON.read_text(encoding="utf-8"))
    assert report["endpoint"] == "localhost"
    assert "HTTP_PROXY" in report["proxy_env_set_names"]
    assert "proxy-secret" not in OUT_JSON.read_text(encoding="utf-8")
    assert "proxy-secret" not in OUT_MD.read_text(encoding="utf-8")
    assert "dns_status" in report
    assert "tcp_status" in report
    print("bailian_endpoint_diagnostics_tests: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
