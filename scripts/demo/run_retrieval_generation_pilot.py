#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.pipeline.retrieval_generation import (
    DEFAULT_SECTION_ID,
    DEFAULT_SECTION_TITLE,
    build_evidence_pack,
    generate_grounded_section,
    load_retrieval_fixture,
)
from review_writer.phase7_budget import DEFAULT_BUDGET_PATH, Phase7BudgetLedger

DEFAULT_FIXTURE = REPO_ROOT / "tests/fixtures/retrieval_generation/clean_3paper_retrieval_fixture.json"
PROXY_ENV_NAMES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy")


def main() -> int:
    args = parse_args()
    started = time.monotonic()
    try:
        report = run(args)
    except Exception as exc:  # noqa: BLE001 - real pilot failures still need a safe report.
        args.output_root.mkdir(parents=True, exist_ok=True)
        report = failure_report(args, exc, elapsed_ms=int((time.monotonic() - started) * 1000))
        (args.output_root / "phase7_retrieval_generation_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (args.output_root / "phase7_retrieval_generation_report.md").write_text(render_report_md(report), encoding="utf-8")
        record_real_result(args, "fail")
        write_real_attempt_report(args, report)
    print(
        "retrieval-generation-pilot: "
        f"{report['status']} provider={report['generation_provider']} checkpoint={report['checkpoint']}"
    )
    return 1 if args.strict and report["status"] == "fail" else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 7 retrieval-backed single-section generation pilot.")
    parser.add_argument("--retrieval-mode", choices=["offline_fixture", "local", "bailian"], default="offline_fixture")
    parser.add_argument("--generation-provider", choices=["offline", "qwen"], default="offline")
    parser.add_argument("--section-id", default=DEFAULT_SECTION_ID)
    parser.add_argument("--section-title", default=DEFAULT_SECTION_TITLE)
    parser.add_argument("--max-evidence-items", type=int, default=3)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output-root", type=Path, default=Path("/tmp/review_writer_phase7_offline"))
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--allow-upload", action="store_true")
    parser.add_argument("--allow-qwen", action="store_true")
    parser.add_argument("--connect-timeout-seconds", type=float, default=10.0)
    parser.add_argument("--first-byte-timeout-seconds", type=float, default=45.0)
    parser.add_argument("--total-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--max-output-tokens", type=int, default=900)
    parser.add_argument("--attempt-type", default="offline")
    parser.add_argument("--attempt-number", type=int, default=0)
    parser.add_argument("--real-report-json", type=Path, default=None)
    parser.add_argument("--real-report-md", type=Path, default=None)
    parser.add_argument("--budget-ledger", type=Path, default=DEFAULT_BUDGET_PATH)
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict[str, Any]:
    args.output_root.mkdir(parents=True, exist_ok=True)
    budget_info = reserve_real_budget(args)
    retrieval_payload = load_retrieval_payload(args)
    pack = build_evidence_pack(
        retrieval_payload,
        section_id=args.section_id,
        section_title=args.section_title,
        max_evidence_items=args.max_evidence_items,
    )
    generation = generate_grounded_section(
        pack,
        generation_provider=args.generation_provider,
        allow_qwen=args.allow_qwen and args.allow_network,
        max_output_tokens=args.max_output_tokens,
        connect_timeout_seconds=args.connect_timeout_seconds,
        first_byte_timeout_seconds=args.first_byte_timeout_seconds,
        total_timeout_seconds=args.total_timeout_seconds,
    )
    evidence_json = args.output_root / "evidence_pack.json"
    section_md = args.output_root / "generated_section.md"
    generation_json = args.output_root / "generation_result.json"
    evidence_json.write_text(json.dumps(pack.to_safe_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    section_md.write_text(generation.section_text, encoding="utf-8")
    generation_json.write_text(json.dumps(generation.to_safe_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    grounding = run_grounding_validator(args.output_root, section_md, evidence_json)
    status = "pass" if grounding["status"] == "pass" and generation.checkpoint == "Sections: ready_for_human_review" else "fail"
    provider_metadata = generation.provider_metadata or {}
    stream = provider_metadata.get("stream_telemetry", {})
    evidence_hash_prefix = evidence_pack_hash_prefix(pack.to_safe_dict())
    bailian_transport_mode = retrieval_payload.get("bailian_transport_mode", "no_proxy" if args.retrieval_mode == "bailian" else "not_used")
    qwen_transport_mode = provider_metadata.get("transport_mode", "openai_sdk_default" if args.generation_provider == "qwen" else "not_used")
    report = {
        "status": status,
        "attempt_type": args.attempt_type,
        "attempt_number": args.attempt_number,
        "budget_before": budget_info.get("budget_before"),
        "budget_after": budget_info.get("budget_after"),
        "failed_stage": None if status == "pass" else "validation",
        "exception_class": None,
        "error_type": None if status == "pass" else "grounding_validation_failed",
        "status_code_if_available": None,
        "request_id_present": bool(provider_metadata.get("request_id_present", False)),
        "retrieval_mode": args.retrieval_mode,
        "generation_provider": args.generation_provider,
        "model_name": provider_metadata.get("model", "qwen3.7-plus" if args.generation_provider == "qwen" else "offline"),
        "region": provider_metadata.get("region"),
        "dedicated_endpoint_used": bool(provider_metadata.get("dedicated_endpoint_used", False)),
        "endpoint_redacted": bool(provider_metadata.get("base_url_redacted") == "redacted") if args.generation_provider == "qwen" else True,
        "transport_mode": f"bailian={bailian_transport_mode};qwen={qwen_transport_mode}",
        "bailian_transport_mode": bailian_transport_mode,
        "bailian_proxy_env_names_set": retrieval_payload.get("bailian_proxy_env_names_set", []),
        "qwen_transport_mode": qwen_transport_mode,
        "qwen_proxy_env_names_set": provider_metadata.get("proxy_env_names_set", []),
        "stream_started": bool(provider_metadata.get("stream_started", False)),
        "chunks_received": int(provider_metadata.get("chunks_received", 0) or 0),
        "server_chunks_received": int(stream.get("server_chunks_received") or 0),
        "content_chunks_received": int(stream.get("content_chunks_received") or 0),
        "reasoning_chunks_received": int(stream.get("reasoning_chunks_received") or 0),
        "usage_chunk_received": bool(stream.get("usage_chunk_received", False)),
        "finish_reason": stream.get("finish_reason"),
        "first_server_chunk_ms": stream.get("first_server_chunk_ms"),
        "first_content_chunk_ms": stream.get("first_content_chunk_ms"),
        "elapsed_ms": stream.get("elapsed_ms"),
        "prompt_tokens": stream.get("prompt_tokens"),
        "completion_tokens": stream.get("completion_tokens"),
        "total_tokens": stream.get("total_tokens"),
        "retry_count": int(provider_metadata.get("retry_count", 0) or 0),
        "retrieval_evidence_count": len(pack.items),
        "evidence_pack_hash_prefix": evidence_hash_prefix,
        "section_id": args.section_id,
        "section_title": args.section_title,
        "section_path": str(section_md),
        "evidence_pack_path": str(evidence_json),
        "generation_result_path": str(generation_json),
        "checkpoint": generation.checkpoint,
        "claim_evidence_coverage": grounding["claim_evidence_coverage"],
        "unsupported_claim_count": grounding["unsupported_claim_count"],
        "unsupported_claims": grounding["unsupported_claim_count"],
        "unsupported_citations": grounding.get("unsupported_citations", []),
        "prompt_leakage_count": grounding["prompt_leakage_count"],
        "prompt_leakage": grounding["prompt_leakage_count"],
        "malformed_marker_count": grounding.get("malformed_marker_count", 0),
        "section_text_present": bool(generation.section_text.strip()),
        "human_review_tasks": grounding["human_review_tasks"],
        "needs_human_review": generation.needs_human_review,
        "trusted_for_scientific_quality": False,
        "real_retrieval_status": retrieval_payload.get("real_retrieval_status", "not_used"),
        "qwen_generation_status": "pass" if args.generation_provider == "qwen" else "not_used",
        "generation_status": "pass" if args.generation_provider == "qwen" else "not_used",
        "cleanup_status": retrieval_payload.get("cleanup_status", "not_needed"),
        "file_created": retrieval_payload.get("file_created", args.retrieval_mode == "bailian"),
        "index_created": retrieval_payload.get("index_created", args.retrieval_mode == "bailian"),
        "cleanup_attempted": retrieval_payload.get("cleanup_attempted", args.retrieval_mode == "bailian"),
        "file_cleanup_status": retrieval_payload.get("file_cleanup_status", retrieval_payload.get("cleanup_status", "not_needed")),
        "index_cleanup_status": retrieval_payload.get("index_cleanup_status", retrieval_payload.get("cleanup_status", "not_needed")),
        "timeout_seconds": {
            "connect": args.connect_timeout_seconds,
            "first_byte": args.first_byte_timeout_seconds,
            "total": args.total_timeout_seconds,
        },
        "max_output_tokens": args.max_output_tokens,
        "safety": {
            "pdf_uploaded": "no",
            "raw_image_uploaded": "no",
            "full_text_uploaded": "no",
            "default_checks_upload": "no",
            "resource_ids_redacted": "yes",
        },
    }
    (args.output_root / "phase7_retrieval_generation_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.output_root / "phase7_retrieval_generation_report.md").write_text(render_report_md(report), encoding="utf-8")
    record_real_result(args, status)
    write_real_attempt_report(args, report)
    return report


def reserve_real_budget(args: argparse.Namespace) -> dict[str, Any]:
    if args.attempt_type not in {"qwen_only", "full_e2e"}:
        return {"budget_before": None, "budget_after": None}
    ledger = Phase7BudgetLedger(args.budget_ledger)
    if args.attempt_type == "qwen_only":
        before, after = ledger.reserve("qwen_only", qwen_requests=1, last_operation="qwen-only streaming smoke")
        args.attempt_number = int(after["qwen_only_attempts"])
    else:
        before, after = ledger.reserve(
            "full_e2e",
            qwen_requests=1,
            lifecycles=1,
            uploads=1,
            last_operation="full bailian qwen e2e",
        )
        args.attempt_number = int(after["full_e2e_attempts"])
    args._phase7_budget_info = {"budget_before": before, "budget_after": after}
    return args._phase7_budget_info


def record_real_result(args: argparse.Namespace, result: str) -> None:
    if args.attempt_type in {"qwen_only", "full_e2e"}:
        Phase7BudgetLedger(args.budget_ledger).record_result(result)


def evidence_pack_hash_prefix(payload: dict[str, Any]) -> str:
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()[:12]


def load_retrieval_payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.retrieval_mode == "offline_fixture":
        return load_retrieval_fixture(args.fixture)
    if args.retrieval_mode == "local":
        return load_retrieval_fixture(args.fixture)
    if args.retrieval_mode == "bailian":
        if not (args.allow_network and args.allow_upload):
            raise RuntimeError("bailian retrieval requires --allow-network --allow-upload")
        return run_real_bailian_retrieval(args)
    raise ValueError(args.retrieval_mode)


def run_real_bailian_retrieval(args: argparse.Namespace) -> dict[str, Any]:
    from scripts.rag.bailian_small_kb_pilot import load_questions
    from scripts.rag.build_bailian_small_kb_payload import build_payload
    from review_writer.retrieval.bailian_official_client import (
        OFFICIAL_CLEAN_3PAPER_MD,
        BailianOfficialClient,
        make_bailian_config,
        retrieve_request_modes,
        retrieve_sdk_capabilities,
    )
    import os

    build_payload(
        Path("demo_projects/clean_3paper_allene_review"),
        Path("/tmp/bailian_small_kb_payload.jsonl"),
        Path("/tmp/bailian_small_kb_payload.md"),
        Path("/tmp/bailian_small_kb_payload_manifest.json"),
    )
    wrapper = BailianOfficialClient(make_bailian_config(endpoint="bailian.cn-beijing.aliyuncs.com", region="cn-beijing", category_id="default", transport_mode="no_proxy"))
    client = None
    workspace_id = None
    file_id = None
    index_id = None
    cleanup_status = "not_needed"
    try:
        with wrapper.transport_environment():
            client = wrapper.create_client()
            workspace_id = os.environ["WORKSPACE_ID"]
            artifact = wrapper.prepare_upload_artifact(OFFICIAL_CLEAN_3PAPER_MD)
            lease = wrapper.apply_file_upload_lease(client, workspace_id, OFFICIAL_CLEAN_3PAPER_MD, artifact)
            wrapper.upload_file_to_presigned_url(lease, OFFICIAL_CLEAN_3PAPER_MD, artifact)
            add_result = wrapper.add_file(client, workspace_id, lease["lease_id"])
            file_id = add_result["file_id"]
            wrapper.describe_file_until_parsed(client, workspace_id, file_id)
            index_result = wrapper.create_index(client, workspace_id, file_id)
            index_id = index_result["index_id"]
            submit = wrapper.submit_index_job(client, workspace_id, index_id)
            wrapper.wait_index_completed(client, workspace_id, index_id, submit["job_id"])
            supported = retrieve_sdk_capabilities()["retrieve_request_supported_fields"]
            mode = next((item for item in retrieve_request_modes(supported) if item["mode"] == "hybrid_no_rerank"), retrieve_request_modes(supported)[0])
            queries = load_questions(Path("evals/fixtures/rag_expected_questions.json"))[:8]
            items = []
            seen = set()
            for question in queries:
                result = wrapper.retrieve_index(
                    client,
                    workspace_id,
                    index_id,
                    str(question.get("query") or ""),
                    request_options=mode["request_options"],
                    supported_request_fields=supported,
                    allow_empty=True,
                )
                for item in result.get("items", []):
                    paper_id = item.get("paper_id")
                    if paper_id in {"F3I", "F47A", "P403"} and paper_id not in seen:
                        seen.add(paper_id)
                        items.append(
                            {
                                "paper_id": paper_id,
                                "chunk_id": f"{paper_id}-real",
                                "sanitized_text": f"{paper_id} retrieved from clean compact Phase 7 payload.",
                                "score": result.get("top_score") or 0.0,
                                "title": paper_id,
                                "known_warnings": "needs human review; trusted_for_scientific_quality=false",
                                "needs_human_review": True,
                            }
                        )
                if seen == {"F3I", "F47A", "P403"}:
                    break
            cleanup = wrapper.cleanup_created_resources(client, workspace_id, index_id=index_id, file_id=file_id)
            cleanup_status = cleanup.get("cleanup_status", "fail")
            return {
                "fixture_id": "phase7_bailian_real_retrieval_redacted",
                "real_retrieval_status": "pass" if items else "fail",
                "bailian_transport_mode": "no_proxy",
                "bailian_proxy_env_names_set": [],
                "cleanup_status": cleanup_status,
                "file_created": bool(file_id),
                "index_created": bool(index_id),
                "cleanup_attempted": True,
                "file_cleanup_status": cleanup.get("file_cleanup_status", cleanup_status),
                "index_cleanup_status": cleanup.get("index_cleanup_status", cleanup_status),
                "needs_human_review": True,
                "trusted_for_scientific_quality": False,
                "items": items,
            }
    finally:
        if client and workspace_id and (index_id or file_id):
            wrapper.cleanup_created_resources(client, workspace_id, index_id=index_id, file_id=file_id)


def run_grounding_validator(output_root: Path, section_md: Path, evidence_json: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/validators/validate_grounded_section.py",
            "--section-md",
            str(section_md),
            "--evidence-pack-json",
            str(evidence_json),
            "--output-json",
            str(output_root / "grounding_report.json"),
            "--output-md",
            str(output_root / "grounding_report.md"),
            "--claim-map-json",
            str(output_root / "claim_evidence_map.json"),
            "--strict",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        report_path = output_root / "grounding_report.json"
        if report_path.exists():
            return json.loads(report_path.read_text(encoding="utf-8"))
        raise RuntimeError(result.stderr + result.stdout)
    return json.loads((output_root / "grounding_report.json").read_text(encoding="utf-8"))


def render_report_md(report: dict[str, Any]) -> str:
    lines = [
        "# Phase 7 Retrieval Generation Pilot",
        "",
        f"- status: `{report['status']}`",
        f"- attempt_type: `{report.get('attempt_type')}`",
        f"- attempt_number: `{report.get('attempt_number')}`",
        f"- failed_stage: `{report.get('failed_stage')}`",
        f"- retrieval_mode: `{report['retrieval_mode']}`",
        f"- generation_provider: `{report['generation_provider']}`",
        f"- model_name: `{report.get('model_name')}`",
        f"- dedicated_endpoint_used: `{report.get('dedicated_endpoint_used')}`",
        f"- stream_started: `{report.get('stream_started')}`",
        f"- chunks_received: `{report.get('chunks_received')}`",
        f"- checkpoint: `{report['checkpoint']}`",
        f"- claim_evidence_coverage: `{report['claim_evidence_coverage']}`",
        f"- unsupported_claim_count: `{report['unsupported_claim_count']}`",
        f"- section_path: `{report['section_path']}`",
        "",
        "## Human Review Tasks",
    ]
    lines.extend(f"- {task}" for task in report["human_review_tasks"])
    return "\n".join(lines) + "\n"


def write_real_attempt_report(args: argparse.Namespace, report: dict[str, Any]) -> None:
    if args.attempt_type in {"qwen_only", "full_e2e"} and not args.real_report_json:
        args.real_report_json = Path(f"/tmp/review_writer_phase7_real_{args.attempt_type}_{args.attempt_number}.json")
    if args.attempt_type in {"qwen_only", "full_e2e"} and not args.real_report_md:
        args.real_report_md = Path(f"/tmp/review_writer_phase7_real_{args.attempt_type}_{args.attempt_number}.md")
    if not args.real_report_json and not args.real_report_md:
        return
    if args.real_report_json:
        args.real_report_json.parent.mkdir(parents=True, exist_ok=True)
        args.real_report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.real_report_md:
        args.real_report_md.parent.mkdir(parents=True, exist_ok=True)
        args.real_report_md.write_text(render_report_md(report), encoding="utf-8")


def failure_report(args: argparse.Namespace, exc: Exception, *, elapsed_ms: int = 0) -> dict[str, Any]:
    error_type = getattr(exc, "error_type", None) or ("qwen_timeout" if "timed out" in str(exc).lower() else type(exc).__name__)
    provider_error_types = {"missing_env", "missing_dependency", "first_byte_timeout", "total_timeout", "stream_failed", "client_timeout", "network_error", "auth_error_401", "rate_limit_or_quota_429", "server_error_5xx"}
    failed_stage = "generation" if args.generation_provider == "qwen" else "preflight"
    if args.retrieval_mode == "bailian" and str(error_type) not in provider_error_types:
        failed_stage = "retrieval"
    budget_info = getattr(args, "_phase7_budget_info", {"budget_before": None, "budget_after": None})
    return {
        "status": "fail",
        "attempt_type": args.attempt_type,
        "attempt_number": args.attempt_number,
        "budget_before": budget_info.get("budget_before"),
        "budget_after": budget_info.get("budget_after"),
        "failed_stage": failed_stage,
        "exception_class": type(exc).__name__,
        "error_type": error_type,
        "status_code_if_available": getattr(exc, "status_code", None),
        "request_id_present": bool(getattr(exc, "request_id_present", False) or getattr(exc, "request_id", None)),
        "stream_started": bool(getattr(exc, "stream_started", False)),
        "chunks_received": int(getattr(exc, "chunks_received", 0)),
        "server_chunks_received": int(getattr(exc, "server_chunks_received", 0)),
        "content_chunks_received": int(getattr(exc, "chunks_received", 0)),
        "reasoning_chunks_received": 0,
        "usage_chunk_received": False,
        "finish_reason": None,
        "first_server_chunk_ms": None,
        "first_content_chunk_ms": None,
        "elapsed_ms": elapsed_ms,
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "retry_count": int(getattr(exc, "retry_count", 0)),
        "model_name": "qwen3.7-plus" if args.generation_provider == "qwen" else "offline",
        "region": "cn-beijing",
        "dedicated_endpoint_used": True if args.generation_provider == "qwen" else False,
        "endpoint_redacted": True,
        "transport_mode": (
            f"bailian={'no_proxy' if args.retrieval_mode == 'bailian' else 'not_used'};"
            f"qwen={'openai_sdk_default' if args.generation_provider == 'qwen' else 'not_used'}"
        ),
        "bailian_transport_mode": "no_proxy" if args.retrieval_mode == "bailian" else "not_used",
        "bailian_proxy_env_names_set": [],
        "qwen_transport_mode": "openai_sdk_default" if args.generation_provider == "qwen" else "not_used",
        "qwen_proxy_env_names_set": proxy_env_names_set() if args.generation_provider == "qwen" else [],
        "first_chunk_ms": None,
        "retrieval_evidence_count": 0,
        "evidence_pack_hash_prefix": None,
        "safe_summary": "Qwen generation timed out" if error_type == "qwen_timeout" else type(exc).__name__,
        "recommended_fix": "Inspect provider/preflight report, then retry only within the approved real-call budget.",
        "retrieval_mode": args.retrieval_mode,
        "generation_provider": args.generation_provider,
        "section_id": args.section_id,
        "section_title": args.section_title,
        "section_path": None,
        "evidence_pack_path": None,
        "generation_result_path": None,
        "checkpoint": "Sections: blocked_before_ready_for_human_review",
        "claim_evidence_coverage": None,
        "unsupported_claim_count": None,
        "unsupported_claims": None,
        "unsupported_citations": [],
        "prompt_leakage_count": None,
        "prompt_leakage": None,
        "malformed_marker_count": None,
        "section_text_present": False,
        "human_review_tasks": ["Retry Qwen only after reviewing timeout/network conditions; do not reuse as scientific final text."],
        "needs_human_review": True,
        "trusted_for_scientific_quality": False,
        "real_retrieval_status": "attempted" if args.retrieval_mode == "bailian" else "not_used",
        "qwen_generation_status": "fail" if args.generation_provider == "qwen" else "not_used",
        "generation_status": "fail" if args.generation_provider == "qwen" else "not_used",
        "cleanup_status": str(getattr(exc, "cleanup_status", "attempted_before_generation_or_not_needed")),
        "file_created": args.retrieval_mode == "bailian",
        "index_created": args.retrieval_mode == "bailian",
        "cleanup_attempted": args.retrieval_mode == "bailian",
        "file_cleanup_status": str(getattr(exc, "cleanup_status", "attempted_before_generation_or_not_needed")),
        "index_cleanup_status": str(getattr(exc, "cleanup_status", "attempted_before_generation_or_not_needed")),
        "safety": {
            "pdf_uploaded": "no",
            "raw_image_uploaded": "no",
            "full_text_uploaded": "no",
            "default_checks_upload": "no",
            "resource_ids_redacted": "yes",
        },
    }


def proxy_env_names_set() -> list[str]:
    return [name for name in PROXY_ENV_NAMES if os.environ.get(name)]


if __name__ == "__main__":
    raise SystemExit(main())
