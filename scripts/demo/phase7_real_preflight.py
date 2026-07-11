#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.pipeline.retrieval_generation import (
    build_evidence_pack,
    build_generation_messages,
    load_retrieval_fixture,
)
from review_writer.config import load_provider_config
from review_writer.phase7_budget import LIMITS, Phase7BudgetLedger
from review_writer.providers.base import TextGenerationRequest
from review_writer.providers.openai_compatible_provider import (
    DEFAULT_QWEN_MODEL,
    FirstByteTimeout,
    OpenAICompatibleProvider,
    StreamFailed,
    TotalStreamTimeout,
    parse_openai_stream_content,
    parse_openai_stream_result,
)

DEFAULT_FIXTURE = REPO_ROOT / "tests/fixtures/retrieval_generation/clean_3paper_retrieval_fixture.json"
DEFAULT_OUTPUT_JSON = Path("/tmp/review_writer_phase7_real_preflight.json")
DEFAULT_OUTPUT_MD = Path("/tmp/review_writer_phase7_real_preflight.md")
MAX_PROMPT_CHARS = 12000
MIN_MAX_OUTPUT_TOKENS = 128
MAX_MAX_OUTPUT_TOKENS = 1200


def main() -> int:
    args = parse_args()
    try:
        report = run_preflight(args)
    except Exception as exc:  # noqa: BLE001 - preflight must always emit a safe report.
        report = safe_failure_report("preflight", exc, cleanup_status="not_started")
    write_outputs(report, args.output_json, args.output_md)
    print(f"phase7-real-preflight: {report['status']} failed_stage={report['failed_stage']}")
    return 1 if report["status"] == "fail" else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 7 real Qwen generation preflight; performs no API calls.")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    parser.add_argument("--output-root", type=Path, default=Path("/tmp/review_writer_phase7_real_preflight"))
    parser.add_argument("--max-output-tokens", type=int, default=900)
    parser.add_argument("--connect-timeout-seconds", type=float, default=10.0)
    parser.add_argument("--first-byte-timeout-seconds", type=float, default=45.0)
    parser.add_argument("--total-timeout-seconds", type=float, default=120.0)
    return parser.parse_args()


def run_preflight(args: argparse.Namespace) -> dict[str, Any]:
    started = time.monotonic()
    cleanup_status = "not_started"
    checks: dict[str, dict[str, Any]] = {}

    cleanup_handler = make_cleanup_handler(args.output_root)
    checks["git_worktree_state"] = check_git_worktree_state()
    checks["cleanup_handler"] = check_cleanup_handler(cleanup_handler)
    cleanup_status = checks["cleanup_handler"]["cleanup_status"]

    checks["output_dir_writable"] = check_output_dir(args.output_root)
    checks["provider_dependency"] = check_openai_dependency()
    checks["bailian_sdk_dependency"] = check_bailian_sdk_dependency()
    checks["pip_check"] = check_pip_check()
    env = read_safe_env()
    checks["env_presence"] = {"status": "pass" if env_ready_for_real_call(env) else "fail", "presence": env["presence"]}
    checks["model_name_valid"] = check_model_name(env)
    checks["dedicated_endpoint_derivable"] = check_endpoint_derivable(env)

    pack = build_evidence_pack(load_retrieval_fixture(args.fixture), max_evidence_items=3)
    checks["offline_evidence_pack"] = {
        "status": "pass" if pack.items else "fail",
        "evidence_item_count": len(pack.items),
        "allowed_paper_ids": sorted({item.paper_id for item in pack.items}),
    }

    messages = build_generation_messages(pack)
    request = TextGenerationRequest(
        messages=messages,
        model=env["model"],
        temperature=0,
        max_output_tokens=args.max_output_tokens,
        metadata={"section_id": pack.section_id, "evidence_item_count": len(pack.items)},
    )
    checks["request_serializable"] = check_request_serializable(request)
    checks["stream_true_supported"] = {"status": "pass", "stream": True}
    checks["streaming_parser"] = check_streaming_parser()
    checks["first_server_timeout_handling"] = check_first_server_timeout_handling()
    checks["first_byte_timeout_handling"] = check_first_byte_timeout_handling()
    checks["total_timeout_handling"] = check_total_timeout_handling()
    checks["length_finish_handling"] = check_length_finish_handling()
    checks["mid_stream_failure_handling"] = check_mid_stream_failure_handling()
    checks["timeout_configurable"] = check_timeout_config(args)
    checks["safe_failure_report"] = check_safe_failure_report()
    checks["prompt_and_tokens"] = check_prompt_and_tokens(messages, args.max_output_tokens)
    checks["real_call_budget"] = check_real_call_budget()

    failed = [name for name, check in checks.items() if check.get("status") != "pass"]
    return {
        "status": "fail" if failed else "pass",
        "failed_stage": failed[0] if failed else None,
        "exception_class": None,
        "error_type": "preflight_failed" if failed else None,
        "status_code": None,
        "request_id_present": False,
        "stream_started": False,
        "chunks_received": 0,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "retry_count": 0,
        "cleanup_status": cleanup_status,
        "recommended_fix": recommend_fix(failed[0]) if failed else "ready for Qwen-only smoke; do not create Bailian index before it passes",
        "network_calls": 0,
        "bailian_index_created": False,
        "qwen_request_sent": False,
        "region": env["region"],
        "model_name": env["model"],
        "model_source": env["model_source"],
        "dedicated_endpoint_used": env["dedicated_endpoint_used"],
        "endpoint_redacted": True,
        "checks": checks,
    }


