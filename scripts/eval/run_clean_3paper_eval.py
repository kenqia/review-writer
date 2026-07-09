#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

METRICS = [
    "workflow_completeness",
    "artifact_completeness",
    "bibliographic_completeness",
    "claim_traceability",
    "figure_note_integrity",
    "warning_visibility",
    "prompt_leakage_absence",
    "safety_boundary",
    "human_review_flags",
]

EXPECTED_ARTIFACTS = [
    "project_status_before.json",
    "checkpoint_log.json",
    "00_discovery/discovery_candidates.json",
    "01_matrix_outline/literature_matrix.json",
    "01_matrix_outline/outline.md",
    "section_blueprint.json",
    "02_section_drafting/section_1.md",
    "03_figure_redraw/figure_manifest.json",
    "04_first_draft/final_draft.md",
    "05_final_audit/final_audit_report.json",
    "05_final_audit/quality_report.json",
    "05_final_audit/clean_3paper_review_pack.md",
    "export/final_draft.md",
    "run_summary.json",
]

LEAKAGE_TERMS = ["写作思路", "本节应当", "请生成", "LLM judge", "rule pack", "blueprint", "workflow", "不要直接出现在正文"]


@dataclass
class Metric:
    metric_id: str
    status: str
    score: float
    weight: float
    summary: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "status": self.status,
            "score": self.score,
            "weight": self.weight,
            "summary": self.summary,
            "details": self.details,
        }


class EvalError(Exception):
    pass


def main() -> int:
    args = parse_args()
    try:
        report = run_eval(args)
    except EvalError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.output_json:
        write_json(args.output_json, report)
    if args.output_md:
        write_markdown(args.output_md, report)
    output_eval = args.output_root / "eval"
    output_eval.mkdir(parents=True, exist_ok=True)
    write_json(output_eval / "clean_3paper_eval_report.json", report)
    write_markdown(output_eval / "clean_3paper_eval_report.md", report)
    print(f"clean-3paper-eval: {report['status']} score={report['score_total']:.1f}")
    return 1 if args.strict and report["status"] == "fail" else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run clean 3-paper offline eval baseline.")
    parser.add_argument("--output-root", type=Path, default=Path("/tmp/review_writer_clean_3paper_e2e"))
    parser.add_argument("--baseline", type=Path, default=Path("evals/baselines/clean_3paper_v1.yaml"))
    parser.add_argument("--expected", type=Path, default=Path("evals/fixtures/clean_3paper_expected_metrics.json"))
    parser.add_argument("--output-json", type=Path, default=Path("/tmp/clean_3paper_eval_report.json"))
    parser.add_argument("--output-md", type=Path, default=Path("/tmp/clean_3paper_eval_report.md"))
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def run_eval(args: argparse.Namespace) -> dict[str, Any]:
    if not args.output_root.exists():
        raise EvalError(f"output root not found: {args.output_root}")
    baseline = load_baseline(args.baseline)
    expected = load_json(args.expected)
    weights = metric_weights(baseline)
    context = Context(args.output_root)
    metric_rows = [
        check_workflow(context, weights["workflow_completeness"]),
        check_artifacts(context, weights["artifact_completeness"]),
        check_bibliography(context, weights["bibliographic_completeness"]),
        check_claims(context, weights["claim_traceability"]),
        check_figures(context, weights["figure_note_integrity"]),
        check_warnings(context, weights["warning_visibility"]),
        check_prompt_leakage(context, weights["prompt_leakage_absence"]),
        check_safety(context, weights["safety_boundary"]),
        check_human_flags(context, weights["human_review_flags"]),
    ]
    errors = [f"{row.metric_id}: {row.summary}" for row in metric_rows if row.status == "fail"]
    warnings = [f"{row.metric_id}: {row.summary}" for row in metric_rows if row.status == "warn"]
    score = round(sum(row.score for row in metric_rows), 2)
    minimum = float(expected.get("minimum_score", 0))
    if score < minimum:
        errors.append(f"score {score} below minimum {minimum}")
    required = set(expected.get("required_metrics") or [])
    present = {row.metric_id for row in metric_rows}
    missing = sorted(required - present)
    if missing:
        errors.append(f"missing required metrics: {', '.join(missing)}")
    status = "fail" if errors else "warn" if warnings else "pass"
    return {
        "status": status,
        "score_total": score,
        "minimum_score": minimum,
        "baseline": baseline.get("name", "clean_3paper_v1"),
        "metrics": [row.to_dict() for row in metric_rows],
        "errors": errors,
        "warnings": warnings,
        "trusted_for_scientific_quality": False,
        "needs_human_review": True,
        "safety": {
            "network": "not_used",
            "pdf_read": "not_used",
            "qwen": "not_used",
            "mineru_api": "not_used",
            "bailian": "not_used",
            "upload": "not_used",
            "knowledge_base": "not_created",
            "image_api": "not_used",
        },
    }


class Context:
    def __init__(self, root: Path) -> None:
        self.root = root

    def json(self, rel: str) -> Any:
        path = self.root / rel
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def text(self, rel: str) -> str:
        path = self.root / rel
        return path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""


def check_workflow(context: Context, weight: float) -> Metric:
    payload = context.json("checkpoint_log.json") or {}
    checkpoints = payload.get("checkpoints") or []
    ok = len(checkpoints) == 9 and all(row.get("human_review_required") is True for row in checkpoints)
    return metric("workflow_completeness", ok, weight, f"{len(checkpoints)} checkpoints", {})


