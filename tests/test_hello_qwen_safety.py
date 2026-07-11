#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts/hello_qwen_openai_compatible.py"
KEY_LIKE = re.compile(r"sk-[A-Za-z0-9_-]{12,}|fake-secret-key|DASHSCOPE_SECRET_VALUE")


def main() -> int:
    tests = [
        test_dry_run_no_network,
        test_missing_key_classified_missing_env,
        test_output_does_not_contain_key_like_string,
        test_without_allow_network_does_not_call,
        test_base_url_construction,
    ]
    failures: list[str] = []
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except AssertionError as exc:
            failures.append(f"{test.__name__}: {exc}")
            print(f"FAIL {test.__name__}: {exc}")
    if failures:
        return 1
    print(f"hello qwen safety tests passed: {len(tests)}")
    return 0


def test_dry_run_no_network() -> None:
    output_json = "/tmp/qwen_hello_test_dry.json"
    result = run_script(["--dry-run", "--output-json", output_json], env=clean_env())
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(Path(output_json).read_text(encoding="utf-8"))
    assert report["status"] == "dry_run"
    assert report["metadata"]["network"] == "not_used"
    assert report["metadata"]["files_uploaded"] == "not_used"


def test_missing_key_classified_missing_env() -> None:
    env = clean_env()
    env["BAILIAN_WORKSPACE_ID"] = "workspace-for-test"
    result = run_script(["--allow-network", "--output-json", "/tmp/qwen_hello_test_missing_env.json"], env=env)
    assert result.returncode == 1
    report = json.loads(Path("/tmp/qwen_hello_test_missing_env.json").read_text(encoding="utf-8"))
    assert report["error_type"] == "missing_env"
    assert report["metadata"]["network"] == "not_used"


def test_output_does_not_contain_key_like_string() -> None:
    env = clean_env()
    env["DASHSCOPE_API_KEY"] = "sk-fake-secret-key-1234567890"
    env["BAILIAN_WORKSPACE_ID"] = "workspace-for-test"
    result = run_script(
        ["--dry-run", "--output-json", "/tmp/qwen_hello_test_no_leak.json", "--output-md", "/tmp/qwen_hello_test_no_leak.md"],
        env=env,
    )
    assert result.returncode == 0
    combined = (
        result.stdout
        + result.stderr
        + Path("/tmp/qwen_hello_test_no_leak.json").read_text(encoding="utf-8")
        + Path("/tmp/qwen_hello_test_no_leak.md").read_text(encoding="utf-8")
    )
    assert not KEY_LIKE.search(combined)


def test_without_allow_network_does_not_call() -> None:
    env = clean_env()
    env["DASHSCOPE_API_KEY"] = "sk-fake-secret-key-1234567890"
    env["BAILIAN_WORKSPACE_ID"] = "workspace-for-test"
    result = run_script(["--output-json", "/tmp/qwen_hello_test_no_allow.json"], env=env)
    assert result.returncode == 0
    report = json.loads(Path("/tmp/qwen_hello_test_no_allow.json").read_text(encoding="utf-8"))
    assert report["metadata"]["network"] == "not_used"
    assert report["status"] == "dry_run"


def test_base_url_construction() -> None:
    module = load_script_module()
    assert (
        module.build_base_url("ws123", "cn-beijing")
        == "https://ws123.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    )
    assert (
        module.build_base_url("ws123", "ap-northeast-1")
        == "https://ws123.ap-northeast-1.maas.aliyuncs.com/compatible-mode/v1"
    )
    assert (
        module.build_base_url("ws123", "ap-southeast-1")
        == "https://ws123.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"
    )


def run_script(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def clean_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in ("DASHSCOPE_API_KEY", "BAILIAN_WORKSPACE_ID", "BAILIAN_REGION", "BAILIAN_MODEL"):
        env.pop(key, None)
    return env


def load_script_module():
    spec = importlib.util.spec_from_file_location("hello_qwen_openai_compatible", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    raise SystemExit(main())
