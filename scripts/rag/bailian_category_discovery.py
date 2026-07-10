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

from review_writer.retrieval.bailian_official_client import (
    BailianOfficialClient,
    make_bailian_config,
    proxy_env_set_names,
    recommend_category,
    recommended_fix,
    safe_error_from_exception,
)


def main() -> int:
    args = parse_args()
    report = run_discovery(args)
    write_outputs(report, args.output_json, args.output_md)
    print(
        "bailian-category-discovery: "
        f"{report['status']} error={report.get('error_type')} "
        f"categories={report.get('categories_count')} recommended={report.get('recommended_category_id')}"
    )
    return 1 if args.strict and report["status"] == "fail" else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discover Bailian categories using ListCategory only.")
    parser.add_argument("--endpoint", default="bailian.cn-beijing.aliyuncs.com")
    parser.add_argument("--transport-mode", choices=["inherited_proxy", "no_proxy", "explicit_proxy"], default="no_proxy")
    parser.add_argument("--category-type")
    parser.add_argument("--connect-timeout-ms", type=int, default=10000)
    parser.add_argument("--read-timeout-ms", type=int, default=20000)
    parser.add_argument("--proxy-url-env", default="HTTPS_PROXY")
    parser.add_argument("--output-json", type=Path, default=Path("/tmp/bailian_category_discovery.json"))
    parser.add_argument("--output-md", type=Path, default=Path("/tmp/bailian_category_discovery.md"))
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--use-official-sdk", action="store_true")
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def run_discovery(args: argparse.Namespace) -> dict[str, Any]:
    config = make_bailian_config(
        endpoint=args.endpoint,
        transport_mode=args.transport_mode,
        connect_timeout_ms=args.connect_timeout_ms,
        read_timeout_ms=args.read_timeout_ms,
        proxy_url_env=args.proxy_url_env,
    )
    client = BailianOfficialClient(config)
    base: dict[str, Any] = {
        "endpoint": args.endpoint,
        "transport_mode": args.transport_mode,
        "category_type": args.category_type,
        "operation_name": "ListCategory",
        "status": "dry_run",
        "error_type": None,
        "request_id_present": False,
        "categories_count": 0,
        "categories_safe_summary": [],
        "candidate_category_ids": [],
        "recommended_category_id": None,
        "recommended_category_type": None,
        "recommended_reason": None,
        "network_attempted": False,
        "apply_file_upload_lease_attempted": False,
        "upload_attempted": False,
        "add_file_attempted": False,
        "index_attempted": False,
        "retrieve_attempted": False,
        "knowledge_base_created": False,
        "dependency_presence": client.dependency_presence(),
        "env_presence": client.env_presence(),
        "proxy_env_set_names": proxy_env_set_names(),
        "safe_error": None,
        "recommended_fix": None,
    }
    if not args.allow_network or not args.use_official_sdk:
        return {
            **base,
            "summary": "category discovery dry-run only; no network call was made",
        }
    phase = "create_client"
    try:
        with client.transport_environment():
            sdk_client = client.create_client()
            import os

            workspace_id = os.environ["WORKSPACE_ID"]
            phase = "list_category"
            result = client.list_categories(sdk_client, workspace_id, category_type=args.category_type)
        categories = result["categories"]
        recommendation = recommend_category(categories)
        return {
            **base,
            "status": "pass",
            "summary": "ListCategory succeeded; no upload or KB operation was attempted",
            "network_attempted": True,
            "request_id_present": bool(result.get("request_id")),
            "categories_count": result.get("categories_count", 0),
            "categories_safe_summary": categories,
            "candidate_category_ids": [item["category_id"] for item in categories if item.get("category_id")],
            **recommendation,
        }
    except Exception as exc:  # noqa: BLE001 - discovery must safely classify SDK failures.
        safe_error = safe_error_from_exception(
            exc,
            operation_name="ListCategory",
            phase=phase,
            endpoint=args.endpoint,
        )
        return {
            **base,
            "status": "fail",
            "error_type": safe_error["error_type"],
            "summary": safe_error["message_redacted"] or safe_error["exception_class"],
            "request_id_present": bool(safe_error.get("request_id")),
            "safe_error": safe_error,
            "recommended_fix": recommended_fix(safe_error["error_type"]),
            "network_attempted": phase != "create_client",
        }


def write_outputs(report: dict[str, Any], output_json: Path, output_md: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(render_markdown(report), encoding="utf-8")


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Bailian Category Discovery",
        "",
        f"- status: `{report.get('status')}`",
        f"- error_type: `{report.get('error_type')}`",
        f"- endpoint: `{report.get('endpoint')}`",
        f"- transport_mode: `{report.get('transport_mode')}`",
        f"- category_type: `{report.get('category_type')}`",
        f"- operation_name: `{report.get('operation_name')}`",
        f"- request_id_present: `{report.get('request_id_present')}`",
        f"- categories_count: `{report.get('categories_count')}`",
        f"- candidate_category_ids: `{report.get('candidate_category_ids')}`",
        f"- recommended_category_id: `{report.get('recommended_category_id')}`",
        f"- recommended_category_type: `{report.get('recommended_category_type')}`",
        f"- recommended_reason: {report.get('recommended_reason')}",
        f"- upload_attempted: `{report.get('upload_attempted')}`",
        f"- knowledge_base_created: `{report.get('knowledge_base_created')}`",
        "",
        "## Categories",
    ]
    for item in report.get("categories_safe_summary", []):
        lines.append(
            "- "
            f"category_id=`{item.get('category_id')}`, "
            f"name=`{item.get('name_redacted_or_plain_if_safe')}`, "
            f"type=`{item.get('type')}`, "
            f"parent_id_present=`{item.get('parent_id_present')}`, "
            f"status=`{item.get('status')}`, "
            f"is_default_candidate=`{item.get('is_default_candidate')}`"
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
