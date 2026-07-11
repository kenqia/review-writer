#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.retrieval.bailian_official_client import (
    BailianOfficialClient,
    BailianPilotError,
    classify_retrieval_root_cause,
    evaluate_retrieve_nodes,
    make_bailian_config,
    retrieve_matrix_queries,
    retrieve_request_modes,
    retrieve_sdk_capabilities,
)
from scripts.rag.local_retrieval_baseline import run_baseline


def main() -> int:
    args = parse_args()
    report = run(args)
    write_outputs(report, args.output_json, args.output_md)
    print(
        "bailian-retrieval-qa: "
        f"{report['status']} root_cause={report['root_cause_classification']} "
        f"smoke_hit={report['smoke_fact_found']}"
    )
    return 1 if args.strict and report["status"] == "fail" else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run safe Bailian Retrieve query/mode matrix against one temp index.")
    parser.add_argument("--index-id")
    parser.add_argument("--index-id-from", type=Path)
    parser.add_argument("--questions", type=Path, default=Path("evals/fixtures/rag_expected_questions.json"))
    parser.add_argument("--manifest", type=Path, default=Path("/tmp/bailian_no_upload_corpus_manifest.json"))
    parser.add_argument("--output-json", type=Path, default=Path("/tmp/bailian_retrieval_qa.json"))
    parser.add_argument("--output-md", type=Path, default=Path("/tmp/bailian_retrieval_qa.md"))
    parser.add_argument("--endpoint")
    parser.add_argument("--region")
    parser.add_argument("--category-id", default="default")
    parser.add_argument("--transport-mode", choices=["inherited_proxy", "no_proxy", "explicit_proxy"], default="inherited_proxy")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--use-official-sdk", action="store_true")
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict[str, Any]:
    index_id = args.index_id or load_index_id(args.index_id_from)
    capabilities = retrieve_sdk_capabilities()
    supported = capabilities["retrieve_request_supported_fields"]
    if any(capabilities["modules"].values()) and all(status == "MISSING" for status in capabilities["modules"].values()):
        supported = {}
    modes = retrieve_request_modes(supported)
    base = {
        "index_id": "[REDACTED_TMP_ONLY]" if index_id else None,
        "index_id_present": bool(index_id),
        "allow_network": bool(args.allow_network),
        "official_sdk_enabled": bool(args.use_official_sdk),
        "retrieve_request_supported_fields": supported,
        "matrix_queries": retrieve_matrix_queries(),
        "matrix_modes": [{"mode": mode["mode"], "request_fields": sorted(mode["request_options"].keys())} for mode in modes],
        "matrix_results": [],
        "working_query": None,
        "working_retrieval_mode": None,
        "smoke_fact_found": False,
        "nodes_count": 0,
        "top_score": None,
        "recall_at_1": None,
        "recall_at_3": None,
        "citation_coverage": None,
        "missed_questions": [],
        "root_cause_classification": "retrieve_service_or_index_content_mismatch",
        "safety": {
            "pdf": "not_uploaded",
            "raw_image": "not_uploaded",
            "full_markdown": "not_uploaded",
            "signed_url_redacted": True,
            "resource_ids_redacted": True,
        },
    }
    if not index_id:
        return {**base, "status": "fail", "error_type": "missing_index_id"}
    if not args.allow_network or not args.use_official_sdk:
        matrix = dry_run_matrix(modes)
        metrics = safe_local_metrics(args.manifest, args.questions)
        return finalize_report(base, matrix, metrics, status="dry_run", error_type=None)
    matrix = real_matrix(args, index_id, modes, supported)
    metrics = real_clean_metrics(args, index_id, modes, supported)
    status = "pass" if any(row.get("smoke_fact_found") for row in matrix) else "fail"
    return finalize_report(base, matrix, metrics, status=status, error_type=None if status == "pass" else "retrieve_fact_miss")