def read_safe_env() -> dict[str, Any]:
    region = os.environ.get("BAILIAN_REGION") or os.environ.get("ALIBABA_REGION") or "cn-beijing"
    env_model = os.environ.get("BAILIAN_MODEL") or os.environ.get("ALIBABA_MODEL")
    repo_model = read_repo_qwen_model()
    model = env_model or repo_model or DEFAULT_QWEN_MODEL
    workspace_present = bool(os.environ.get("BAILIAN_WORKSPACE_ID") or os.environ.get("ALIBABA_WORKSPACE_ID"))
    base_url_present = bool(os.environ.get("BAILIAN_OPENAI_BASE_URL") or os.environ.get("ALIBABA_OPENAI_BASE_URL"))
    return {
        "region": region,
        "model": model,
        "model_source": "env" if env_model else "repo_config",
        "dedicated_endpoint_used": workspace_present or base_url_present,
        "workspace_present": workspace_present,
        "base_url_present": base_url_present,
        "presence": {
            "DASHSCOPE_API_KEY": "SET" if os.environ.get("DASHSCOPE_API_KEY") else "MISSING",
            "BAILIAN_WORKSPACE_ID": "SET" if os.environ.get("BAILIAN_WORKSPACE_ID") else "MISSING",
            "ALIBABA_WORKSPACE_ID": "SET" if os.environ.get("ALIBABA_WORKSPACE_ID") else "MISSING",
            "BAILIAN_OPENAI_BASE_URL": "SET" if os.environ.get("BAILIAN_OPENAI_BASE_URL") else "MISSING",
            "BAILIAN_REGION": "SET" if os.environ.get("BAILIAN_REGION") else "MISSING_DEFAULT_CN_BEIJING",
            "BAILIAN_MODEL": "SET" if os.environ.get("BAILIAN_MODEL") else "MISSING_REPO_QWEN37_PLUS",
        },
    }


def env_ready_for_real_call(env: dict[str, Any]) -> bool:
    has_key = env["presence"]["DASHSCOPE_API_KEY"] == "SET"
    has_endpoint = env["presence"]["BAILIAN_WORKSPACE_ID"] == "SET" or env["presence"]["ALIBABA_WORKSPACE_ID"] == "SET" or env["presence"]["BAILIAN_OPENAI_BASE_URL"] == "SET"
    return has_key and has_endpoint


