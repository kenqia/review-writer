#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_METRICS = REPO_ROOT / "evals/fixtures/rag_expected_metrics.json"
DEFAULT_PREFLIGHT = REPO_ROOT / "scripts/rag/bailian_preflight.py"
DEFAULT_CONFIG = REPO_ROOT / "rag/bailian/preflight_config.example.yaml"
DEFAULT_CLEAN_ROOT = REPO_ROOT / "demo_projects/clean_3paper_allene_review"
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "be",
    "for",
    "from",
    "in",
    "is",
    "of",
    "or",
    "paper",
    "papers",
    "question",
    "should",
    "the",
    "to",
    "which",
    "with",
}
WORD_RE = re.compile(r"[a-z0-9]+")


class RetrievalError(Exception):
    pass


def main() -> int:
    args = parse_args()
    try:
        report = run_baseline(args.manifest, args.questions)
    except RetrievalError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.output_json:
        write_json(args.output_json, report)
    if args.output_md:
        write_markdown(args.output_md, report)
    print(
        "local-retrieval-baseline: "
        f"{report['status']} recall@1={report['recall_at_1']:.3f} "
        f"recall@3={report['recall_at_3']:.3f} citation={report['citation_coverage']:.3f}"
    )
    return 1 if args.strict and report["status"] == "fail" else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local no-network retrieval baseline for no-upload RAG corpus.")
    parser.add_argument("--manifest", type=Path, default=Path("/tmp/bailian_no_upload_corpus_manifest.json"))
    parser.add_argument("--questions", type=Path, default=Path("evals/fixtures/rag_expected_questions.json"))
    parser.add_argument("--output-json", type=Path, default=Path("/tmp/local_retrieval_baseline_report.json"))
    parser.add_argument("--output-md", type=Path, default=Path("/tmp/local_retrieval_baseline_report.md"))
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def run_baseline(manifest_path: Path, questions_path: Path) -> dict[str, Any]:
    ensure_manifest(manifest_path)
    manifest = load_json(manifest_path)
    questions_payload = load_json(questions_path)
    metrics = load_json(DEFAULT_METRICS) if DEFAULT_METRICS.exists() else {}
    items = manifest.get("items") or []
    questions = questions_payload.get("questions") or []
    if not items:
        raise RetrievalError("manifest contains no items")
    if not questions:
        raise RetrievalError("questions file contains no questions")
    corpus_warnings = validate_manifest_safety(manifest)
    idf = compute_idf(items)
    per_question = []
    recall1_values = []
    recall3_values = []
    citation_hits = []
    missed = []
    for question in questions:
        ranked = rank_items(question["query"], items, idf)
        expected = [str(pid) for pid in question.get("expected_paper_ids", [])]
        top1 = [row["paper_id"] for row in ranked[:1]]
        top3 = [row["paper_id"] for row in ranked[:3]]
        top1_recall = recall(expected, top1)
        top3_recall = recall(expected, top3)
        citation_ok = bool(question.get("answer_must_cite")) and all(pid in top3 for pid in expected)
        result = {
            "question_id": question.get("question_id"),
            "query": question.get("query"),
            "expected_paper_ids": expected,
            "top1": top1,
            "top3": top3,
            "scores": ranked[:3],
            "recall_at_1": top1_recall,
            "recall_at_3": top3_recall,
            "citation_ok": citation_ok,
        }
        per_question.append(result)
        recall1_values.append(top1_recall)
        recall3_values.append(top3_recall)
        citation_hits.append(1.0 if citation_ok else 0.0)
        if top3_recall < 1.0 or not citation_ok:
            missed.append(
                {
                    "question_id": question.get("question_id"),
                    "expected_paper_ids": expected,
                    "top3": top3,
                    "reason": "expected papers not fully recovered in top3",
                }
            )
    recall_at_1 = average(recall1_values)
    recall_at_3 = average(recall3_values)
    citation_coverage = average(citation_hits)
    min_recall3 = float(metrics.get("minimum_recall_at_3", 0.8))
    min_citation = float(metrics.get("minimum_citation_coverage", 1.0))
    trust_ok = manifest.get("trusted_for_scientific_quality") is False and all(
        item.get("trusted_for_scientific_quality") is False for item in items
    )
    errors = []
    if recall_at_3 < min_recall3:
        errors.append(f"recall@3 {recall_at_3:.3f} is below minimum {min_recall3:.3f}")
    if citation_coverage < min_citation:
        errors.append(f"citation coverage {citation_coverage:.3f} is below minimum {min_citation:.3f}")
    if metrics.get("trusted_for_scientific_quality_must_remain_false", True) and not trust_ok:
        errors.append("trusted_for_scientific_quality was not preserved as false")
    status = "fail" if errors else "warn" if corpus_warnings else "pass"
    allow_warn = bool(metrics.get("allow_warn", True))
    recommendation = "proceed_to_bailian_pilot" if not errors and (allow_warn or not corpus_warnings) else "fix_manifest_first"
    return {
        "status": status,
        "recall_at_1": round(recall_at_1, 4),
        "recall_at_3": round(recall_at_3, 4),
        "citation_coverage": round(citation_coverage, 4),
        "per_question_results": per_question,
        "missed_questions": missed,
        "corpus_warnings": corpus_warnings,
        "errors": errors,
        "recommendation": recommendation,
        "trusted_for_scientific_quality": False,
        "safety": {
            "network": "not_used",
            "qwen": "not_used",
            "bailian_api": "not_used",
            "mineru_api": "not_used",
            "upload": "not_used",
            "knowledge_base": "not_created",
            "pdf_read": "not_used",
        },
    }