def dry_run_matrix(modes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for query in retrieve_matrix_queries():
        for mode in modes:
            nodes = dry_nodes_for_query(query["query_id"])
            evaluation = evaluate_retrieve_nodes(nodes)
            results.append(
                matrix_row(
                    query_id=query["query_id"],
                    query=query["query"],
                    mode=mode["mode"],
                    request_fields=sorted(["index_id", "query", *mode["request_options"].keys()]),
                    evaluation=evaluation,
                    status="ok",
                    request_id_present=True,
                    readiness_checks=0,
                )
            )
    return results


def dry_nodes_for_query(query_id: str) -> list[dict[str, Any]]:
    if query_id in {"Q1_exact", "Q4_expected_answer"}:
        return [{"Text": "Project name: review-writer Phase 6c smoke test.", "Score": 0.99}]
    return [{"Text": "Review Writer Bailian Smoke Test", "Score": 0.65, "Metadata": {"content": "title-only dry run"}}]


def real_matrix(
    args: argparse.Namespace,
    index_id: str,
    modes: list[dict[str, Any]],
    supported: dict[str, bool],
) -> list[dict[str, Any]]:
    client_wrapper = BailianOfficialClient(
        make_bailian_config(
            endpoint=args.endpoint,
            region=args.region,
            category_id=args.category_id,
            transport_mode=args.transport_mode,
        )
    )
    results: list[dict[str, Any]] = []
    with client_wrapper.transport_environment():
        sdk_client = client_wrapper.create_client()
        workspace_id = os.environ["WORKSPACE_ID"]
        for query in retrieve_matrix_queries():
            for mode in modes:
                attempts = 0
                while True:
                    try:
                        retrieved = client_wrapper.retrieve_index(
                            sdk_client,
                            workspace_id,
                            index_id,
                            query["query"],
                            request_options=mode["request_options"],
                            supported_request_fields=supported,
                            allow_empty=True,
                        )
                        row = matrix_row(
                            query_id=query["query_id"],
                            query=query["query"],
                            mode=mode["mode"],
                            request_fields=retrieved.get("retrieve_request_fields", []),
                            evaluation=retrieved,
                            status="ok",
                            request_id_present=bool(retrieved.get("request_id_present")),
                            readiness_checks=attempts,
                        )
                    except BailianPilotError as exc:
                        row = error_row(query["query_id"], query["query"], mode["mode"], exc.error_type, attempts)
                    if row["nodes_count"] or attempts >= 3:
                        results.append(row)
                        break
                    attempts += 1
                    time.sleep(10)
    return results


def real_clean_metrics(
    args: argparse.Namespace,
    index_id: str,
    modes: list[dict[str, Any]],
    supported: dict[str, bool],
) -> dict[str, Any]:
    questions = json.loads(args.questions.read_text(encoding="utf-8")).get("questions") or []
    mode = next((item for item in modes if item["mode"] == "hybrid_no_rerank"), modes[0])
    client_wrapper = BailianOfficialClient(
        make_bailian_config(
            endpoint=args.endpoint,
            region=args.region,
            category_id=args.category_id,
            transport_mode=args.transport_mode,
        )
    )
    per_question = []
    hit1 = 0
    hit3 = 0
    citation = 0
    with client_wrapper.transport_environment():
        sdk_client = client_wrapper.create_client()
        workspace_id = os.environ["WORKSPACE_ID"]
        for question in questions:
            retrieved = client_wrapper.retrieve_index(
                sdk_client,
                workspace_id,
                index_id,
                str(question.get("query") or question.get("question") or ""),
                request_options=mode["request_options"],
                supported_request_fields=supported,
                allow_empty=True,
            )
            top_ids = [item["paper_id"] for item in retrieved.get("items", []) if item.get("paper_id")][:3]
            expected = [str(item) for item in question.get("expected_paper_ids", [])]
            q_hit1 = bool(top_ids[:1] and top_ids[0] in expected)
            q_hit3 = bool(any(item in expected for item in top_ids))
            hit1 += int(q_hit1)
            hit3 += int(q_hit3)
            citation += int(bool(top_ids))
            per_question.append(
                {
                    "question_id": question.get("question_id"),
                    "expected_paper_ids": expected,
                    "retrieved_paper_ids_top3": top_ids,
                    "hit_at_1": q_hit1,
                    "hit_at_3": q_hit3,
                }
            )
    total = len(questions)
    missed = [row for row in per_question if not row["hit_at_3"]]
    return {
        "recall_at_1": round(hit1 / total, 4) if total else None,
        "recall_at_3": round(hit3 / total, 4) if total else None,
        "citation_coverage": round(citation / total, 4) if total else None,
        "per_question_results": per_question,
        "missed_questions": missed,
    }


def safe_local_metrics(manifest: Path, questions: Path) -> dict[str, Any]:
    return run_baseline(manifest, questions)


def matrix_row(
    *,
    query_id: str,
    query: str,
    mode: str,
    request_fields: list[str],
    evaluation: dict[str, Any],
    status: str,
    request_id_present: bool,
    readiness_checks: int,
) -> dict[str, Any]:
    return {
        "query_id": query_id,
        "query": query,
        "mode": mode,
        "status": status,
        "retrieve_request_fields": request_fields,
        "nodes_count": evaluation.get("nodes_count", 0),
        "top_scores": evaluation.get("top_scores", []),
        "text_present": bool(evaluation.get("node_text_present_count")),
        "metadata_content_present": bool(evaluation.get("metadata_content_present_count")),
        "smoke_fact_found": bool(evaluation.get("smoke_fact_found")),
        "matched_source": evaluation.get("matched_source", "none"),
        "request_id_present": request_id_present,
        "readiness_checks": readiness_checks,
    }


def error_row(query_id: str, query: str, mode: str, error_type: str, readiness_checks: int) -> dict[str, Any]:
    return {
        "query_id": query_id,
        "query": query,
        "mode": mode,
        "status": "fail",
        "error_type": error_type,
        "retrieve_request_fields": [],
        "nodes_count": 0,
        "top_scores": [],
        "text_present": False,
        "metadata_content_present": False,
        "smoke_fact_found": False,
        "matched_source": "none",
        "request_id_present": False,
        "readiness_checks": readiness_checks,
    }


def finalize_report(
    base: dict[str, Any],
    matrix: list[dict[str, Any]],
    metrics: dict[str, Any],
    *,
    status: str,
    error_type: str | None,
) -> dict[str, Any]:
    working = next((row for row in matrix if row.get("smoke_fact_found")), None)
    top_score = next((row["top_scores"][0] for row in matrix if row.get("top_scores")), None)
    missed = metrics.get("missed_questions") or []
    return {
        **base,
        "status": status,
        "error_type": error_type,
        "matrix_results": matrix,
        "working_query": working.get("query") if working else None,
        "working_retrieval_mode": working.get("mode") if working else None,
        "smoke_fact_found": bool(working),
        "nodes_count": sum(int(row.get("nodes_count") or 0) for row in matrix),
        "top_score": top_score,
        "recall_at_1": metrics.get("recall_at_1"),
        "recall_at_3": metrics.get("recall_at_3"),
        "citation_coverage": metrics.get("citation_coverage"),
        "missed_questions": missed,
        "per_question_results": metrics.get("per_question_results", []),
        "root_cause_classification": classify_retrieval_root_cause(matrix),
    }


def load_index_id(path: Path | None) -> str | None:
    if not path or not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    for key in ["index_id", "created_index_id"]:
        value = payload.get(key)
        if value:
            return str(value)
    official = payload.get("official_sdk_result") if isinstance(payload.get("official_sdk_result"), dict) else {}
    for key in ["index_id", "created_index_id"]:
        value = official.get(key)
        if value:
            return str(value)
    return None


def write_outputs(report: dict[str, Any], output_json: Path, output_md: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(render_markdown(report), encoding="utf-8")


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Bailian Retrieval QA",
        "",
        f"- status: `{report['status']}`",
        f"- error_type: `{report.get('error_type')}`",
        f"- index_id_present: `{report['index_id_present']}`",
        f"- root_cause_classification: `{report['root_cause_classification']}`",
        f"- working_query: `{report.get('working_query')}`",
        f"- working_retrieval_mode: `{report.get('working_retrieval_mode')}`",
        f"- nodes_count: `{report.get('nodes_count')}`",
        f"- top_score: `{report.get('top_score')}`",
        f"- smoke_fact_found: `{report.get('smoke_fact_found')}`",
        f"- recall@1: `{report.get('recall_at_1')}`",
        f"- recall@3: `{report.get('recall_at_3')}`",
        f"- citation_coverage: `{report.get('citation_coverage')}`",
        "",
        "## Matrix",
    ]
    for row in report["matrix_results"]:
        lines.append(
            f"- {row['query_id']} / {row['mode']}: status=`{row['status']}`, "
            f"nodes=`{row['nodes_count']}`, hit=`{row['smoke_fact_found']}`, "
            f"matched_source=`{row['matched_source']}`"
        )
    lines.extend(["", "## Missed Questions"])
    if report["missed_questions"]:
        lines.extend(f"- {row.get('question_id')}" for row in report["missed_questions"])
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
