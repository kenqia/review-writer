#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "scripts/demo/run_real_lite_e2e.py"
EVAL_RUNNER = REPO_ROOT / "scripts/eval/run_eval_baseline.py"
EXPECTED_ARTIFACTS = [
    "checkpoint_log.json",
    "01_matrix_outline/literature_matrix.json",
    "section_blueprint.json",
    "03_figure_redraw/figure_manifest.json",
    "04_first_draft/final_draft.md",
    "05_final_audit/quality_report.json",
    "05_final_audit/final_audit_report.json",
    "run_summary.json",
]


class AuditError(Exception):
    pass


def main() -> int:
    args = parse_args()
    try:
        report = audit_outputs(args.output_root, args.input_demo_root)
    except AuditError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.output_json:
        write_json(args.output_json, report)
    if args.output_md:
        write_markdown(args.output_md, report)
    print(
        "real-lite-output-audit: "
        f"engineering={report['engineering_status']} "
        f"content_quality={report['content_quality_status']} "
        f"scientific_quality={report['trusted_for_scientific_quality']}"
    )
    return 1 if args.strict and report["engineering_status"] == "fail" else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit real-lite E2E output quality and provenance limits.")
    parser.add_argument("--output-root", type=Path, default=Path("/tmp/review_writer_real_lite_e2e"))
    parser.add_argument("--input-demo-root", type=Path, default=Path("demo_projects/real_lite_allene_review"))
    parser.add_argument("--output-json", type=Path, default=Path("/tmp/real_lite_output_audit.json"))
    parser.add_argument("--output-md", type=Path, default=Path("/tmp/real_lite_output_audit.md"))
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def audit_outputs(output_root: Path, input_demo_root: Path) -> dict[str, Any]:
    ensure_output(output_root, input_demo_root)
    missing = [rel for rel in EXPECTED_ARTIFACTS if not (output_root / rel).exists()]
    if missing:
        raise AuditError(f"missing expected output artifacts: {', '.join(missing)}")

    draft = (output_root / "04_first_draft/final_draft.md").read_text(encoding="utf-8", errors="ignore")
    matrix = load_json(output_root / "01_matrix_outline/literature_matrix.json", "literature matrix")
    blueprint = load_json(output_root / "section_blueprint.json", "section blueprint")
    figures = load_json(output_root / "03_figure_redraw/figure_manifest.json", "figure manifest")
    quality = load_json(output_root / "05_final_audit/quality_report.json", "quality report")
    checkpoints = load_json(output_root / "checkpoint_log.json", "checkpoint log")
    eval_report = run_or_load_eval(output_root)

    word_count = len(re.findall(r"\b[\w-]+\b", draft))
    section_count = len(re.findall(r"^##\s+", draft, flags=re.MULTILINE))
    has_references = bool(re.search(r"^##\s+References\b", draft, flags=re.MULTILINE))
    title_signals = detect_title_or_paper_signals(draft, input_demo_root)
    skeleton_signals = detect_skeleton_signals(draft, figures)
    matrix_rows = matrix.get("rows") if isinstance(matrix, dict) else []
    sections = blueprint.get("sections") if isinstance(blueprint, dict) else []
    figure_rows = figures.get("figures") if isinstance(figures, dict) else []
    checkpoint_rows = checkpoints.get("checkpoints") if isinstance(checkpoints, dict) else checkpoints
    if not isinstance(checkpoint_rows, list):
        checkpoint_rows = []
    quality_status = quality.get("status") if isinstance(quality, dict) else None
    eval_status = eval_report.get("status")

    engineering_errors: list[str] = []
    warnings: list[str] = []
    if len(matrix_rows or []) < 5:
        engineering_errors.append("literature_matrix has fewer than 5 papers")
    if not sections:
        engineering_errors.append("section_blueprint has no sections")
    if len(checkpoint_rows) != 9:
        engineering_errors.append("checkpoint log does not contain 9 checkpoints")
    if quality_status not in {"pass", "warn"}:
        engineering_errors.append(f"quality_report status is {quality_status}")
    if eval_status != "pass":
        engineering_errors.append(f"eval baseline status is {eval_status}")
    if not figure_rows:
        engineering_errors.append("figure_manifest has no figures")

    if word_count < 700:
        warnings.append(f"final_draft is compact ({word_count} words)")
    if skeleton_signals:
        warnings.extend(skeleton_signals)
    if len(title_signals) < 3:
        warnings.append("draft has limited paper_id/title signals")
    if not has_references:
        warnings.append("draft has no References section")

    pointer_or_placeholder_figures = figure_manifest_is_pointer_or_placeholder(figure_rows)
    if pointer_or_placeholder_figures:
        warnings.append("figure manifest uses pointer/placeholder assets")

    engineering_status = "fail" if engineering_errors else "pass"
    content_quality_status = "needs_human_review" if warnings or pointer_or_placeholder_figures else "pass_for_demo_only"
    trusted_for_scientific_quality = False
    trusted_for_demo = engineering_status == "pass"

    return {
        "engineering_status": engineering_status,
        "content_quality_status": content_quality_status,
        "trusted_for_demo": trusted_for_demo,
        "trusted_for_scientific_quality": trusted_for_scientific_quality,
        "checks": {
            "final_draft_words": word_count,
            "section_count": section_count,
            "has_references": has_references,
            "paper_or_title_signals": title_signals,
            "skeleton_or_placeholder_signals": skeleton_signals,
            "literature_matrix_papers": len(matrix_rows or []),
            "section_blueprint_sections": len(sections or []),
            "figure_count": len(figure_rows or []),
            "figures_pointer_or_placeholder": pointer_or_placeholder_figures,
            "quality_report_status": quality_status,
            "eval_status": eval_status,
            "eval_score": eval_report.get("score_total"),
            "checkpoint_count": len(checkpoint_rows),
        },
        "warnings": warnings,
        "errors": engineering_errors,
        "next_actions": [
            "Use this output for engineering regression and dashboard payload QA.",
            "Do not use this output as final scientific review quality evidence.",
            "Build a clean human-verified 3-paper dataset before citation-accurate review evaluation.",
        ],
        "safety": {
            "network": "not_used",
            "pdf_read": "not_used",
            "qwen": "not_used",
            "mineru_api": "not_used",
            "upload": "not_used",
        },
    }


