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

from review_writer.retrieval.bailian_official_client import category_sdk_capabilities


def main() -> int:
    args = parse_args()
    report = build_report()
    write_outputs(report, args.output_json, args.output_md)
    print(
        "bailian-category-introspection: "
        f"{report['status']} list_request={report['has_list_category_request']} "
        f"list_method={report['has_list_category_with_options']}"
    )
    return 1 if args.strict and report["status"] == "fail" else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect Bailian SDK category API capability.")
    parser.add_argument("--output-json", type=Path, default=Path("/tmp/bailian_category_introspection.json"))
    parser.add_argument("--output-md", type=Path, default=Path("/tmp/bailian_category_introspection.md"))
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def build_report() -> dict[str, Any]:
    caps = category_sdk_capabilities()
    missing_modules = [name for name, status in caps["modules"].items() if status == "MISSING"]
    has_list_request = bool(caps["has_list_category_request"])
    has_list_method = bool(caps["has_list_category_with_options"])
    status = "pass" if has_list_request and has_list_method else ("warn" if missing_modules else "fail")
    return {
        "status": status,
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "installed_modules": caps["modules"],
        "missing_modules": missing_modules,
        "has_list_category_request": has_list_request,
        "has_list_category_with_options": has_list_method,
        "has_create_category_request": bool(caps["has_create_category_request"]),
        "request_models": caps["request_models"],
        "client_methods": caps["client_methods"],
        "recommendation": recommendation(status),
    }


def recommendation(status: str) -> str:
    if status == "pass":
        return "SDK exposes ListCategory; category discovery can run after explicit network approval."
    if status == "warn":
        return "Run inside review-writer-bailian conda env for strict SDK category introspection."
    return "Installed SDK lacks ListCategory contract; verify package version before discovery."


def write_outputs(report: dict[str, Any], output_json: Path, output_md: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(render_markdown(report), encoding="utf-8")


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Bailian Category Introspection",
        "",
        f"- status: `{report.get('status')}`",
        f"- has_list_category_request: `{report.get('has_list_category_request')}`",
        f"- has_list_category_with_options: `{report.get('has_list_category_with_options')}`",
        f"- has_create_category_request: `{report.get('has_create_category_request')}`",
        f"- missing_modules: `{report.get('missing_modules')}`",
        f"- recommendation: {report.get('recommendation')}",
        "",
        "## ListCategoryRequest Fields",
        f"`{(report.get('request_models') or {}).get('ListCategoryRequest', {}).get('instance_fields', [])}`",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
