#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.retrieval.bailian_official_client import BailianOfficialClient

DEFAULT_PAYLOAD_MD = Path("/tmp/bailian_small_kb_upload_payload.md")
FALLBACK_PAYLOAD_MD = Path("/tmp/bailian_small_kb_payload.md")
FORBIDDEN_RE = re.compile(
    r"(\.pdf\b|\.png\b|\.jpe?g\b|\.webp\b|/home/|/mnt/|[A-Za-z]:\\Users\\|"
    r"api[_-]?key\s*[:=]|token\s*[:=]|secret\s*[:=]|authorization\s*[:=]|x-bailian-extra|sk-)",
    re.I,
)


def main() -> int:
    args = parse_args()
    report = run_probe(args)
    write_outputs(report, args.output_json, args.output_md)
    print(
        "bailian-lease-probe: "
        f"{report['status']} error={report.get('error_type')} operation={report.get('operation_name')}"
    )
    return 1 if args.strict and report["status"] == "fail" else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lease-only Bailian SDK diagnostic probe.")
    parser.add_argument("--payload-md", type=Path, default=DEFAULT_PAYLOAD_MD)
    parser.add_argument("--output-json", type=Path, default=Path("/tmp/bailian_lease_probe_dry.json"))
    parser.add_argument("--output-md", type=Path, default=Path("/tmp/bailian_lease_probe_dry.md"))
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--use-official-sdk", action="store_true")
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    payload_status = ensure_probe_payload(args.payload_md)
    client = BailianOfficialClient()
    base = {
        "payload_md": str(args.payload_md),
        "payload_status": payload_status["status"],
        "payload_errors": payload_status["errors"],
        "operation_name": "ApplyFileUploadLease",
        "first_failed_phase": None,
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
        "safety": {
            "key_printed": "no",
            "presigned_url_printed": "no",
            "signed_headers_printed": "no",
            "upload": "not_used",
            "add_file": "not_used",
            "create_index": "not_used",
            "retrieve": "not_used",
            "qwen": "not_used",
            "mineru": "not_used",
            "image_api": "not_used",
        },
    }
    if payload_status["status"] == "fail":
        return {
            **base,
            "status": "fail",
            "error_type": "upload_rejected",
            "summary": "lease probe payload validation failed",
            "first_failed_phase": "payload_guard",
            "recommended_fix": "Regenerate the sanitized payload and ensure no forbidden paths or secrets are present.",
        }
    result = client.run_lease_probe(
        payload_md=args.payload_md,
        allow_network=args.allow_network,
        use_official_sdk=args.use_official_sdk,
    )
    return {
        **base,
        **result,
        "payload_status": payload_status["status"],
        "payload_errors": payload_status["errors"],
        "safety": base["safety"],
    }


def ensure_probe_payload(path: Path) -> dict[str, Any]:
    if not path.exists() and FALLBACK_PAYLOAD_MD.exists():
        text = FALLBACK_PAYLOAD_MD.read_text(encoding="utf-8")
        if FORBIDDEN_RE.search(text):
            return {"status": "fail", "errors": ["fallback payload contains forbidden content"]}
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FALLBACK_PAYLOAD_MD, path)
    if not path.exists():
        return {"status": "fail", "errors": [f"missing payload markdown: {path}"]}
    text = path.read_text(encoding="utf-8")
    errors = []
    if FORBIDDEN_RE.search(text):
        errors.append("payload markdown contains forbidden content")
    if not text.strip():
        errors.append("payload markdown is empty")
    return {"status": "fail" if errors else "pass", "errors": errors}


def write_outputs(report: dict[str, Any], output_json: Path, output_md: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(render_markdown(report), encoding="utf-8")


def render_markdown(report: dict[str, Any]) -> str:
    safe_error = report.get("safe_error") or {}
    lines = [
        "# Bailian Lease-only Probe",
        "",
        f"- status: `{report.get('status')}`",
        f"- error_type: `{report.get('error_type')}`",
        f"- operation_name: `{report.get('operation_name')}`",
        f"- first_failed_phase: `{report.get('first_failed_phase')}`",
        f"- summary: {report.get('summary')}",
        f"- file_name: `{report.get('file_name')}`",
        f"- file_size: `{report.get('file_size')}`",
        f"- md5_prefix: `{report.get('md5_prefix')}`",
        f"- lease_obtained: `{report.get('lease_obtained')}`",
        f"- lease_id_present: `{report.get('lease_id_present')}`",
        f"- upload_url_present: `{report.get('upload_url_present')}`",
        f"- headers_present: `{report.get('headers_present')}`",
        f"- recommended_fix: {report.get('recommended_fix')}",
        "",
        "## Safe Error",
        f"- exception_class: `{safe_error.get('exception_class')}`",
        f"- error_code: `{safe_error.get('error_code')}`",
        f"- status_code: `{safe_error.get('status_code')}`",
        f"- request_id_present: `{bool(safe_error.get('request_id'))}`",
        f"- message_redacted: {safe_error.get('message_redacted')}",
        f"- data_keys: `{safe_error.get('data_keys')}`",
        "",
        "## Safety",
    ]
    lines.extend(f"- {key}: `{value}`" for key, value in report.get("safety", {}).items())
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
