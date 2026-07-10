#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.retrieval.bailian_official_client import (
    BailianOfficialClient,
    make_bailian_config,
    proxy_env_set_names,
    recommended_fix,
)

DUMMY_CONTENT = "# review-writer lease probe\nThis is a tiny dummy metadata file.\n"
DUMMY_FILE_NAME = "review-writer-lease-probe.md"
DUMMY_FILE_PATH = Path("/tmp/review-writer-lease-probe.md")
def main() -> int:
    args = parse_args()
    report = run_repro(args)
    write_outputs(report, args.output_json, args.output_md)
    print(
        "bailian-minimal-lease-repro: "
        f"{report['status']} error={report.get('error_type')} operation={report.get('operation_name')}"
    )
    return 1 if args.strict and report["status"] == "fail" else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Official-minimal ApplyFileUploadLease repro.")
    parser.add_argument("--endpoint", default="bailian.cn-beijing.aliyuncs.com")
    parser.add_argument("--category-id", default="default")
    parser.add_argument("--transport-mode", choices=["inherited_proxy", "no_proxy", "explicit_proxy"], default="inherited_proxy")
    parser.add_argument("--connect-timeout-ms", type=int, default=10000)
    parser.add_argument("--read-timeout-ms", type=int, default=20000)
    parser.add_argument("--proxy-url-env", default="HTTPS_PROXY")
    parser.add_argument("--output-json", type=Path, default=Path("/tmp/bailian_minimal_lease_repro_dry.json"))
    parser.add_argument("--output-md", type=Path, default=Path("/tmp/bailian_minimal_lease_repro_dry.md"))
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def run_repro(args: argparse.Namespace) -> dict[str, Any]:
    config = make_bailian_config(
        endpoint=args.endpoint,
        category_id=args.category_id,
        transport_mode=args.transport_mode,
        connect_timeout_ms=args.connect_timeout_ms,
        read_timeout_ms=args.read_timeout_ms,
        proxy_url_env=args.proxy_url_env,
    )
    client = BailianOfficialClient(config)
    base: dict[str, Any] = {
        "endpoint": args.endpoint,
        "category_id": args.category_id,
        "transport_mode": args.transport_mode,
        "connect_timeout_ms": args.connect_timeout_ms,
        "read_timeout_ms": args.read_timeout_ms,
        "proxy_url_env": args.proxy_url_env,
        "proxy_url_env_set": False if not args.proxy_url_env else bool(os.environ.get(args.proxy_url_env)),
        "proxy_env_set_names": proxy_env_set_names(),
        "operation_name": "ApplyFileUploadLease",
        "file_name": DUMMY_FILE_NAME,
        "file_size": len(DUMMY_CONTENT.encode("utf-8")),
        "md5_prefix": None,
        "lease_obtained": False,
        "lease_id_present": False,
        "upload_url_present": False,
        "headers_present": False,
        "network_attempted": False,
        "upload_attempted": False,
        "add_file_attempted": False,
        "index_attempted": False,
        "retrieve_attempted": False,
        "knowledge_base_created": False,
        "dependency_presence": client.dependency_presence(),
        "env_presence": client.env_presence(),
        "transport": client.transport_report(),
        "safe_error": None,
        "recommended_fix": None,
    }
    if not args.allow_network:
        return {
            **base,
            "status": "dry_run",
            "error_type": None,
            "summary": "minimal lease repro dry-run only; no network call was made",
        }
    DUMMY_FILE_PATH.write_text(DUMMY_CONTENT, encoding="utf-8")
    report = client.run_lease_probe(
        payload_md=DUMMY_FILE_PATH,
        allow_network=True,
        use_official_sdk=True,
    )
    return {
        **base,
        **{key: value for key, value in report.items() if key not in {"payload_md", "file_name", "file_size"}},
        "file_name": DUMMY_FILE_NAME,
        "file_size": len(DUMMY_CONTENT.encode("utf-8")),
        "md5_prefix": report.get("md5_prefix"),
        "proxy_env_set_names": proxy_env_set_names(),
    }


def write_outputs(report: dict[str, Any], output_json: Path, output_md: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(render_markdown(report), encoding="utf-8")


def render_markdown(report: dict[str, Any]) -> str:
    safe_error = report.get("safe_error") or {}
    lines = [
        "# Bailian Minimal Lease Repro",
        "",
        f"- status: `{report.get('status')}`",
        f"- error_type: `{report.get('error_type')}`",
        f"- endpoint: `{report.get('endpoint')}`",
        f"- category_id: `{report.get('category_id')}`",
        f"- transport_mode: `{report.get('transport_mode')}`",
        f"- connect_timeout_ms: `{report.get('connect_timeout_ms')}`",
        f"- read_timeout_ms: `{report.get('read_timeout_ms')}`",
        f"- proxy_url_env: `{report.get('proxy_url_env')}`",
        f"- proxy_url_env_set: `{report.get('proxy_url_env_set')}`",
        f"- proxy_env_set_names: `{report.get('proxy_env_set_names')}`",
        f"- operation_name: `{report.get('operation_name')}`",
        f"- lease_obtained: `{report.get('lease_obtained')}`",
        f"- lease_id_present: `{report.get('lease_id_present')}`",
        f"- upload_url_present: `{report.get('upload_url_present')}`",
        f"- headers_present: `{report.get('headers_present')}`",
        f"- upload_attempted: `{report.get('upload_attempted')}`",
        f"- knowledge_base_created: `{report.get('knowledge_base_created')}`",
        f"- recommended_fix: {report.get('recommended_fix')}",
        "",
        "## Safe Error",
        f"- exception_class: `{safe_error.get('exception_class')}`",
        f"- error_code: `{safe_error.get('error_code')}`",
        f"- status_code: `{safe_error.get('status_code')}`",
        f"- request_id_present: `{bool(safe_error.get('request_id'))}`",
        f"- cause_class: `{safe_error.get('cause_class')}`",
        f"- cause_message_redacted: {safe_error.get('cause_message_redacted')}",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