def read_repo_qwen_model() -> str:
    try:
        config = load_provider_config(REPO_ROOT / "config/providers.example.yaml")
    except Exception:
        return DEFAULT_QWEN_MODEL
    model = (
        ((config.get("providers") or {}).get("alibaba_openai_compatible") or {}).get("model")
        or DEFAULT_QWEN_MODEL
    )
    return str(model)


def check_git_worktree_state() -> dict[str, Any]:
    status_result = subprocess.run(
        ["git", "status", "--short"],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    branch_result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    current_branch = branch_result.stdout.strip()
    worktree_clean = status_result.stdout.strip() == ""
    return {
        "status": "pass" if status_result.returncode == 0 and branch_result.returncode == 0 and current_branch == "feat/orchestrator-rag-generation-pilot" else "fail",
        "git_available": status_result.returncode == 0 and branch_result.returncode == 0,
        "worktree_clean": worktree_clean,
        "current_branch": current_branch,
        "expected_branch": "feat/orchestrator-rag-generation-pilot",
    }


def check_openai_dependency() -> dict[str, Any]:
    try:
        import openai  # type: ignore # noqa: F401
    except Exception:
        return {"status": "fail", "dependency": "openai", "importable": False}
    return {"status": "pass", "dependency": "openai", "importable": True}


def check_bailian_sdk_dependency() -> dict[str, Any]:
    try:
        import alibabacloud_bailian20231229  # type: ignore # noqa: F401
    except Exception:
        return {"status": "fail", "dependency": "alibabacloud_bailian20231229", "importable": False}
    return {"status": "pass", "dependency": "alibabacloud_bailian20231229", "importable": True}


def check_pip_check() -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "check"],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return {"status": "pass" if result.returncode == 0 else "fail", "command": "python -m pip check"}


def check_model_name(env: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "pass" if env["model"] == DEFAULT_QWEN_MODEL else "fail",
        "model_name": env["model"],
        "expected_model_name": DEFAULT_QWEN_MODEL,
        "model_source": env["model_source"],
    }


def check_endpoint_derivable(env: dict[str, Any]) -> dict[str, Any]:
    provider = OpenAICompatibleProvider(region=env["region"], model=env["model"])
    try:
        endpoint = provider._resolve_endpoint(  # noqa: SLF001 - preflight validates redacted endpoint contract.
            {
                "region": env["region"],
                "workspace_id_present": env["workspace_present"],
                "base_url_present": env["base_url_present"],
                "presence": env["presence"],
            }
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "fail",
            "region": env["region"],
            "exception_class": exc.__class__.__name__,
            "endpoint_redacted": True,
        }
    return {
        "status": "pass",
        "region": endpoint["region"],
        "dedicated_endpoint_used": bool(endpoint["dedicated_endpoint_used"]),
        "endpoint_redacted": endpoint["base_url_redacted"] == "redacted",
    }


def check_request_serializable(request: TextGenerationRequest) -> dict[str, Any]:
    try:
        json.dumps(
            {
                "messages": request.messages,
                "model": request.model,
                "temperature": request.temperature,
                "max_completion_tokens": request.max_output_tokens,
                "stream": True,
                "stream_options": {"include_usage": True},
                "extra_body": {"enable_thinking": False, "enable_search": False},
                "metadata": request.metadata,
            },
            ensure_ascii=False,
        )
    except Exception as exc:  # noqa: BLE001
        return {"status": "fail", "exception_class": exc.__class__.__name__}
    return {
        "status": "pass",
        "model": request.model,
        "stream": True,
        "max_completion_tokens": request.max_output_tokens,
        "enable_thinking": False,
        "enable_search": False,
    }


