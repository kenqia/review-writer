#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

METRIC_IDS = [
    "workflow_completeness",
    "artifact_completeness",
    "quality_gate_health",
    "figure_integrity",
    "citation_and_reference_integrity",
    "prompt_leakage_absence",
    "evidence_coverage",
    "safety_boundary",
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
    "export/final_draft.md",
    "run_summary.json",
]

LEAKAGE_TERMS = [
    "写作思路",
    "本节应当",
    "请生成",
    "LLM judge",
    "rule pack",
    "blueprint",
    "workflow",
    "不要直接出现在正文",
]

CITATION_RE = re.compile(r"\[(\d+(?:\s*(?:,|-|–)\s*\d+)*)\]")


@dataclass
class MetricResult:
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
    print(f"eval-baseline: {report['status']} score={report['score_total']:.1f}")
    return 1 if args.strict and report["status"] == "fail" else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run offline real-lite eval baseline.")
    parser.add_argument("--output-root", type=Path, default=Path("/tmp/review_writer_real_lite_e2e"))
    parser.add_argument("--baseline", type=Path, default=Path("evals/baselines/real_lite_v1.yaml"))
    parser.add_argument("--expected", type=Path, default=Path("evals/fixtures/real_lite_expected_metrics.json"))
    parser.add_argument("--output-json", type=Path, default=Path("/tmp/real_lite_eval_report.json"))
    parser.add_argument("--output-md", type=Path, default=Path("/tmp/real_lite_eval_report.md"))
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def run_eval(args: argparse.Namespace) -> dict[str, Any]:
    output_root = args.output_root.resolve()
    if not output_root.exists():
        raise EvalError(f"output root not found: {output_root}")
    baseline = load_baseline(args.baseline)
    expected = load_json(args.expected, "expected metrics")
    weights = metric_weights(baseline)
    context = EvalContext(output_root)
    metric_results = [
        check_workflow_completeness(context, weights["workflow_completeness"]),
        check_artifact_completeness(context, weights["artifact_completeness"]),
        check_quality_gate_health(context, weights["quality_gate_health"]),
        check_figure_integrity(context, weights["figure_integrity"]),
        check_citation_and_reference_integrity(context, weights["citation_and_reference_integrity"]),
        check_prompt_leakage_absence(context, weights["prompt_leakage_absence"]),
        check_evidence_coverage(context, weights["evidence_coverage"]),
        check_safety_boundary(context, weights["safety_boundary"]),
    ]
    metrics = [row.to_dict() for row in metric_results]
    errors: list[str] = []
    warnings: list[str] = []
    for row in metric_results:
        if row.status == "fail":
            errors.append(f"{row.metric_id}: {row.summary}")
        elif row.status == "warn":
            warnings.append(f"{row.metric_id}: {row.summary}")
    minimum_score = float(expected.get("minimum_score", 0))
    required_metrics = set(expected.get("required_metrics") or [])
    missing_required = sorted(required_metrics.difference({row.metric_id for row in metric_results}))
    if missing_required:
        errors.append(f"missing required metrics: {', '.join(missing_required)}")
    required_statuses = set(expected.get("required_metric_statuses") or ["pass"])
    for row in metric_results:
        if row.metric_id in required_metrics and row.status not in required_statuses:
            errors.append(f"required metric {row.metric_id} is {row.status}")
    score_total = round(sum(row.score for row in metric_results), 2)
    if score_total < minimum_score:
        errors.append(f"score_total {score_total} below minimum_score {minimum_score}")
    status = "fail" if errors else "warn" if warnings else "pass"
    return {
        "status": status,
        "baseline": baseline.get("name") or args.baseline.name,
        "score_total": score_total,
        "minimum_score": minimum_score,
        "metrics": metrics,
        "errors": errors,
        "warnings": warnings,
        "artifacts_checked": EXPECTED_ARTIFACTS,
        "safety": {
            "network": "not_used",
            "pdf_read": "not_used",
            "qwen": "not_used",
            "mineru_api": "not_used",
            "upload": "not_used",
            "promptfoo": "not_used",
        },
        "next_actions": next_actions(metric_results, status),
    }


class EvalContext:
    def __init__(self, output_root: Path) -> None:
        self.output_root = output_root

    def path(self, rel: str) -> Path:
        return self.output_root / rel

    def text(self, rel: str) -> str:
        path = self.path(rel)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")

    def json(self, rel: str) -> Any:
        return read_json_if_exists(self.path(rel))


