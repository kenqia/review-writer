#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.retrieval.bailian_official_client import (
    BailianOfficialClient,
    make_bailian_config,
    validate_rerank_config,
)

OFFICIAL_UPLOAD_MD = Path("/tmp/bailian_small_kb_upload_payload.md")
FORBIDDEN_RE = re.compile(r"(\.pdf\b|\.png\b|\.jpe?g\b|\.webp\b|/home/|/mnt/|[A-Za-z]:\\Users\\|api[_-]?key\s*[:=]|token\s*[:=]|secret\s*[:=]|sk-)", re.I)


def main() -> int:
    args = parse_args()
    report = run_pilot(args)
    write_outputs(report, args.output_json, args.output_md)
    print(
        "bailian-small-kb-pilot: "
        f"{report['status']} error={report.get('error_type')} retrieval={report.get('retrieval_status')}"
    )
    return 1 if args.strict and report["status"] == "fail" else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Controlled Bailian small-KB pilot wrapper.")
    parser.add_argument("--payload-jsonl", type=Path, default=Path("/tmp/bailian_small_kb_payload.jsonl"))
    parser.add_argument("--questions", type=Path, default=Path("evals/fixtures/rag_expected_questions.json"))
    parser.add_argument("--output-json", type=Path, default=Path("/tmp/bailian_small_kb_pilot_dry.json"))
    parser.add_argument("--output-md", type=Path, default=Path("/tmp/bailian_small_kb_pilot_dry.md"))
    parser.add_argument("--endpoint")
    parser.add_argument("--region")
    parser.add_argument("--category-id", default="default")
    parser.add_argument("--transport-mode", choices=["inherited_proxy", "no_proxy", "explicit_proxy"], default="inherited_proxy")
    parser.add_argument("--connect-timeout-ms", type=int, default=10000)
    parser.add_argument("--read-timeout-ms", type=int, default=20000)
    parser.add_argument("--proxy-url-env", default="HTTPS_PROXY")
    parser.add_argument("--rerank-mode")
    parser.add_argument("--rerank-instruct")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--allow-upload", action="store_true")
    parser.add_argument("--use-official-sdk", action="store_true")
    parser.add_argument("--cleanup", action="store_true")
    parser.add_argument("--cleanup-index-id")
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def run_pilot(args: argparse.Namespace) -> dict[str, Any]:
    payload_status = validate_payload(args.payload_jsonl)
    upload_md_status = build_upload_markdown(args.payload_jsonl, OFFICIAL_UPLOAD_MD)
    questions_status = validate_questions(args.questions)
    env = safe_env_presence()
    official = BailianOfficialClient(
        make_bailian_config(
            endpoint=args.endpoint,
            region=args.region,
            category_id=args.category_id,
            transport_mode=args.transport_mode,
            connect_timeout_ms=args.connect_timeout_ms,
            read_timeout_ms=args.read_timeout_ms,
            proxy_url_env=args.proxy_url_env,
            rerank_mode=args.rerank_mode,
            rerank_instruct=args.rerank_instruct,
        )
    )
    base = {
        "payload_jsonl": str(args.payload_jsonl),
        "official_upload_md": str(OFFICIAL_UPLOAD_MD),
        "questions": str(args.questions),
        "env": env,
        "endpoint": official.config.endpoint,
        "region": official.config.region,
        "category_id": official.config.category_id,
        "config": official.config_report(),
        "official_sdk": {
            "enabled": bool(args.use_official_sdk),
            "dependency_presence": official.dependency_presence(),
            "required_steps": [
                "ApplyFileUploadLease",
                "upload file to pre-signed URL",
                "AddFile",
                "DescribeFile until parse success",
                "CreateIndex",
                "SubmitIndexJob",
                "GetIndexJobStatus",
            ],
        },
        "record_count": payload_status["record_count"],
        "payload_status": payload_status["status"],
        "payload_errors": payload_status["errors"] + upload_md_status["errors"],
        "retrieval_status": "not_run",
        "nodes_count": 0,
        "top_score": None,
        "smoke_fact_found": False,
        "signed_url_present": False,
        "signed_url_redacted": True,
        "recall_at_1": None,
        "recall_at_3": None,
        "citation_coverage": None,
        "per_question_results": [],
        "kb_id_redacted_or_tmp_only": None,
        "cleanup_requested": bool(args.cleanup),
        "cleanup_index_id_provided": bool(args.cleanup_index_id),
        "first_failed_phase": None,
        "operation_name": None,
        "safe_error": None,
        "recommended_fix": None,
        "cleanup_recommendation": "No KB was created in dry-run mode.",
        "safety": {
            "key_printed": "no",
            "qwen": "not_used",
            "pdf": "not_uploaded",
            "raw_image": "not_uploaded",
            "full_markdown": "not_uploaded",
            "upload": "not_used",
            "knowledge_base": "not_created",
        },
    }
    if payload_status["status"] == "fail" or upload_md_status["status"] == "fail" or questions_status["status"] == "fail":
        return {**base, "status": "fail", "error_type": "upload_rejected", "summary": "payload or question validation failed"}
    rerank_error = validate_rerank_config(args.rerank_mode, args.rerank_instruct)
    if rerank_error:
        return {**base, "status": "fail", **rerank_error}
    if not args.allow_network or not args.allow_upload:
        return {
            **base,
            "status": "dry_run",
            "error_type": None,
            "summary": "dry-run only; pass both --allow-network and --allow-upload for real pilot",
        }
    if args.use_official_sdk:
        official_report = official.run_small_kb_pilot(
            upload_file=OFFICIAL_UPLOAD_MD,
            questions=load_questions(args.questions),
            allow_network=args.allow_network,
            allow_upload=args.allow_upload,
            cleanup=args.cleanup,
            cleanup_index_id=args.cleanup_index_id,
        )
        knowledge_base_created = bool(official_report.get("knowledge_base_created"))
        return {
            **base,
            "status": official_report["status"],
            "error_type": official_report.get("error_type"),
            "summary": official_report["summary"],
            "retrieval_status": official_report.get("retrieval_status", "not_run"),
            "nodes_count": official_report.get("nodes_count", 0),
            "top_score": official_report.get("top_score"),
            "smoke_fact_found": official_report.get("smoke_fact_found", False),
            "signed_url_present": official_report.get("signed_url_present", False),
            "signed_url_redacted": True,
            "recall_at_1": official_report.get("recall_at_1"),
            "recall_at_3": official_report.get("recall_at_3"),
            "citation_coverage": official_report.get("citation_coverage"),
            "per_question_results": official_report.get("per_question_results", []),
            "kb_id_redacted_or_tmp_only": official_report.get("kb_id_redacted_or_tmp_only"),
            "cleanup_requested": bool(args.cleanup),
            "cleanup_index_id_provided": bool(args.cleanup_index_id),
            "first_failed_phase": official_report.get("first_failed_phase"),
            "operation_name": official_report.get("operation_name"),
            "safe_error": official_report.get("safe_error"),
            "recommended_fix": official_report.get("recommended_fix"),
            "cleanup_attempted": official_report.get("cleanup_attempted", False),
            "cleanup_status": official_report.get("cleanup_status", "not_needed"),
            "index_cleanup": official_report.get("index_cleanup", "not_created"),
            "file_cleanup": official_report.get("file_cleanup", "not_created"),
            "created_resource_ids_cleaned": official_report.get("created_resource_ids_cleaned", "not_created"),
            "cleanup_errors": official_report.get("cleanup_errors", []),
            "cleanup_recommendation": official_report.get(
                "cleanup_recommendation",
                "No KB was created. If a manual KB is created, delete it in the Bailian console after evaluation.",
            ),
            "safety": {
                **base["safety"],
                "upload": "attempted_sanitized_payload_only" if official_report.get("upload_attempted") else "not_used",
                "knowledge_base": "created_temp_index" if knowledge_base_created else "not_created",
            },
            "official_sdk_result": official_report,
        }
    missing = [name for name in ["DASHSCOPE_API_KEY", "BAILIAN_WORKSPACE_ID"] if env.get(name) == "MISSING"]
    if missing:
        return {**base, "status": "fail", "error_type": "missing_env", "summary": "legacy placeholder env is missing; values were not printed"}
    return {
        **base,
        "status": "blocked_manual_console_required",
        "error_type": "missing_dependency_or_api_contract",
        "summary": "Bailian KB API contract is not implemented in this repo; no upload was attempted",
        "cleanup_recommendation": "No KB was created. If you create one manually, delete it in the Bailian console after evaluation.",
        "manual_console_runbook": [
            "Create a temporary document-search/basic QA knowledge base in Bailian.",
            "Upload only /tmp/bailian_small_kb_payload.jsonl or equivalent sanitized text records.",
            "Do not upload PDFs, raw images, full markdown, local paths, or secrets.",
            "Record the KB id only in /tmp, then delete the KB after the pilot.",
        ],
    }


