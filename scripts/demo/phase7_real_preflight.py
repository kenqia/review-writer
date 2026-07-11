#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
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
from review_writer.providers.base import TextGenerationRequest
from review_writer.providers.openai_compatible_provider import OpenAICompatibleProvider, parse_openai_stream_content

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
    checks["cleanup_handler"] = check_cleanup_handler(cleanup_handler)
    cleanup_status = checks["cleanup_handler"]["cleanup_status"]

    checks["output_dir_writable"] = check_output_dir(args.output_root)
    checks["provider_dependency"] = check_openai_dependency()
    env = read_safe_env()
    checks["env_presence"] = {"status": "pass" if env_ready_for_real_call(env) else "fail", "presence": env["presence"]}

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
    checks["streaming_parser"] = check_streaming_parser()
    checks["timeout_configurable"] = check_timeout_config(args)
    checks["safe_failure_report"] = check_safe_failure_report()
    checks["prompt_and_tokens"] = check_prompt_and_tokens(messages, args.max_output_tokens)

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
        "dedicated_endpoint_used": env["dedicated_endpoint_used"],
        "checks": checks,
    }


def read_safe_env() -> dict[str, Any]:
    region = os.environ.get("BAILIAN_REGION") or os.environ.get("ALIBABA_REGION") or "cn-beijing"
    model = os.environ.get("BAILIAN_MODEL") or os.environ.get("ALIBABA_MODEL") or "qwen-plus"
    workspace_present = bool(os.environ.get("BAILIAN_WORKSPACE_ID") or os.environ.get("ALIBABA_WORKSPACE_ID"))
    base_url_present = bool(os.environ.get("BAILIAN_OPENAI_BASE_URL") or os.environ.get("ALIBABA_OPENAI_BASE_URL"))
    return {
        "region": region,
        "model": model,
        "dedicated_endpoint_used": workspace_present or base_url_present,
        "presence": {
            "DASHSCOPE_API_KEY": "SET" if os.environ.get("DASHSCOPE_API_KEY") else "MISSING",
            "BAILIAN_WORKSPACE_ID": "SET" if os.environ.get("BAILIAN_WORKSPACE_ID") else "MISSING",
            "ALIBABA_WORKSPACE_ID": "SET" if os.environ.get("ALIBABA_WORKSPACE_ID") else "MISSING",
            "BAILIAN_OPENAI_BASE_URL": "SET" if os.environ.get("BAILIAN_OPENAI_BASE_URL") else "MISSING",
            "BAILIAN_REGION": "SET" if os.environ.get("BAILIAN_REGION") else "MISSING_DEFAULT_CN_BEIJING",
            "BAILIAN_MODEL": "SET" if os.environ.get("BAILIAN_MODEL") else "MISSING_DEFAULT_QWEN_PLUS",
        },
    }


def env_ready_for_real_call(env: dict[str, Any]) -> bool:
    has_key = env["presence"]["DASHSCOPE_API_KEY"] == "SET"
    has_endpoint = env["presence"]["BAILIAN_WORKSPACE_ID"] == "SET" or env["presence"]["ALIBABA_WORKSPACE_ID"] == "SET" or env["presence"]["BAILIAN_OPENAI_BASE_URL"] == "SET"
    return has_key and has_endpoint


def check_openai_dependency() -> dict[str, Any]:
    try:
        import openai  # type: ignore # noqa: F401
    except Exception:
        return {"status": "fail", "dependency": "openai", "importable": False}
    return {"status": "pass", "dependency": "openai", "importable": True}


def check_request_serializable(request: TextGenerationRequest) -> dict[str, Any]:
    try:
        json.dumps(
            {
                "messages": request.messages,
                "model": request.model,
                "temperature": request.temperature,
                "max_tokens": request.max_output_tokens,
                "metadata": request.metadata,
            },
            ensure_ascii=False,
        )
    except Exception as exc:  # noqa: BLE001
        return {"status": "fail", "exception_class": exc.__class__.__name__}
    return {"status": "pass", "model": request.model, "max_output_tokens": request.max_output_tokens}


def check_streaming_parser() -> dict[str, Any]:
    chunks = [
        {"choices": [{"delta": {"content": "one "}}]},
        {"choices": [{"delta": {"content": "two"}}]},
    ]
    content = parse_openai_stream_content(chunks, first_byte_timeout_seconds=3, total_timeout_seconds=5)
    return {"status": "pass" if content == "one two" else "fail", "chunks_received": 2}


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
