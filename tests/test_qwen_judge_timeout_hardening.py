#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JUDGE_CLI = ROOT / "scripts/llm_judges/qwen_review_quality_judge.py"
FIXTURE = ROOT / "tests/fixtures/judge/bad_title_alignment.md"
KEY_LIKE = re.compile(r"sk-[A-Za-z0-9_-]{12,}|fake-secret-key|DASHSCOPE_SECRET_VALUE")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review_writer.judges import JudgeTask, QwenJudge
from review_writer.judges.qwen_judge import build_judge_prompt


def main() -> int:
    tests = [
        test_dry_run_outputs_prompt_chars,
        test_compact_prompt_is_shorter,
        test_no_allow_network_never_attempts_network,
        test_timeout_classification_does_not_leak_key,
        test_timeout_and_max_tokens_written,
        test_task_limit_one,
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
    print(f"qwen judge timeout hardening tests passed: {len(tests)}")
    return 0


def test_dry_run_outputs_prompt_chars() -> None:
    report = run_cli_report("--dry-run", "--output-json", "/tmp/qwen_judge_harden_dry.json")
    result = report["results"][0]
    assert result["metadata"]["prompt_chars"] > 0
    assert result["metadata"]["network_attempts"] == 0


def test_compact_prompt_is_shorter() -> None:
    task = JudgeTask(
        task_id="compact",
        rule_id="CRQ007_REVIEW_TITLE_FIT",
        task_type="review_title_alignment",
        input_text="Allene ligand catalysis. " * 200,
        rubric="Judge title alignment. " * 50,
    )
    full = build_judge_prompt(task, compact=False)
    compact = build_judge_prompt(task, compact=True)
    assert len(compact) < len(full)


def test_no_allow_network_never_attempts_network() -> None:
    env = clean_env()
    env["DASHSCOPE_API_KEY"] = "sk-fake-secret-key-1234567890"
    env["BAILIAN_WORKSPACE_ID"] = "workspace-for-test"
    report = run_cli_report("--judge-mode", "qwen", "--output-json", "/tmp/qwen_judge_harden_no_allow.json", env=env)
    result = report["results"][0]
    assert result["status"] == "disabled"
    assert result["metadata"]["network"] == "not_used"
    assert result["metadata"]["network_attempts"] == 0


def test_timeout_classification_does_not_leak_key() -> None:
    result = QwenJudge(enabled=True, allow_network=True)._error(  # noqa: SLF001
        sample_task(),
        "client_timeout",
        "client request timed out",
        {"model": "qwen-plus", "region": "cn-beijing", "presence": {"DASHSCOPE_API_KEY": "SET"}, "workspace_id": "ws"},
        network="attempted_once",
        network_attempts=1,
        elapsed_seconds=90.0,
    ).to_dict()
    text = json.dumps(result, ensure_ascii=False)
    assert result["error_type"] == "client_timeout"
    assert result["metadata"]["error_category"] == "client_timeout"
    assert not KEY_LIKE.search(text)


def test_timeout_and_max_tokens_written() -> None:
    report = run_cli_report(
        "--dry-run",
        "--compact",
        "--timeout-seconds",
        "90",
        "--max-output-tokens",
        "128",
        "--output-json",
        "/tmp/qwen_judge_harden_params.json",
    )
    md = report["results"][0]["metadata"]
    assert md["timeout_seconds"] == 90.0
    assert md["max_output_tokens"] == 128
    assert md["compact_mode"] is True


def test_task_limit_one() -> None:
    report = run_cli_report("--dry-run", "--task-limit", "1", "--output-json", "/tmp/qwen_judge_harden_task_limit.json")
    assert len(report["results"]) == 1
    assert report["task_limit"] == 1


def run_cli_report(*args: str, env: dict[str, str] | None = None) -> dict:
    env = clean_env() if env is None else env
    output_path = _output_path(args)
    result = subprocess.run(
        [sys.executable, str(JUDGE_CLI), "--input-md", str(FIXTURE), *args],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode in {0, 1}, result.stdout + result.stderr
    assert output_path.exists(), result.stdout + result.stderr
    combined = result.stdout + result.stderr + output_path.read_text(encoding="utf-8")
    assert not KEY_LIKE.search(combined)
    return json.loads(output_path.read_text(encoding="utf-8"))


def _output_path(args: tuple[str, ...]) -> Path:
    if "--output-json" in args:
        return Path(args[args.index("--output-json") + 1])
    raise AssertionError("--output-json is required for test helper")


def sample_task() -> JudgeTask:
    return JudgeTask(
        task_id="timeout",
        rule_id="CRQ007_REVIEW_TITLE_FIT",
        task_type="review_title_alignment",
        input_text="Title/body excerpt",
        rubric="Judge alignment.",
    )


def clean_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in ("DASHSCOPE_API_KEY", "BAILIAN_WORKSPACE_ID", "BAILIAN_REGION", "BAILIAN_MODEL"):
        env.pop(key, None)
    return env


if __name__ == "__main__":
    raise SystemExit(main())
