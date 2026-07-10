#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.retrieval.bailian_official_client import sdk_transport_capabilities

IMPORTANT_FIELDS = [
    "proxy",
    "http_proxy",
    "https_proxy",
    "connect_timeout",
    "read_timeout",
    "autoretry",
    "ignore_ssl",
]


def main() -> int:
    args = parse_args()
    report = build_report()
    write_outputs(report, args.output_json, args.output_md)
    print(
        "bailian-sdk-transport-introspection: "
        f"{report['status']} config_proxy={report['config_supports_proxy']} "
        f"runtime_proxy={report['runtime_supports_proxy']}"
    )
    return 1 if args.strict and report["status"] == "fail" else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect Bailian SDK transport/proxy runtime capabilities.")
    parser.add_argument("--output-json", type=Path, default=Path("/tmp/bailian_sdk_transport_introspection.json"))
    parser.add_argument("--output-md", type=Path, default=Path("/tmp/bailian_sdk_transport_introspection.md"))
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def build_report() -> dict[str, Any]:
    capabilities = sdk_transport_capabilities()
    modules = capabilities["modules"]
    config = capabilities["config"]
    runtime = capabilities["runtime_options"]
    missing_modules = [name for name, status in modules.items() if status == "MISSING"]
    config_supports_proxy = any(bool(config.get(field)) for field in ("proxy", "http_proxy", "https_proxy"))
    runtime_supports_proxy = any(bool(runtime.get(field)) for field in ("proxy", "http_proxy", "https_proxy"))
    config_supports_timeout = any(bool(config.get(field)) for field in ("connect_timeout", "read_timeout"))
    runtime_supports_timeout = any(bool(runtime.get(field)) for field in ("connect_timeout", "read_timeout"))
    status = "pass" if not missing_modules else "fail"
    return {
        "status": status,
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "installed_modules": modules,
        "missing_modules": missing_modules,
        "config_fields": config.get("fields", []),
        "runtime_options_fields": runtime.get("fields", []),
        "config_field_support": {field: bool(config.get(field)) for field in IMPORTANT_FIELDS},
        "runtime_options_field_support": {field: bool(runtime.get(field)) for field in IMPORTANT_FIELDS},
        "config_supports_proxy": config_supports_proxy,
        "runtime_supports_proxy": runtime_supports_proxy,
        "config_supports_timeout": config_supports_timeout,
        "runtime_supports_timeout": runtime_supports_timeout,
        "recommendation": recommendation(status, config_supports_proxy, runtime_supports_proxy),
    }


def recommendation(status: str, config_proxy: bool, runtime_proxy: bool) -> str:
    if status == "fail":
        return "Run inside the isolated review-writer-bailian conda env before a real SDK matrix."
    if config_proxy or runtime_proxy:
        return "SDK exposes proxy fields; explicit_proxy mode can be tested without printing proxy values."
    return "SDK timeout fields may still work, but explicit proxy mode is unsupported by introspection."


def write_outputs(report: dict[str, Any], output_json: Path, output_md: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(render_markdown(report), encoding="utf-8")


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Bailian SDK Transport Introspection",
        "",
        f"- status: `{report.get('status')}`",
        f"- python_executable: `{report.get('python_executable')}`",
        f"- python_version: `{report.get('python_version')}`",
        f"- missing_modules: `{report.get('missing_modules')}`",
        f"- config_supports_proxy: `{report.get('config_supports_proxy')}`",
        f"- runtime_supports_proxy: `{report.get('runtime_supports_proxy')}`",
        f"- config_supports_timeout: `{report.get('config_supports_timeout')}`",
        f"- runtime_supports_timeout: `{report.get('runtime_supports_timeout')}`",
        f"- config_fields: `{report.get('config_fields')}`",
        f"- runtime_options_fields: `{report.get('runtime_options_fields')}`",
        f"- recommendation: {report.get('recommendation')}",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