def load_baseline(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise EvalError(f"baseline not found: {path}")
    data: dict[str, Any] = {"metrics": []}
    current_metric: dict[str, Any] | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped.startswith("- id:"):
            current_metric = {"id": stripped.split(":", 1)[1].strip()}
            data["metrics"].append(current_metric)
        elif current_metric is not None and stripped.startswith("weight:"):
            current_metric["weight"] = float(stripped.split(":", 1)[1].strip())
        elif not raw.startswith(" ") and ":" in stripped:
            key, value = stripped.split(":", 1)
            key = key.strip()
            if key == "metrics":
                current_metric = None
                data.setdefault("metrics", [])
            else:
                data[key] = parse_scalar(value.strip())
    return data


def parse_scalar(value: str) -> Any:
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    try:
        return float(value) if "." in value else int(value)
    except ValueError:
        return value


def metric_weights(baseline: dict[str, Any]) -> dict[str, float]:
    weights = {metric_id: 100.0 / len(METRIC_IDS) for metric_id in METRIC_IDS}
    for row in baseline.get("metrics") or []:
        metric_id = row.get("id")
        if metric_id in weights:
            weights[metric_id] = float(row.get("weight") or weights[metric_id])
    return weights


def check_workflow_completeness(context: EvalContext, weight: float) -> MetricResult:
    payload = context.json("checkpoint_log.json")
    checkpoints = payload.get("checkpoints") if isinstance(payload, dict) else payload if isinstance(payload, list) else []
    missing_fields = []
    for index, row in enumerate(checkpoints or [], start=1):
        for field in ["status", "input_files", "output_files", "human_review_required"]:
            if field not in row:
                missing_fields.append(f"{index}.{field}")
        if "checkpoint" not in row and "name" not in row:
            missing_fields.append(f"{index}.name")
    ok = len(checkpoints or []) == 9 and not missing_fields
    return metric("workflow_completeness", ok, weight, f"{len(checkpoints or [])} checkpoints", {"missing_fields": missing_fields})


def check_artifact_completeness(context: EvalContext, weight: float) -> MetricResult:
    missing = []
    empty = []
    for rel in EXPECTED_ARTIFACTS:
        path = context.path(rel)
        if not path.exists():
            missing.append(rel)
        elif path.stat().st_size <= 0:
            empty.append(rel)
    ok = not missing and not empty
    return metric("artifact_completeness", ok, weight, "expected artifacts present", {"missing": missing, "empty": empty})


def check_quality_gate_health(context: EvalContext, weight: float) -> MetricResult:
    report = context.json("05_final_audit/quality_report.json")
    if not isinstance(report, dict):
        return metric("quality_gate_health", False, weight, "quality_report.json missing or invalid", {})
    errors = report.get("errors") or []
    warnings = report.get("warnings") or []
    ok = report.get("status") in {"pass", "warn"} and not errors
    details = {"quality_status": report.get("status"), "errors": len(errors), "warnings": len(warnings)}
    return metric("quality_gate_health", ok, weight, "quality gate has no blocking errors", details)


def check_figure_integrity(context: EvalContext, weight: float) -> MetricResult:
    manifest = context.json("03_figure_redraw/figure_manifest.json")
    figures = manifest.get("figures") if isinstance(manifest, dict) else []
    missing = []
    for index, row in enumerate(figures or [], start=1):
        if not row.get("figure_id"):
            missing.append(f"{index}.figure_id")
        if not (row.get("source_path") or row.get("source_hint")):
            missing.append(f"{index}.source_path")
        if not row.get("caption"):
            missing.append(f"{index}.caption")
    ok = bool(figures) and not missing
    return metric("figure_integrity", ok, weight, f"{len(figures or [])} figures", {"missing_fields": missing})


def check_citation_and_reference_integrity(context: EvalContext, weight: float) -> MetricResult:
    text = context.text("04_first_draft/final_draft.md")
    callouts = list(CITATION_RE.finditer(text))
    bad_callouts = []
    for match in callouts:
        raw = match.group(1)
        numbers = []
        local_bad = False
        for part in re.split(r"\s*,\s*", raw):
            if "-" in part or "–" in part:
                left_raw, right_raw = re.split(r"\s*[-–]\s*", part, maxsplit=1)
                left, right = int(left_raw), int(right_raw)
                if left > right:
                    local_bad = True
                numbers.extend([left, right])
            else:
                numbers.append(int(part.strip()))
        if numbers != sorted(numbers):
            local_bad = True
        if local_bad:
            bad_callouts.append(f"[{raw}]")
    has_references = bool(re.search(r"^##\s+References\b", text, re.I | re.M))
    ok = bool(callouts) and not bad_callouts and has_references
    details = {"callout_count": len(callouts), "bad_callouts": bad_callouts, "has_references": has_references}
    return metric("citation_and_reference_integrity", ok, weight, "citation callouts and references present", details)


def check_prompt_leakage_absence(context: EvalContext, weight: float) -> MetricResult:
    text = context.text("04_first_draft/final_draft.md")
    hits = [term for term in LEAKAGE_TERMS if term.lower() in text.lower()]
    return metric("prompt_leakage_absence", not hits, weight, "no obvious process text leaked", {"hits": hits})


def check_evidence_coverage(context: EvalContext, weight: float) -> MetricResult:
    summary = context.json("run_summary.json")
    selected = summary.get("selected_papers") if isinstance(summary, dict) else []
    haystack = "\n".join(
        [
            json.dumps(context.json("00_discovery/discovery_candidates.json") or {}, ensure_ascii=False),
            json.dumps(context.json("01_matrix_outline/literature_matrix.json") or {}, ensure_ascii=False),
            context.text("02_section_drafting/section_1.md"),
            context.text("04_first_draft/final_draft.md"),
        ]
    )
    present = [paper_id for paper_id in selected or [] if str(paper_id) in haystack]
    ok = len(present) >= 3
    return metric("evidence_coverage", ok, weight, f"{len(present)} selected papers visible in stage outputs", {"present": present})


def check_safety_boundary(context: EvalContext, weight: float) -> MetricResult:
    summary = context.json("run_summary.json")
    if not isinstance(summary, dict):
        return metric("safety_boundary", False, weight, "run_summary.json missing or invalid", {})
    required = {
        "network": "not_used",
        "pdf_read": "not_used",
        "qwen": "not_used",
        "mineru_api": "not_used",
        "upload": "not_used",
    }
    optional = {
        "knowledge_base_created": "not_used",
        "image_api": "not_used",
    }
    mismatches = {key: summary.get(key) for key, expected in required.items() if summary.get(key) != expected}
    for key, expected in optional.items():
        if key in summary and summary.get(key) != expected:
            mismatches[key] = summary.get(key)
    ok = not mismatches
    return metric("safety_boundary", ok, weight, "offline safety markers preserved", {"mismatches": mismatches})


def metric(metric_id: str, ok: bool, weight: float, summary: str, details: dict[str, Any]) -> MetricResult:
    return MetricResult(metric_id, "pass" if ok else "fail", weight if ok else 0.0, weight, summary, details)


def next_actions(results: list[MetricResult], status: str) -> list[str]:
    if status == "pass":
        return [
            "Use this baseline as the Phase 5d regression gate.",
            "Keep generated eval reports under /tmp unless a release artifact is explicitly requested.",
        ]
    return [f"Fix metric: {row.metric_id}" for row in results if row.status != "pass"]


def load_json(path: Path, label: str) -> Any:
    if not path.exists():
        raise EvalError(f"{label} not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EvalError(f"{label} is invalid JSON: {path} ({exc})") from exc


def read_json_if_exists(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Real-Lite Eval Report",
        "",
        f"- status: {report['status']}",
        f"- score_total: {report['score_total']}",
        f"- minimum_score: {report['minimum_score']}",
        "",
        "## Metrics",
        "",
        "| metric | status | score | weight | summary |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for row in report["metrics"]:
        lines.append(
            f"| {row['metric_id']} | {row['status']} | {row['score']} | {row['weight']} | {row['summary']} |"
        )
    lines.extend(["", "## Safety", ""])
    for key, value in report["safety"].items():
        lines.append(f"- {key}: {value}")
    if report["errors"]:
        lines.extend(["", "## Errors", ""])
        lines.extend(f"- {item}" for item in report["errors"])
    if report["warnings"]:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {item}" for item in report["warnings"])
    lines.extend(["", "## Next Actions", ""])
    lines.extend(f"- {item}" for item in report["next_actions"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class EvalError(Exception):
    pass


if __name__ == "__main__":
    raise SystemExit(main())
