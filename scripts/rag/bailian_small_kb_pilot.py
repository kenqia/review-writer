#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

FORBIDDEN_RE = re.compile(r"(\.pdf\b|\.png\b|\.jpe?g\b|\.webp\b|/home/|/mnt/|[A-Za-z]:\\Users\\|api[_-]?key|token|secret|sk-)", re.I)


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
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--allow-upload", action="store_true")
    parser.add_argument("--cleanup", action="store_true")
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def run_pilot(args: argparse.Namespace) -> dict[str, Any]:
    payload_status = validate_payload(args.payload_jsonl)
    questions_status = validate_questions(args.questions)
    env = safe_env_presence()
    base = {
        "payload_jsonl": str(args.payload_jsonl),
        "questions": str(args.questions),
        "env": env,
        "record_count": payload_status["record_count"],
        "payload_status": payload_status["status"],
        "payload_errors": payload_status["errors"],
        "retrieval_status": "not_run",
        "recall_at_1": None,
        "recall_at_3": None,
        "citation_coverage": None,
        "per_question_results": [],
        "kb_id_redacted_or_tmp_only": None,
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
    if payload_status["status"] == "fail" or questions_status["status"] == "fail":
        return {**base, "status": "fail", "error_type": "upload_rejected", "summary": "payload or question validation failed"}
    if not args.allow_network or not args.allow_upload:
        return {
            **base,
            "status": "dry_run",
            "error_type": None,
            "summary": "dry-run only; pass both --allow-network and --allow-upload for real pilot",
        }
    missing = [name for name in ["DASHSCOPE_API_KEY", "BAILIAN_WORKSPACE_ID"] if env[name] == "MISSING"]
    if missing:
        return {**base, "status": "fail", "error_type": "missing_env", "summary": "required env is missing; values were not printed"}
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


def validate_questions(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "fail", "errors": [f"missing questions: {path}"]}
    payload = json.loads(path.read_text(encoding="utf-8"))
    questions = payload.get("questions") or []
    if len(questions) < 6:
        return {"status": "fail", "errors": ["expected at least 6 retrieval questions"]}
    return {"status": "pass", "errors": []}


def safe_env_presence() -> dict[str, str]:
    return {
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
        f"- record_count: `{report['record_count']}`",
        f"- retrieval_status: `{report['retrieval_status']}`",
        f"- recall@1: `{report['recall_at_1']}`",
        f"- recall@3: `{report['recall_at_3']}`",
        f"- citation coverage: `{report['citation_coverage']}`",
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