def validate_payload(path: Path) -> dict[str, Any]:
    errors: list[str] = []
    if not path.exists():
        return {"status": "fail", "record_count": 0, "errors": [f"missing payload: {path}"]}
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    for row in rows:
        text = json.dumps(row, ensure_ascii=False)
        paper_id = row.get("paper_id", "unknown")
        if FORBIDDEN_RE.search(text):
            errors.append(f"{paper_id}: forbidden payload content")
        if row.get("needs_human_review") is not True:
            errors.append(f"{paper_id}: needs_human_review must be true")
        if row.get("trusted_for_scientific_quality") is not False:
            errors.append(f"{paper_id}: trusted_for_scientific_quality must be false")
        if row.get("upload_scope") != "small_kb_pilot":
            errors.append(f"{paper_id}: upload_scope must be small_kb_pilot")
    return {"status": "fail" if errors else "pass", "record_count": len(rows), "errors": errors}


def build_upload_markdown(jsonl_path: Path, output_path: Path) -> dict[str, Any]:
    if not jsonl_path.exists():
        return {"status": "fail", "errors": [f"missing payload jsonl: {jsonl_path}"]}
    rows = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    lines = [
        "# Review Writer Clean 3-Paper Small KB Payload",
        "",
        "review-writer Phase 6c smoke test",
        "",
    ]
    for row in rows:
        meta = row.get("metadata", {})
        lines.extend(
            [
                f"## {row.get('paper_id')}: {row.get('title')}",
                "",
                f"paper_id: {row.get('paper_id')}",
                f"title: {row.get('title')}",
                f"year: {meta.get('year')}",
                f"journal: {meta.get('journal')}",
                f"role: {meta.get('role')}",
                f"needs_human_review: {row.get('needs_human_review')}",
                f"trusted_for_scientific_quality: {row.get('trusted_for_scientific_quality')}",
                "",
                str(row.get("compact_text") or ""),
                "",
            ]
        )
    text = "\n".join(lines)
    if FORBIDDEN_RE.search(text):
        return {"status": "fail", "errors": ["official upload markdown contains forbidden content"]}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")
    return {"status": "pass", "errors": [], "path": str(output_path)}


