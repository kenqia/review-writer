#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.retrieval.bailian_official_client import recommended_fix, safe_error_from_exception

DUMMY_CONTENT = b"# review-writer lease probe\nThis is a tiny dummy metadata file.\n"
DUMMY_FILE_NAME = "review-writer-lease-probe.md"
REQUIRED_MODULES = [
    "alibabacloud_bailian20231229",
    "alibabacloud_tea_openapi",
    "alibabacloud_tea_util",
]
REQUIRED_ENV = [
    "ALIBABA_CLOUD_ACCESS_KEY_ID",
    "ALIBABA_CLOUD_ACCESS_KEY_SECRET",
    "WORKSPACE_ID",
]


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
    parser.add_argument("--output-json", type=Path, default=Path("/tmp/bailian_minimal_lease_repro_dry.json"))
    parser.add_argument("--output-md", type=Path, default=Path("/tmp/bailian_minimal_lease_repro_dry.md"))
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def run_repro(args: argparse.Namespace) -> dict[str, Any]:
    md5 = hashlib.md5(DUMMY_CONTENT).hexdigest()  # noqa: S324 - required by Bailian upload lease API.
    base: dict[str, Any] = {
        "endpoint": args.endpoint,
        "category_id": args.category_id,
        "operation_name": "ApplyFileUploadLease",
        "file_name": DUMMY_FILE_NAME,
        "file_size": len(DUMMY_CONTENT),
        "md5_prefix": md5[:8],
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
        "dependency_presence": module_presence(),
        "env_presence": env_presence(),
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
    missing_modules = [name for name, status in base["dependency_presence"].items() if status == "MISSING"]
    if missing_modules:
        return {
            **base,
            "status": "fail",
            "error_type": "missing_dependency_or_api_contract",
            "summary": "official Bailian SDK modules are missing",
            "recommended_fix": recommended_fix("missing_dependency_or_api_contract"),
        }
    missing_env = [name for name, status in base["env_presence"].items() if status == "MISSING"]
    if missing_env:
        return {
            **base,
            "status": "fail",
            "error_type": "missing_env",
            "summary": "required env is missing; values were not printed",
            "recommended_fix": recommended_fix("missing_env"),
        }
    phase = "create_client"
    try:
        from alibabacloud_bailian20231229 import models
        from alibabacloud_bailian20231229.client import Client as BailianClient
        from alibabacloud_tea_openapi import models as open_api_models
        from alibabacloud_tea_util import models as util_models

        config = open_api_models.Config(
            access_key_id=os.environ["ALIBABA_CLOUD_ACCESS_KEY_ID"],
            access_key_secret=os.environ["ALIBABA_CLOUD_ACCESS_KEY_SECRET"],
        )
        config.endpoint = args.endpoint
        client = BailianClient(config)
        request = models.ApplyFileUploadLeaseRequest(
            file_name=DUMMY_FILE_NAME,
            md_5=md5,
            size_in_bytes=str(len(DUMMY_CONTENT)),
        )
        runtime = util_models.RuntimeOptions(connect_timeout=60000, read_timeout=60000)
        phase = "apply_file_upload_lease"
        response = client.apply_file_upload_lease_with_options(
            args.category_id,
            os.environ["WORKSPACE_ID"],
            request,
            {},
            runtime,
        )
        data = _safe_get(response, "body", "data")
        param = _safe_get(data, "param")
        headers = _safe_get(param, "headers") or {}
        return {
            **base,
            "status": "pass",
            "error_type": None,
            "summary": "ApplyFileUploadLease succeeded; no upload was attempted",
            "lease_obtained": True,
            "lease_id_present": bool(_safe_get(data, "file_upload_lease_id")),
            "upload_url_present": bool(_safe_get(param, "url")),
            "headers_present": bool(headers),
            "network_attempted": True,
        }
    except Exception as exc:  # noqa: BLE001 - minimal repro must safely report SDK failures.
        safe_error = safe_error_from_exception(
            exc,
            operation_name="ApplyFileUploadLease",
            phase=phase,
            endpoint=args.endpoint,
        )
        return {
            **base,
            "status": "fail",
            "error_type": safe_error["error_type"],
            "summary": safe_error["message_redacted"] or safe_error["exception_class"],
            "safe_error": safe_error,
            "recommended_fix": recommended_fix(safe_error["error_type"]),
            "network_attempted": phase != "create_client",
        }


def module_presence() -> dict[str, str]:
    presence: dict[str, str] = {}
    for module in REQUIRED_MODULES:
        try:
            __import__(module)
            presence[module] = "INSTALLED"
        except Exception:
            presence[module] = "MISSING"
    return presence


def env_presence() -> dict[str, str]:
    return {name: "SET" if os.environ.get(name) else "MISSING" for name in REQUIRED_ENV}


def _safe_get(obj: Any, *path: str) -> Any:
    current = obj
    for part in path:
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(part)
        else:
            current = getattr(current, part, None)
    return current


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