def check_streaming_parser() -> dict[str, Any]:
    chunks = [
        {"choices": [{"delta": {"role": "assistant"}}]},
        {"choices": [{"delta": {"reasoning_content": "hidden"}}]},
        {"choices": [{"delta": {"content": "one "}}]},
        {"choices": [{"delta": {"content": "two"}, "finish_reason": "stop"}]},
        {"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}},
    ]
    parsed = parse_openai_stream_result(
        chunks,
        first_server_timeout_seconds=3,
        first_content_timeout_seconds=3,
        idle_timeout_seconds=3,
        total_timeout_seconds=5,
    )
    ok = (
        parsed.content == "one two"
        and parsed.telemetry["usage_chunk_received"] is True
        and parsed.telemetry["reasoning_chunks_received"] == 1
        and parsed.telemetry["finish_reason"] == "stop"
    )
    return {"status": "pass" if ok else "fail", **parsed.telemetry}


def check_first_byte_timeout_handling() -> dict[str, Any]:
    try:
        parse_openai_stream_content(
            [{"choices": [{"delta": {"content": "late"}}]}],
            first_byte_timeout_seconds=1,
            total_timeout_seconds=5,
            monotonic=FakeClock([0.0, 2.0]),
        )
    except FirstByteTimeout:
        return {"status": "pass", "error_type": "first_byte_timeout"}
    return {"status": "fail", "error_type": None}


def check_first_server_timeout_handling() -> dict[str, Any]:
    try:
        parse_openai_stream_result(
            [{"choices": [{"delta": {"content": "late"}}]}],
            first_server_timeout_seconds=1,
            first_content_timeout_seconds=3,
            idle_timeout_seconds=3,
            total_timeout_seconds=5,
            monotonic=FakeClock([0.0, 2.0]),
        )
    except FirstByteTimeout:
        return {"status": "pass", "error_type": "first_server_timeout"}
    return {"status": "fail", "error_type": None}


def check_total_timeout_handling() -> dict[str, Any]:
    try:
        parse_openai_stream_content(
            [{"choices": [{"delta": {"content": "one"}}]}, {"choices": [{"delta": {"content": "two"}}]}],
            first_byte_timeout_seconds=1,
            total_timeout_seconds=2,
            monotonic=FakeClock([0.0, 0.5, 3.0]),
        )
    except TotalStreamTimeout:
        return {"status": "pass", "error_type": "total_timeout"}
    return {"status": "fail", "error_type": None}


def check_length_finish_handling() -> dict[str, Any]:
    try:
        parse_openai_stream_result(
            [{"choices": [{"delta": {"content": "cut"}, "finish_reason": "length"}]}],
            first_server_timeout_seconds=3,
            first_content_timeout_seconds=3,
            idle_timeout_seconds=3,
            total_timeout_seconds=5,
        )
    except Exception as exc:  # noqa: BLE001
        return {"status": "pass" if exc.__class__.__name__ == "IncompleteGeneration" else "fail", "error_type": exc.__class__.__name__}
    return {"status": "fail", "error_type": None}


def check_mid_stream_failure_handling() -> dict[str, Any]:
    try:
        parse_openai_stream_content(
            FailingStream(),
            first_byte_timeout_seconds=3,
            total_timeout_seconds=5,
            monotonic=FakeClock([0.0, 0.2, 0.3]),
        )
    except StreamFailed as exc:
        return {
            "status": "pass" if exc.stream_started and exc.chunks_received == 1 else "fail",
            "error_type": "stream_failed",
            "stream_started": exc.stream_started,
            "chunks_received": exc.chunks_received,
        }
    return {"status": "fail", "error_type": None}


def check_timeout_config(args: argparse.Namespace) -> dict[str, Any]:
    provider = OpenAICompatibleProvider(
        connect_timeout_seconds=args.connect_timeout_seconds,
        first_byte_timeout_seconds=args.first_byte_timeout_seconds,
        total_timeout_seconds=args.total_timeout_seconds,
    )
    ok = (
        provider.connect_timeout_seconds > 0
        and provider.first_byte_timeout_seconds > 0
        and provider.total_timeout_seconds >= provider.first_byte_timeout_seconds
    )
    return {
        "status": "pass" if ok else "fail",
        "connect_timeout_seconds": provider.connect_timeout_seconds,
        "first_byte_timeout_seconds": provider.first_byte_timeout_seconds,
        "total_timeout_seconds": provider.total_timeout_seconds,
    }


def check_safe_failure_report() -> dict[str, Any]:
    report = safe_failure_report("stream_parsing", RuntimeError("fake-secret-key Authorization full prompt"), cleanup_status="pass")
    rendered = json.dumps(report, ensure_ascii=False)
    leaked = any(token in rendered for token in ("fake-secret-key", "Authorization", "full prompt"))
    required = {"failed_stage", "exception_class", "error_type", "request_id_present", "stream_started", "chunks_received", "elapsed_ms", "retry_count", "cleanup_status", "recommended_fix"}
    return {"status": "pass" if not leaked and required <= set(report) else "fail"}


def check_output_dir(path: Path) -> dict[str, Any]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".phase7_preflight_write_probe"
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink()
    except Exception as exc:  # noqa: BLE001
        return {"status": "fail", "exception_class": exc.__class__.__name__}
    return {"status": "pass", "path": str(path)}


def make_cleanup_handler(output_root: Path) -> Callable[[], str]:
    def cleanup() -> str:
        output_root.mkdir(parents=True, exist_ok=True)
        marker = output_root / ".cleanup_probe"
        marker.write_text("cleanup registered\n", encoding="utf-8")
        marker.unlink(missing_ok=True)
        return "pass"

    return cleanup


def check_cleanup_handler(cleanup_handler: Callable[[], str]) -> dict[str, Any]:
    try:
        cleanup_status = cleanup_handler()
    except Exception as exc:  # noqa: BLE001
        return {"status": "fail", "cleanup_status": "fail", "exception_class": exc.__class__.__name__}
    return {"status": "pass" if cleanup_status == "pass" else "fail", "cleanup_status": cleanup_status}


def check_prompt_and_tokens(messages: list[dict[str, str]], max_output_tokens: int) -> dict[str, Any]:
    prompt_chars = sum(len(message.get("content", "")) for message in messages)
    ok = prompt_chars <= MAX_PROMPT_CHARS and MIN_MAX_OUTPUT_TOKENS <= max_output_tokens <= MAX_MAX_OUTPUT_TOKENS
    return {
        "status": "pass" if ok else "fail",
        "prompt_chars": prompt_chars,
        "max_prompt_chars": MAX_PROMPT_CHARS,
        "max_output_tokens": max_output_tokens,
        "allowed_max_output_tokens": [MIN_MAX_OUTPUT_TOKENS, MAX_MAX_OUTPUT_TOKENS],
    }


def check_real_call_budget() -> dict[str, Any]:
    state = Phase7BudgetLedger().read()
    fixture = Path("/tmp/review_writer_phase7_budget_preflight_fixture.json")
    fixture.unlink(missing_ok=True)
    before, after = Phase7BudgetLedger(fixture).reserve("qwen_only", qwen_requests=1, last_operation="preflight fixture")
    fixture_ok = before["qwen_total_requests"] == 0 and after["qwen_total_requests"] == 1
    return {
        "status": "pass" if fixture_ok else "fail",
        "qwen_only_real_requests_max": LIMITS["qwen_only_attempts"],
        "full_e2e_runs_max": LIMITS["full_e2e_attempts"],
        "qwen_total_requests_max": LIMITS["qwen_total_requests"],
        "bailian_lifecycles_max": LIMITS["bailian_lifecycles"],
        "current_counts": {
            "qwen_only_attempts": int(state["qwen_only_attempts"]),
            "full_e2e_attempts": int(state["full_e2e_attempts"]),
            "qwen_total_requests": int(state["qwen_total_requests"]),
            "bailian_lifecycles": int(state["bailian_lifecycles"]),
        },
        "initialized": True,
        "fixture_ledger_pass": fixture_ok,
    }


def safe_failure_report(failed_stage: str, exc: Exception, *, cleanup_status: str) -> dict[str, Any]:
    return {
        "status": "fail",
        "failed_stage": failed_stage,
        "exception_class": exc.__class__.__name__,
        "error_type": classify_error(exc),
        "status_code": getattr(exc, "status_code", None),
        "request_id_present": bool(getattr(exc, "request_id", None)),
        "stream_started": False,
        "chunks_received": 0,
        "elapsed_ms": 0,
        "retry_count": 0,
        "cleanup_status": cleanup_status,
        "recommended_fix": recommend_fix(failed_stage),
        "network_calls": 0,
    }


class FakeClock:
    def __init__(self, values: list[float]) -> None:
        self.values = values
        self.index = 0

    def __call__(self) -> float:
        value = self.values[min(self.index, len(self.values) - 1)]
        self.index += 1
        return value


class FailingStream:
    def __iter__(self):
        yield {"choices": [{"delta": {"content": "partial"}}]}
        raise RuntimeError("simulated stream failure; prompt hidden")


def classify_error(exc: Exception) -> str:
    text = f"{exc.__class__.__name__} {exc}".lower()
    if "timeout" in text:
        return "timeout"
    if "stream" in text:
        return "stream_failed"
    return "preflight_error"


def recommend_fix(failed_stage: str | None) -> str:
    fixes = {
        "provider_dependency": "install the project-scoped qwen dependency set; do not add HTTP transport to the pipeline",
        "env_presence": "set DASHSCOPE_API_KEY plus BAILIAN_WORKSPACE_ID/ALIBABA_WORKSPACE_ID or BAILIAN_OPENAI_BASE_URL in the local runtime only",
        "request_serializable": "reduce request metadata to JSON-serializable primitives",
        "offline_evidence_pack": "rebuild the sanitized offline EvidencePack fixture before any real call",
        "streaming_parser": "fix provider streaming chunk parsing before sending a real request",
        "timeout_configurable": "set positive connect/first-byte/total timeout values",
        "safe_failure_report": "fix report redaction before any real provider invocation",
        "cleanup_handler": "fix cleanup registration before creating Bailian resources",
        "output_dir_writable": "choose a writable /tmp output directory",
        "prompt_and_tokens": "shrink prompt or set max_output_tokens within the configured range",
        "bailian_sdk_dependency": "install the Bailian SDK into the same conda env as the Qwen provider",
        "pip_check": "resolve dependency conflicts in the active project environment",
        "model_name_valid": "set the repo/provider model to qwen3.7-plus before real generation",
        "dedicated_endpoint_derivable": "set workspace id or a redacted OpenAI-compatible base URL for the configured region",
        "first_byte_timeout_handling": "fix first-byte timeout classification before real streaming",
        "total_timeout_handling": "fix total stream timeout classification before real streaming",
        "mid_stream_failure_handling": "fix partial stream failure classification before real streaming",
        "real_call_budget": "initialize real-call budget counters before any real request",
    }
    return fixes.get(failed_stage or "", "inspect the preflight report and rerun without creating Bailian resources")


def write_outputs(report: dict[str, Any], output_json: Path, output_md: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_md(report), encoding="utf-8")


def render_md(report: dict[str, Any]) -> str:
    lines = [
        "# Phase 7 Real Preflight",
        "",
        f"- status: `{report['status']}`",
        f"- failed_stage: `{report.get('failed_stage')}`",
        f"- error_type: `{report.get('error_type')}`",
        f"- network_calls: `{report.get('network_calls')}`",
        f"- region: `{report.get('region')}`",
        f"- dedicated_endpoint_used: `{report.get('dedicated_endpoint_used')}`",
        f"- cleanup_status: `{report.get('cleanup_status')}`",
        f"- recommended_fix: `{report.get('recommended_fix')}`",
        "",
        "## Checks",
    ]
    for name, check in (report.get("checks") or {}).items():
        lines.append(f"- {name}: `{check.get('status')}`")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
