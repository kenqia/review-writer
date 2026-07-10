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

from review_writer.retrieval.bailian_official_client import retrieve_sdk_capabilities


def main() -> int:
    args = parse_args()
    report = build_report()
    write_outputs(report, args.output_json, args.output_md)
    supported = report["retrieve_request_supported_fields"]
    print(
        "bailian-retrieve-contract-introspection: "
        f"{report['status']} query={supported.get('query')} index_id={supported.get('index_id')}"
    )
    return 1 if args.strict and report["status"] == "fail" else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect installed Bailian SDK Retrieve request/response contract.")
    parser.add_argument("--output-json", type=Path, default=Path("/tmp/bailian_retrieve_contract_introspection.json"))
    parser.add_argument("--output-md", type=Path, default=Path("/tmp/bailian_retrieve_contract_introspection.md"))
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def build_report() -> dict[str, Any]:
    capabilities = retrieve_sdk_capabilities()
    missing = [name for name, status in capabilities["modules"].items() if status == "MISSING"]
    return {
        "status": "fail" if missing else "pass",
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "installed_modules": capabilities["modules"],
        "missing_modules": missing,
        "models": capabilities["models"],
        "client_methods": capabilities["client_methods"],
        "retrieve_request_supported_fields": capabilities["retrieve_request_supported_fields"],
    }


def write_outputs(report: dict[str, Any], output_json: Path, output_md: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(render_markdown(report), encoding="utf-8")


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Bailian Retrieve Contract Introspection",
        "",
        f"- status: `{report['status']}`",
        f"- python_executable: `{report['python_executable']}`",
        f"- python_version: `{report['python_version']}`",
        f"- missing_modules: `{report['missing_modules']}`",
        "",
        "## RetrieveRequest Supported Fields",
    ]
    for field, supported in report["retrieve_request_supported_fields"].items():
        lines.append(f"- {field}: `{supported}`")
    lines.extend(["", "## Models"])
    for name, model in report["models"].items():
        lines.append(
            f"- {name}: exists=`{model.get('exists')}`, "
            f"signature_fields=`{model.get('signature_fields')}`, "
            f"instance_fields=`{model.get('instance_fields')}`"
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