def validate_questions(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "fail", "errors": [f"missing questions: {path}"]}
    payload = json.loads(path.read_text(encoding="utf-8"))
    questions = payload.get("questions") or []
    if len(questions) < 6:
        return {"status": "fail", "errors": ["expected at least 6 retrieval questions"]}
    return {"status": "pass", "errors": []}


def load_questions(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    questions = payload.get("questions") if isinstance(payload, dict) else payload
    return questions if isinstance(questions, list) else []


def safe_env_presence() -> dict[str, str]:
    return {
        "ALIBABA_CLOUD_ACCESS_KEY_ID": "SET" if os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_ID") else "MISSING",
        "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "SET" if os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET") else "MISSING",
        "WORKSPACE_ID": "SET" if os.environ.get("WORKSPACE_ID") else "MISSING",
        "DASHSCOPE_API_KEY": "SET" if os.environ.get("DASHSCOPE_API_KEY") else "MISSING",
        "BAILIAN_WORKSPACE_ID": "SET" if os.environ.get("BAILIAN_WORKSPACE_ID") else "MISSING",
        "BAILIAN_REGION": "SET" if os.environ.get("BAILIAN_REGION") else "MISSING_DEFAULT_CN_BEIJING",
        "BAILIAN_MODEL": "SET" if os.environ.get("BAILIAN_MODEL") else "MISSING_DEFAULT_QWEN_PLUS",
        "BAILIAN_KNOWLEDGE_BASE_ID": "SET" if os.environ.get("BAILIAN_KNOWLEDGE_BASE_ID") else "MISSING_CREATE_TEMP_IF_API_SUPPORTED",
    }


def write_outputs(report: dict[str, Any], output_json: Path, output_md: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(render_markdown(report), encoding="utf-8")


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Bailian Small KB Pilot",
        "",
        f"- status: `{report['status']}`",
        f"- error_type: `{report.get('error_type')}`",
        f"- summary: {report['summary']}",
        f"- endpoint: `{report.get('endpoint')}`",
        f"- region: `{report.get('region')}`",
        f"- category_id: `{report.get('category_id')}`",
        f"- official_upload_md: `{report.get('official_upload_md')}`",
        f"- record_count: `{report['record_count']}`",
        f"- retrieval_status: `{report['retrieval_status']}`",
        f"- nodes_count: `{report.get('nodes_count', 0)}`",
        f"- top_score: `{report.get('top_score')}`",
        f"- smoke_fact_found: `{report.get('smoke_fact_found', False)}`",
        f"- signed_url_present: `{report.get('signed_url_present', False)}`",
        f"- signed_url_redacted: `{report.get('signed_url_redacted', True)}`",
        f"- recall@1: `{report['recall_at_1']}`",
        f"- recall@3: `{report['recall_at_3']}`",
        f"- citation coverage: `{report['citation_coverage']}`",
        f"- cleanup_requested: `{report.get('cleanup_requested', False)}`",
        f"- cleanup_index_id_provided: `{report.get('cleanup_index_id_provided', False)}`",
        f"- cleanup_attempted: `{report.get('cleanup_attempted', False)}`",
        f"- cleanup_status: `{report.get('cleanup_status', 'not_needed')}`",
        f"- index_cleanup: `{report.get('index_cleanup', 'not_created')}`",
        f"- file_cleanup: `{report.get('file_cleanup', 'not_created')}`",
        f"- created_resource_ids_cleaned: `{report.get('created_resource_ids_cleaned', 'not_created')}`",
        f"- first_failed_phase: `{report.get('first_failed_phase')}`",
        f"- operation_name: `{report.get('operation_name')}`",
        f"- recommended_fix: {report.get('recommended_fix')}",
        f"- cleanup: {report['cleanup_recommendation']}",
        "",
        "## Environment Presence",
    ]
    lines.extend(f"- {key}: {value}" for key, value in report["env"].items())
    if report.get("manual_console_runbook"):
        lines.extend(["", "## Manual Console Runbook"])
        lines.extend(f"- {step}" for step in report["manual_console_runbook"])
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
