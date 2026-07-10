#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.retrieval.bailian_official_client import proxy_env_set_names, recommended_fix
from scripts.rag.bailian_minimal_lease_repro import run_repro

MODES = ["inherited_proxy", "no_proxy", "explicit_proxy"]


def main() -> int:
    args = parse_args()
    report = run_matrix(args)
    write_outputs(report, args.output_json, args.output_md)
    print(
        "bailian-transport-matrix: "
        f"{report['overall_status']} working_mode={report.get('working_transport_mode')} "
        f"request_id_any={report.get('request_id_present_any')} lease_any={report.get('lease_obtained_any')}"
    )
    return 1 if args.strict and report["overall_status"] == "error" else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Bailian SDK proxy/transport matrix.")
    parser.add_argument("--endpoint", default="bailian.cn-beijing.aliyuncs.com")
    parser.add_argument("--category-id", default="default")
    parser.add_argument("--connect-timeout-ms", type=int, default=10000)
    parser.add_argument("--read-timeout-ms", type=int, default=20000)
    parser.add_argument("--proxy-url-env", default="HTTPS_PROXY")
    parser.add_argument("--output-json", type=Path, default=Path("/tmp/bailian_transport_matrix.json"))
    parser.add_argument("--output-md", type=Path, default=Path("/tmp/bailian_transport_matrix.md"))
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--use-official-sdk", action="store_true")
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def run_matrix(args: argparse.Namespace) -> dict[str, Any]:
    modes: list[dict[str, Any]] = []
    allow_real = bool(args.allow_network and args.use_official_sdk)
    for mode in MODES:
        repro_args = SimpleNamespace(
            endpoint=args.endpoint,
            category_id=args.category_id,
            transport_mode=mode,
            connect_timeout_ms=args.connect_timeout_ms,
            read_timeout_ms=args.read_timeout_ms,
            proxy_url_env=args.proxy_url_env,
            allow_network=allow_real,
            strict=False,
            output_json=Path("/tmp/unused.json"),
            output_md=Path("/tmp/unused.md"),
        )
        raw = run_repro(repro_args)
        modes.append(summarize_mode(raw))

    lease_mode = next((item["mode"] for item in modes if item.get("lease_obtained")), None)
    request_id_any = any(item.get("request_id_present") for item in modes)
    lease_any = bool(lease_mode)
    if not allow_real:
        overall_status = "dry_run"
        recommendation = "Pass --allow-network --use-official-sdk only after review to run the three lease-only modes."
    elif lease_any:
        overall_status = "pass"
        recommendation = f"retry full pilot once using {lease_mode} transport mode"
    elif request_id_any:
        overall_status = "service_reached"
        recommendation = "fix permission/workspace/category/request"
    else:
        overall_status = "transport_blocked"
        recommendation = "fix conda/SDK proxy/TLS transport or use manual console pilot"

    return {
        "overall_status": overall_status,
        "endpoint": args.endpoint,
        "category_id": args.category_id,
        "allow_network": args.allow_network,
        "use_official_sdk": args.use_official_sdk,
        "connect_timeout_ms": args.connect_timeout_ms,
        "read_timeout_ms": args.read_timeout_ms,
        "proxy_url_env": args.proxy_url_env,
        "proxy_url_env_set": bool(__import__("os").environ.get(args.proxy_url_env)),
        "proxy_env_set_names": proxy_env_set_names(),
        "modes": modes,
        "working_transport_mode": lease_mode,
        "request_id_present_any": request_id_any,
        "lease_obtained_any": lease_any,
        "recommendation": recommendation,
        "upload_attempted": False,
        "add_file_attempted": False,
        "index_attempted": False,
        "retrieve_attempted": False,
        "knowledge_base_created": False,
    }


def summarize_mode(raw: dict[str, Any]) -> dict[str, Any]:
    safe_error = raw.get("safe_error") or {}
    error_type = raw.get("error_type") or safe_error.get("error_type")
    return {
        "mode": raw.get("transport_mode"),
        "status": raw.get("status"),
        "error_type": error_type,
        "exception_class": safe_error.get("exception_class"),
        "request_id_present": bool(safe_error.get("request_id")),
        "status_code": safe_error.get("status_code"),
        "error_code": safe_error.get("error_code"),
        "lease_obtained": bool(raw.get("lease_obtained")),
        "first_failed_phase": raw.get("first_failed_phase") or safe_error.get("phase"),
        "operation_name": raw.get("operation_name") or safe_error.get("operation_name"),
        "recommended_fix": raw.get("recommended_fix") or recommended_fix(error_type),
        "proxy_env_set_names": raw.get("proxy_env_set_names") or [],
        "network_attempted": raw.get("network_attempted"),
        "upload_attempted": raw.get("upload_attempted"),
        "knowledge_base_created": raw.get("knowledge_base_created"),
    }


def write_outputs(report: dict[str, Any], output_json: Path, output_md: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(render_markdown(report), encoding="utf-8")


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Bailian Transport Matrix",
        "",
        f"- overall_status: `{report.get('overall_status')}`",
        f"- endpoint: `{report.get('endpoint')}`",
        f"- category_id: `{report.get('category_id')}`",
        f"- allow_network: `{report.get('allow_network')}`",
        f"- use_official_sdk: `{report.get('use_official_sdk')}`",
        f"- working_transport_mode: `{report.get('working_transport_mode')}`",
        f"- request_id_present_any: `{report.get('request_id_present_any')}`",
        f"- lease_obtained_any: `{report.get('lease_obtained_any')}`",
        f"- proxy_env_set_names: `{report.get('proxy_env_set_names')}`",
        f"- upload_attempted: `{report.get('upload_attempted')}`",
        f"- knowledge_base_created: `{report.get('knowledge_base_created')}`",
        "",
        "## Modes",
    ]
    for item in report.get("modes", []):
        lines.extend(
            [
                "",
                f"### {item.get('mode')}",
                f"- status: `{item.get('status')}`",
                f"- error_type: `{item.get('error_type')}`",
                f"- exception_class: `{item.get('exception_class')}`",
                f"- request_id_present: `{item.get('request_id_present')}`",
                f"- status_code: `{item.get('status_code')}`",
                f"- error_code: `{item.get('error_code')}`",
                f"- lease_obtained: `{item.get('lease_obtained')}`",
                f"- first_failed_phase: `{item.get('first_failed_phase')}`",
                f"- operation_name: `{item.get('operation_name')}`",
                f"- recommended_fix: {item.get('recommended_fix')}",
            ]
        )
    lines.extend(["", f"- recommendation: {report.get('recommendation')}"])
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
