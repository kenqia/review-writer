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

from review_writer.retrieval.bailian_official_client import DEFAULT_CATEGORY_TYPE, recommended_fix
from scripts.rag.bailian_category_discovery import run_discovery

DEFAULT_CANDIDATES = [
    "UNSTRUCTURED",
    "SESSION_FILE",
    "DOCUMENT",
    "DATA_CENTER_FILE",
    "DATA_CENTER_CATEGORY",
    "DEFAULT",
    "INDEX",
    "KNOWLEDGE_BASE",
]


def main() -> int:
    args = parse_args()
    report = run_matrix(args)
    write_outputs(report, args.output_json, args.output_md)
    print(
        "bailian-category-type-matrix: "
        f"{report['overall_status']} recommended_type={report.get('recommended_category_type')} "
        f"recommended_id={report.get('recommended_category_id')}"
    )
    return 1 if args.strict and report["overall_status"] == "error" else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discover Bailian CategoryType candidates via ListCategory only.")
    parser.add_argument("--endpoint", default="bailian.cn-beijing.aliyuncs.com")
    parser.add_argument("--transport-mode", choices=["inherited_proxy", "no_proxy", "explicit_proxy"], default="no_proxy")
    parser.add_argument("--category-types", nargs="*", default=DEFAULT_CANDIDATES)
    parser.add_argument("--connect-timeout-ms", type=int, default=10000)
    parser.add_argument("--read-timeout-ms", type=int, default=20000)
    parser.add_argument("--proxy-url-env", default="HTTPS_PROXY")
    parser.add_argument("--output-json", type=Path, default=Path("/tmp/bailian_category_type_matrix.json"))
    parser.add_argument("--output-md", type=Path, default=Path("/tmp/bailian_category_type_matrix.md"))
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--use-official-sdk", action="store_true")
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def run_matrix(args: argparse.Namespace) -> dict[str, Any]:
    allow_real = bool(args.allow_network and args.use_official_sdk)
    candidates = dedupe_candidates(args.category_types)
    results: list[dict[str, Any]] = []
    for candidate in candidates:
        discovery_args = SimpleNamespace(
            endpoint=args.endpoint,
            transport_mode=args.transport_mode,
            category_type=candidate,
            connect_timeout_ms=args.connect_timeout_ms,
            read_timeout_ms=args.read_timeout_ms,
            proxy_url_env=args.proxy_url_env,
            allow_network=allow_real,
            use_official_sdk=allow_real,
            strict=False,
            output_json=Path("/tmp/unused.json"),
            output_md=Path("/tmp/unused.md"),
        )
        results.append(summarize_candidate(candidate, run_discovery(discovery_args)))

    found = next((item for item in results if item["status"] == "pass" and item["recommended_category_id"]), None)
    valid_empty = next((item for item in results if item["status"] == "pass" and item["categories_count"] == 0), None)
    if not allow_real:
        overall_status = "dry_run"
        next_action = "Run with --allow-network --use-official-sdk after review to test ListCategory candidates."
    elif found:
        overall_status = "category_type_found"
        next_action = "Run one lease-only reprobe with the recommended category type and id."
    elif valid_empty:
        overall_status = "category_type_valid_but_empty"
        next_action = "Create/select a category in console or inspect create-category API; do not full-pilot yet."
    else:
        overall_status = "category_type_unknown"
        next_action = "Use official API Explorer or console manual pilot; do not full-pilot blindly."

    return {
        "overall_status": overall_status,
        "endpoint": args.endpoint,
        "transport_mode": args.transport_mode,
        "allow_network": args.allow_network,
        "use_official_sdk": args.use_official_sdk,
        "candidate_category_types": candidates,
        "results": results,
        "network_attempted": any(item.get("network_attempted") for item in results),
        "recommended_category_type": found["candidate_category_type"] if found else None,
        "recommended_category_id": found["recommended_category_id"] if found else None,
        "recommended_reason": found["recommended_reason"] if found else None,
        "next_action": next_action,
        "upload_attempted": False,
        "add_file_attempted": False,
        "index_attempted": False,
        "retrieve_attempted": False,
        "knowledge_base_created": False,
    }


def summarize_candidate(candidate: str, report: dict[str, Any]) -> dict[str, Any]:
    safe_error = report.get("safe_error") or {}
    categories = report.get("categories_safe_summary") or []
    error_type = report.get("error_type") or safe_error.get("error_type")
    return {
        "category_type": candidate,
        "candidate_category_type": candidate,
        "status": report.get("status"),
        "error_type": error_type,
        "request_id_present": bool(report.get("request_id_present") or safe_error.get("request_id")),
        "status_code": safe_error.get("status_code"),
        "error_code": safe_error.get("error_code"),
        "categories_count": report.get("categories_count", 0),
        "category_ids_safe": [item.get("category_id") for item in categories if item.get("category_id")],
        "recommended_category_id": report.get("recommended_category_id"),
        "recommended_reason": report.get("recommended_reason") or recommended_fix(error_type),
        "network_attempted": report.get("network_attempted"),
        "upload_attempted": report.get("upload_attempted"),
        "knowledge_base_created": report.get("knowledge_base_created"),
    }


def dedupe_candidates(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        candidate = str(value).strip().upper()
        if candidate and candidate not in result:
            result.append(candidate)
    if DEFAULT_CATEGORY_TYPE not in result:
        result.insert(0, DEFAULT_CATEGORY_TYPE)
    return result


def write_outputs(report: dict[str, Any], output_json: Path, output_md: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(render_markdown(report), encoding="utf-8")


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Bailian CategoryType Matrix",
        "",
        f"- overall_status: `{report.get('overall_status')}`",
        f"- endpoint: `{report.get('endpoint')}`",
        f"- transport_mode: `{report.get('transport_mode')}`",
        f"- allow_network: `{report.get('allow_network')}`",
        f"- use_official_sdk: `{report.get('use_official_sdk')}`",
        f"- recommended_category_type: `{report.get('recommended_category_type')}`",
        f"- recommended_category_id: `{report.get('recommended_category_id')}`",
        f"- upload_attempted: `{report.get('upload_attempted')}`",
        f"- knowledge_base_created: `{report.get('knowledge_base_created')}`",
        "",
        "## Candidates",
    ]
    for item in report.get("results", []):
        lines.extend(
            [
                "",
                f"### {item.get('candidate_category_type')}",
                f"- status: `{item.get('status')}`",
                f"- error_type: `{item.get('error_type')}`",
                f"- request_id_present: `{item.get('request_id_present')}`",
                f"- status_code: `{item.get('status_code')}`",
                f"- error_code: `{item.get('error_code')}`",
                f"- categories_count: `{item.get('categories_count')}`",
                f"- category_ids_safe: `{item.get('category_ids_safe')}`",
                f"- recommended_category_id: `{item.get('recommended_category_id')}`",
            ]
        )
    lines.extend(["", f"- next_action: {report.get('next_action')}"])
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