def ensure_manifest(manifest_path: Path) -> None:
    if manifest_path.exists():
        return
    cmd = [
        sys.executable,
        str(DEFAULT_PREFLIGHT),
        "--clean-root",
        str(DEFAULT_CLEAN_ROOT),
        "--config",
        str(DEFAULT_CONFIG),
        "--output-json",
        "/tmp/bailian_rag_preflight.json",
        "--output-md",
        "/tmp/bailian_rag_preflight.md",
        "--strict",
    ]
    result = subprocess.run(cmd, cwd=REPO_ROOT, text=True, capture_output=True)
    if result.returncode != 0:
        raise RetrievalError("failed to generate no-upload manifest before retrieval baseline")
    if not manifest_path.exists():
        raise RetrievalError(f"manifest still missing after preflight: {manifest_path}")


def rank_items(query: str, items: list[dict[str, Any]], idf: dict[str, float]) -> list[dict[str, Any]]:
    query_tokens = tokenize(query)
    ranked = []
    for item in items:
        score = 0.0
        matched_terms: list[str] = []
        weighted_fields = [
            ("paper_id", 6.0),
            ("title", 5.0),
            ("role", 4.0),
            ("claim_draft", 3.0),
            ("figure_note_draft", 2.5),
            ("warning", 2.0),
            ("journal", 0.8),
        ]
        for field, weight in weighted_fields:
            field_tokens = tokenize(str(item.get(field, "")))
            counts = Counter(field_tokens)
            for token in query_tokens:
                if counts[token]:
                    score += weight * (1.0 + math.log1p(counts[token])) * idf.get(token, 1.0)
                    matched_terms.append(token)
        ranked.append(
            {
                "paper_id": item.get("paper_id"),
                "score": round(score, 4),
                "matched_terms": sorted(set(matched_terms)),
            }
        )
    return sorted(ranked, key=lambda row: (-float(row["score"]), str(row["paper_id"])))


def compute_idf(items: list[dict[str, Any]]) -> dict[str, float]:
    docs = []
    for item in items:
        text = " ".join(str(item.get(field, "")) for field in ["title", "role", "claim_draft", "figure_note_draft", "warning"])
        docs.append(set(tokenize(text)))
    total = len(docs)
    df: Counter[str] = Counter()
    for doc in docs:
        df.update(doc)
    return {token: math.log((total + 1) / (count + 1)) + 1 for token, count in df.items()}


def tokenize(text: str) -> list[str]:
    return [token for token in WORD_RE.findall(text.lower().replace("_", " ")) if token not in STOPWORDS and len(token) > 1]


def recall(expected: list[str], retrieved: list[str]) -> float:
    if not expected:
        return 1.0
    return len(set(expected) & set(retrieved)) / len(set(expected))


def average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def validate_manifest_safety(manifest: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    items = manifest.get("items") or []
    if manifest.get("no_upload") is not True:
        warnings.append("manifest no_upload is not true")
    if manifest.get("knowledge_base_created") is not False:
        warnings.append("manifest knowledge_base_created is not false")
    for item in items:
        paper_id = item.get("paper_id", "unknown")
        if item.get("needs_human_review") is not True:
            warnings.append(f"{paper_id}: needs_human_review is not true")
        if item.get("trusted_for_scientific_quality") is not False:
            warnings.append(f"{paper_id}: trusted_for_scientific_quality is not false")
        if item.get("upload_status") != "not_uploaded":
            warnings.append(f"{paper_id}: upload_status is not not_uploaded")
    return warnings


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RetrievalError(f"missing required file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Local RAG Retrieval Baseline",
        "",
        f"- status: `{report['status']}`",
        f"- recall@1: `{report['recall_at_1']}`",
        f"- recall@3: `{report['recall_at_3']}`",
        f"- citation coverage: `{report['citation_coverage']}`",
        f"- recommendation: `{report['recommendation']}`",
        f"- trusted_for_scientific_quality: `{report['trusted_for_scientific_quality']}`",
        "",
        "## Per Question",
    ]
    for result in report["per_question_results"]:
        lines.append(
            f"- {result['question_id']}: expected {result['expected_paper_ids']}, "
            f"top3 {result['top3']}, recall@3 {result['recall_at_3']}"
        )
    lines.append("")
    lines.append("## Missed Questions")
    if report["missed_questions"]:
        lines.extend(f"- {item['question_id']}: {item['reason']}" for item in report["missed_questions"])
    else:
        lines.append("- none")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

