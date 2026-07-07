#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts/validators/validate_review_quality.py"
JUDGE_CLI = ROOT / "scripts/llm_judges/qwen_review_quality_judge.py"
FIXTURES = ROOT / "tests/fixtures/judge"
KEY_LIKE = re.compile(r"sk-[A-Za-z0-9_-]{12,}|fake-secret-key|DASHSCOPE_SECRET_VALUE")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review_writer.judges import JudgeTask, OfflineJudge, QwenJudge


def main() -> int:
    tests = [
        test_offline_judge_deterministic,
        test_qwen_without_allow_network_disabled,
        test_qwen_missing_env_classified,
        test_output_does_not_contain_key_like_string,
        test_fixture_generates_judge_tasks,
        test_no_pdf_read_metadata,
        test_no_upload_metadata,
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
    print(f"qwen judge safety tests passed: {len(tests)}")
    return 0


def test_offline_judge_deterministic() -> None:
    task = sample_task()
    first = OfflineJudge().judge(task)
    second = OfflineJudge().judge(task)
    assert first.status == "ok"
    assert first.metadata["network"] == "not_used"
    assert first.metadata["deterministic_digest"] == second.metadata["deterministic_digest"]


def test_qwen_without_allow_network_disabled() -> None:
    result = QwenJudge(enabled=True, allow_network=False).judge(sample_task())
    assert result.status == "disabled"
    assert result.metadata["network"] == "not_used"


def test_qwen_missing_env_classified() -> None:
    result = run_with_clean_env(
        [sys.executable, str(JUDGE_CLI), "--judge-mode", "qwen", "--allow-network", "--output-json", "/tmp/qwen_judge_missing_env.json"]
    )
    assert result.returncode == 1
    report = json.loads(Path("/tmp/qwen_judge_missing_env.json").read_text(encoding="utf-8"))
    assert report["errors"][0]["error_type"] == "missing_env"
    assert report["errors"][0]["metadata"]["network"] == "not_used"


def test_output_does_not_contain_key_like_string() -> None:
    env = clean_env()
    env["DASHSCOPE_API_KEY"] = "sk-fake-secret-key-1234567890"
    result = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--draft",
            str(FIXTURES / "prompt_leakage_semantic.md"),
            "--judge-mode",
            "qwen",
            "--output-json",
            "/tmp/qwen_judge_no_leak_quality.json",
            "--judge-output-json",
            "/tmp/qwen_judge_no_leak.json",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    combined = (
        result.stdout
        + result.stderr
        + Path("/tmp/qwen_judge_no_leak_quality.json").read_text(encoding="utf-8")
        + Path("/tmp/qwen_judge_no_leak.json").read_text(encoding="utf-8")
    )
    assert not KEY_LIKE.search(combined)


def test_fixture_generates_judge_tasks() -> None:
    result = run_with_clean_env(
        [
            sys.executable,
            str(VALIDATOR),
            "--draft",
            str(FIXTURES / "bad_title_alignment.md"),
            "--judge-mode",
            "offline",
            "--output-json",
            "/tmp/qwen_judge_fixture_quality.json",
            "--judge-output-json",
            "/tmp/qwen_judge_fixture_report.json",
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr
    quality = json.loads(Path("/tmp/qwen_judge_fixture_quality.json").read_text(encoding="utf-8"))
    judge = json.loads(Path("/tmp/qwen_judge_fixture_report.json").read_text(encoding="utf-8"))
    task_types = {row["metadata"].get("task_type") for row in judge["results"]}
    assert quality["llm_judge_tasks"]
    assert "review_title_alignment" in task_types
    assert "section_title_alignment" in task_types


def test_no_pdf_read_metadata() -> None:
    report = run_validator_report("good_title_alignment.md")
    assert report["metadata"]["paper_body_read"] == "not_read"


def test_no_upload_metadata() -> None:
    report = run_validator_report("prompt_leakage_semantic.md")
    assert report["metadata"]["uploads"] == "not_used"
    assert report["metadata"]["knowledge_base_created"] == "not_used"
    assert report["metadata"]["image_api"] == "not_used"


def run_validator_report(fixture_name: str) -> dict:
    result = run_with_clean_env(
        [
            sys.executable,
            str(VALIDATOR),
            "--draft",
            str(FIXTURES / fixture_name),
            "--judge-mode",
            "offline",
            "--output-json",
            "/tmp/qwen_judge_quality_tmp.json",
            "--judge-output-json",
            "/tmp/qwen_judge_report_tmp.json",
        ]
    )
    assert result.returncode in {0, 1}, result.stdout + result.stderr
    return json.loads(Path("/tmp/qwen_judge_report_tmp.json").read_text(encoding="utf-8"))


def sample_task() -> JudgeTask:
    return JudgeTask(
        task_id="sample",
        rule_id="CRQ007_REVIEW_TITLE_FIT",
        task_type="review_title_alignment",
        input_text="Title: Allene ligands\nBody: allene ligand catalysis.",
        rubric="Judge alignment only.",
    )


def run_with_clean_env(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, env=clean_env(), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def clean_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in ("DASHSCOPE_API_KEY", "BAILIAN_WORKSPACE_ID", "BAILIAN_REGION", "BAILIAN_MODEL"):
        env.pop(key, None)
    return env


if __name__ == "__main__":
    raise SystemExit(main())