def check_artifacts(context: Context, weight: float) -> Metric:
    missing = [rel for rel in EXPECTED_ARTIFACTS if not (context.root / rel).exists()]
    return metric("artifact_completeness", not missing, weight, "expected clean artifacts present", {"missing": missing})


def check_bibliography(context: Context, weight: float) -> Metric:
    matrix = context.json("01_matrix_outline/literature_matrix.json") or {}
    rows = matrix.get("rows") or []
    missing = []
    for row in rows:
        for field in ["title", "year", "journal", "doi"]:
            value = row.get(field)
            if value in (None, "", "unknown"):
                missing.append(f"{row.get('paper_id')}.{field}")
    ok = len(rows) == 3 and not any(item.endswith(".title") for item in missing)
    status = "pass" if ok else "fail"
    summary = f"{len(rows)} bibliographic rows; missing={len(missing)}"
    return Metric("bibliographic_completeness", status, weight if ok else 0.0, weight, summary, {"missing": missing})


def check_claims(context: Context, weight: float) -> Metric:
    blueprint = context.json("section_blueprint.json") or {}
    claims = (blueprint.get("sections") or [{}])[0].get("claims") or []
    text = context.text("02_section_drafting/section_1.md") + "\n" + context.text("04_first_draft/final_draft.md")
    present = [pid for pid in ["F3I", "F47A", "P403"] if pid in text]
    ok = len(claims) >= 6 and len(present) == 3
    return metric("claim_traceability", ok, weight, f"{len(claims)} claim ids visible in blueprint", {"present_papers": present})


def check_figures(context: Context, weight: float) -> Metric:
    manifest = context.json("03_figure_redraw/figure_manifest.json") or {}
    figures = manifest.get("figures") or []
    ok = len(figures) >= 3 and all(row.get("needs_human_review") is True for row in figures)
    return metric("figure_note_integrity", ok, weight, f"{len(figures)} figure notes", {})


def check_warnings(context: Context, weight: float) -> Metric:
    quality = context.json("05_final_audit/quality_report.json") or {}
    warnings_text = json.dumps(quality.get("warnings") or [], ensure_ascii=False)
    ok = "P403" in warnings_text and "missing fields" in warnings_text and "source conflicts" in warnings_text
    return metric("warning_visibility", ok, weight, "P403 missing metadata and source conflicts visible", {})


def check_prompt_leakage(context: Context, weight: float) -> Metric:
    text = context.text("04_first_draft/final_draft.md")
    hits = [term for term in LEAKAGE_TERMS if term.lower() in text.lower()]
    return metric("prompt_leakage_absence", not hits, weight, "no prompt leakage terms", {"hits": hits})


def check_safety(context: Context, weight: float) -> Metric:
    summary = context.json("run_summary.json") or {}
    expected = {
        "network": "not_used",
        "pdf_read": "not_used",
        "qwen": "not_used",
        "mineru_api": "not_used",
        "upload": "not_used",
        "knowledge_base": "not_created",
    }
    mismatches = {key: summary.get(key) for key, value in expected.items() if summary.get(key) != value}
    return metric("safety_boundary", not mismatches, weight, "offline safety markers preserved", {"mismatches": mismatches})


def check_human_flags(context: Context, weight: float) -> Metric:
    summary = context.json("run_summary.json") or {}
    final = context.json("05_final_audit/final_audit_report.json") or {}
    ok = (
        summary.get("needs_human_review") is True
        and summary.get("trusted_for_scientific_quality") is False
        and final.get("trusted_for_scientific_quality") is False
    )
    return metric("human_review_flags", ok, weight, "human review flags retained", {})


def metric(metric_id: str, ok: bool, weight: float, summary: str, details: dict[str, Any]) -> Metric:
    return Metric(metric_id, "pass" if ok else "fail", weight if ok else 0.0, weight, summary, details)


def load_baseline(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise EvalError(f"baseline not found: {path}")
    data: dict[str, Any] = {"metrics": []}
    current: dict[str, Any] | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped.startswith("- id:"):
            current = {"id": stripped.split(":", 1)[1].strip()}
            data["metrics"].append(current)
        elif current is not None and stripped.startswith("weight:"):
            current["weight"] = float(stripped.split(":", 1)[1].strip())
        elif not raw.startswith(" ") and ":" in stripped:
            key, value = stripped.split(":", 1)
            if key.strip() != "metrics":
                data[key.strip()] = value.strip()
    return data


def metric_weights(baseline: dict[str, Any]) -> dict[str, float]:
    weights = {metric_id: 100.0 / len(METRICS) for metric_id in METRICS}
    for row in baseline.get("metrics") or []:
        if row.get("id") in weights:
            weights[row["id"]] = float(row.get("weight") or weights[row["id"]])
    return weights


def load_json(path: Path) -> Any:
    if not path.exists():
        raise EvalError(f"JSON not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Clean 3-Paper Eval Report",
        "",
        f"- status: {report['status']}",
        f"- score_total: {report['score_total']}",
        f"- trusted_for_scientific_quality: {report['trusted_for_scientific_quality']}",
        f"- needs_human_review: {report['needs_human_review']}",
        "",
        "| metric | status | score | weight | summary |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for row in report["metrics"]:
        lines.append(f"| {row['metric_id']} | {row['status']} | {row['score']} | {row['weight']} | {row['summary']} |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
