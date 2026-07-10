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

from review_writer.retrieval.bailian_official_client import (  # noqa: E402
    BailianOfficialClient,
    make_bailian_config,
    recommended_fix,
    safe_error_from_exception,
)


def main() -> int:
    args = parse_args()
    report = run_cleanup(args)
    write_outputs(report, args.output_json, args.output_md)
    print(
        "bailian-orphan-file-cleanup: "
        f"{report['status']} file_id_present={report['file_id_present']} cleanup={report['file_cleanup']}"
    )
    return 1 if args.strict and report["status"] == "fail" else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cleanup one Bailian Application Data orphan file from a /tmp pilot report.")
    parser.add_argument("--report-json", type=Path, default=Path("/tmp/bailian_small_kb_pilot_real.json"))
    parser.add_argument("--output-json", type=Path, default=Path("/tmp/bailian_orphan_file_cleanup.json"))
    parser.add_argument("--output-md", type=Path, default=Path("/tmp/bailian_orphan_file_cleanup.md"))
    parser.add_argument("--endpoint")
    parser.add_argument("--region")
    parser.add_argument("--category-id", default="default")
    parser.add_argument("--transport-mode", choices=["inherited_proxy", "no_proxy", "explicit_proxy"], default="inherited_proxy")
    parser.add_argument("--connect-timeout-ms", type=int, default=10000)
    parser.add_argument("--read-timeout-ms", type=int, default=20000)
    parser.add_argument("--proxy-url-env", default="HTTPS_PROXY")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--use-official-sdk", action="store_true")
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def run_cleanup(args: argparse.Namespace) -> dict[str, Any]:
    report_data = read_report(args.report_json)
    file_id = extract_file_id(report_data)
    index_id = extract_index_id(report_data)
    client_wrapper = BailianOfficialClient(
        make_bailian_config(
            endpoint=args.endpoint,
            region=args.region,
            category_id=args.category_id,
            transport_mode=args.transport_mode,
            connect_timeout_ms=args.connect_timeout_ms,
            read_timeout_ms=args.read_timeout_ms,
            proxy_url_env=args.proxy_url_env,
        )
    )
    base = {
        "status": "dry_run",
        "error_type": None,
        "summary": "dry-run only; no cleanup call was made",
        "report_json": str(args.report_json),
        "file_id_present": bool(file_id),
        "index_id_present": bool(index_id),
        "index_cleanup": "not_attempted",
        "file_cleanup": "not_attempted",
        "cleanup_attempted": False,
        "network_attempted": False,
        "created_resource_ids_cleaned": "not_created" if not file_id and not index_id else "no",
        "env_presence": client_wrapper.env_presence(),
        "dependency_presence": client_wrapper.dependency_presence(),
        "safe_error": None,
        "recommended_fix": None,
        "ids_redacted": True,
    }
    if not args.report_json.exists():
        return {
            **base,
            "status": "fail",
            "error_type": "missing_report",
            "summary": "pilot report JSON is missing",
        }
    if not file_id and not index_id:
        return {
            **base,
            "status": "fail",
            "error_type": "missing_resource_id",
            "summary": "pilot report does not contain cleanup resource ids",
        }
    if not args.allow_network or not args.use_official_sdk:
        return base
    readiness = client_wrapper._readiness_error(base)  # noqa: SLF001 - CLI needs the same readiness gate as the pilot.
    if readiness:
        return readiness
    phase = "create_client"
    try:
        with client_wrapper.transport_environment():
            client = client_wrapper.create_client()
            workspace_id = os.environ["WORKSPACE_ID"]
            if index_id:
                phase = "delete_index"
                client_wrapper.delete_index(client, workspace_id, index_id)
            if file_id:
                phase = "delete_file"
                client_wrapper.delete_file(client, workspace_id, file_id)
        return {
            **base,
            "status": "pass",
            "summary": "orphan cleanup request completed",
            "index_cleanup": "pass" if index_id else "not_created",
            "file_cleanup": "pass" if file_id else "not_created",
            "cleanup_attempted": True,
            "network_attempted": True,
            "created_resource_ids_cleaned": "yes",
        }
    except Exception as exc:  # noqa: BLE001 - cleanup reports must classify safe failures.
        safe_error = safe_error_from_exception(
            exc,
            operation_name="DeleteFile",
            phase=phase,
            endpoint=client_wrapper.config.endpoint,
        )
        return {
            **base,
            "status": "fail",
            "error_type": safe_error["error_type"],
            "summary": safe_error["message_redacted"] or safe_error["exception_class"],
            "index_cleanup": "fail" if phase == "delete_index" else base["index_cleanup"],
            "file_cleanup": "fail" if phase == "delete_file" else base["file_cleanup"],
            "cleanup_attempted": phase != "create_client",
            "network_attempted": phase != "create_client",
            "created_resource_ids_cleaned": "no",
            "safe_error": safe_error,
            "recommended_fix": recommended_fix(safe_error["error_type"]),
        }


def read_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def extract_file_id(report: dict[str, Any]) -> str | None:
    candidates = [
        report.get("file_id"),
        report.get("created_file_id"),
        (report.get("official_sdk_result") or {}).get("file_id"),
        (report.get("official_sdk_result") or {}).get("created_file_id"),
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def extract_index_id(report: dict[str, Any]) -> str | None:
    candidates = [
        report.get("index_id"),
        report.get("created_index_id"),
        (report.get("official_sdk_result") or {}).get("index_id"),
        (report.get("official_sdk_result") or {}).get("created_index_id"),
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def write_outputs(report: dict[str, Any], output_json: Path, output_md: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(render_markdown(report), encoding="utf-8")


def render_markdown(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Bailian Orphan File Cleanup",
            "",
            f"- status: `{report['status']}`",
            f"- error_type: `{report.get('error_type')}`",
            f"- summary: {report['summary']}",
            f"- file_id_present: `{report['file_id_present']}`",
            f"- index_id_present: `{report['index_id_present']}`",
            f"- index_cleanup: `{report['index_cleanup']}`",
            f"- file_cleanup: `{report['file_cleanup']}`",
            f"- cleanup_attempted: `{report['cleanup_attempted']}`",
            f"- network_attempted: `{report['network_attempted']}`",
            f"- created_resource_ids_cleaned: `{report['created_resource_ids_cleaned']}`",
            f"- ids_redacted: `{report['ids_redacted']}`",
        ]
    ) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