def ensure_output(output_root: Path, input_demo_root: Path) -> None:
    if output_root.exists():
        return
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--demo-root",
            str(input_demo_root),
            "--output-root",
            str(output_root),
            "--strict",
        ],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise AuditError(f"could not generate real-lite output: {result.stderr.strip() or result.stdout.strip()}")


def run_or_load_eval(output_root: Path) -> dict[str, Any]:
    eval_path = Path("/tmp/real_lite_output_audit_eval.json")
    result = subprocess.run(
        [
            sys.executable,
            str(EVAL_RUNNER),
            "--output-root",
            str(output_root),
            "--baseline",
            "evals/baselines/real_lite_v1.yaml",
            "--expected",
            "evals/fixtures/real_lite_expected_metrics.json",
            "--output-json",
            str(eval_path),
            "--output-md",
            "/tmp/real_lite_output_audit_eval.md",
            "--strict",
        ],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        return {"status": "fail", "score_total": 0, "error": result.stderr.strip() or result.stdout.strip()}
    return load_json(eval_path, "eval report")


def detect_title_or_paper_signals(draft: str, input_demo_root: Path) -> list[str]:
    signals: list[str] = []
    selected_path = input_demo_root / "inputs/selected_papers.json"
    if selected_path.exists():
        payload = load_json(selected_path, "selected papers")
        selected = payload.get("selected_papers") if isinstance(payload, dict) else []
        for row in selected or []:
            paper_id = str(row.get("paper_id") or "")
            title = str(row.get("title") or "")
            if paper_id and paper_id in draft:
                signals.append(paper_id)
            elif title and title[:32] in draft:
                signals.append(paper_id or title[:32])
    for token in ["palladium carbonylation", "photoredox copper", "nickel reductive coupling"]:
        if token.lower() in draft.lower():
            signals.append(token)
    return sorted(set(signals))


def detect_skeleton_signals(draft: str, figures: dict[str, Any]) -> list[str]:
    terms = ["real-lite", "intentionally compact", "pointer", "placeholder", "human review should"]
    signals = [f"draft contains '{term}'" for term in terms if term.lower() in draft.lower()]
    figure_text = json.dumps(figures, ensure_ascii=False).lower()
    if "placeholder" in figure_text or "pointer" in figure_text:
        signals.append("figure manifest declares pointer/placeholder assets")
    return signals


def figure_manifest_is_pointer_or_placeholder(figures: list[Any]) -> bool:
    if not figures:
        return True
    text = json.dumps(figures, ensure_ascii=False).lower()
    return "pointer" in text or "placeholder" in text or "source figures remain external" in text


def load_json(path: Path, label: str) -> Any:
    if not path.exists():
        raise AuditError(f"{label} not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AuditError(f"{label} is not valid JSON: {path} ({exc})") from exc


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Real-Lite Output Reality Audit",
        "",
        f"- Engineering status: `{report['engineering_status']}`",
        f"- Content quality status: `{report['content_quality_status']}`",
        f"- Trusted for demo: `{str(report['trusted_for_demo']).lower()}`",
        f"- Trusted for scientific quality: `{str(report['trusted_for_scientific_quality']).lower()}`",
        "",
        "## Checks",
        "",
    ]
    for key, value in report["checks"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Warnings", ""])
    lines.extend([f"- {warning}" for warning in report["warnings"]] or ["- None"])
    lines.extend(["", "## Next Actions", ""])
    lines.extend([f"- {item}" for item in report["next_actions"]])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
