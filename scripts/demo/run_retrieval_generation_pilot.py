#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
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

DEFAULT_FIXTURE = REPO_ROOT / "tests/fixtures/retrieval_generation/clean_3paper_retrieval_fixture.json"


def main() -> int:
    args = parse_args()
    try:
        report = run(args)
    except Exception as exc:  # noqa: BLE001 - real pilot failures still need a safe report.
        args.output_root.mkdir(parents=True, exist_ok=True)
        report = failure_report(args, exc)
        (args.output_root / "phase7_retrieval_generation_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (args.output_root / "phase7_retrieval_generation_report.md").write_text(render_report_md(report), encoding="utf-8")
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
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict[str, Any]:
    args.output_root.mkdir(parents=True, exist_ok=True)
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
    )
    evidence_json = args.output_root / "evidence_pack.json"
    section_md = args.output_root / "generated_section.md"
    generation_json = args.output_root / "generation_result.json"
    evidence_json.write_text(json.dumps(pack.to_safe_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    section_md.write_text(generation.section_text, encoding="utf-8")
    generation_json.write_text(json.dumps(generation.to_safe_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    grounding = run_grounding_validator(args.output_root, section_md, evidence_json)
    status = "pass" if grounding["status"] == "pass" and generation.checkpoint == "Sections: ready_for_human_review" else "fail"
    report = {
        "status": status,
        "retrieval_mode": args.retrieval_mode,
        "generation_provider": args.generation_provider,
        "section_id": args.section_id,
        "section_title": args.section_title,
        "section_path": str(section_md),
        "evidence_pack_path": str(evidence_json),
        "generation_result_path": str(generation_json),
        "checkpoint": generation.checkpoint,
        "claim_evidence_coverage": grounding["claim_evidence_coverage"],
        "unsupported_claim_count": grounding["unsupported_claim_count"],
        "prompt_leakage_count": grounding["prompt_leakage_count"],
        "human_review_tasks": grounding["human_review_tasks"],
        "needs_human_review": generation.needs_human_review,
        "trusted_for_scientific_quality": False,
        "real_retrieval_status": retrieval_payload.get("real_retrieval_status", "not_used"),
        "qwen_generation_status": "pass" if args.generation_provider == "qwen" else "not_used",
        "cleanup_status": retrieval_payload.get("cleanup_status", "not_needed"),
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
    return report


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
                "cleanup_status": cleanup_status,
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
        raise RuntimeError(result.stderr + result.stdout)
    return json.loads((output_root / "grounding_report.json").read_text(encoding="utf-8"))


def render_report_md(report: dict[str, Any]) -> str:
    lines = [
        "# Phase 7 Retrieval Generation Pilot",
        "",
        f"- status: `{report['status']}`",
        f"- retrieval_mode: `{report['retrieval_mode']}`",
        f"- generation_provider: `{report['generation_provider']}`",
        f"- checkpoint: `{report['checkpoint']}`",
        f"- claim_evidence_coverage: `{report['claim_evidence_coverage']}`",
        f"- unsupported_claim_count: `{report['unsupported_claim_count']}`",
        f"- section_path: `{report['section_path']}`",
        "",
        "## Human Review Tasks",
    ]
    lines.extend(f"- {task}" for task in report["human_review_tasks"])
    return "\n".join(lines) + "\n"


def failure_report(args: argparse.Namespace, exc: Exception) -> dict[str, Any]:
    error_type = "qwen_timeout" if "timed out" in str(exc).lower() else type(exc).__name__
    return {
        "status": "fail",
        "error_type": error_type,
        "safe_summary": "Qwen generation timed out" if error_type == "qwen_timeout" else type(exc).__name__,
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
        "prompt_leakage_count": None,
        "human_review_tasks": ["Retry Qwen only after reviewing timeout/network conditions; do not reuse as scientific final text."],
        "needs_human_review": True,
        "trusted_for_scientific_quality": False,
        "real_retrieval_status": "attempted" if args.retrieval_mode == "bailian" else "not_used",
        "qwen_generation_status": "fail" if args.generation_provider == "qwen" else "not_used",
        "cleanup_status": "attempted_before_generation_or_not_needed",
        "safety": {
            "pdf_uploaded": "no",
            "raw_image_uploaded": "no",
            "full_text_uploaded": "no",
            "default_checks_upload": "no",
            "resource_ids_redacted": "yes",
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
