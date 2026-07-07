#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.judges import JudgeTask, OfflineJudge, QwenJudge


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline-first Qwen review quality judge")
    parser.add_argument("--input-md", type=Path)
    parser.add_argument("--judge-mode", choices=["offline", "qwen"], default="offline")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-md", type=Path)
    args = parser.parse_args()

    if args.input_md:
        if not args.input_md.exists():
            print(f"ERROR: input markdown not found: {args.input_md}", file=sys.stderr)
            return 2
        text = args.input_md.read_text(encoding="utf-8", errors="ignore")[:3000]
    else:
        text = "# Offline Judge Fixture\n\nThis dry-run checks judge wiring only."

    tasks = [
        JudgeTask(
            task_id="dry_run_title_alignment",
            rule_id="CRQ007_REVIEW_TITLE_FIT",
            task_type="review_title_alignment",
            input_text=text,
            rubric="Judge whether the title matches the body. Do not generate manuscript prose.",
        )
    ]
    report = run_tasks(tasks, judge_mode=args.judge_mode, allow_network=args.allow_network, dry_run=args.dry_run)
    write_outputs(report, args.output_json, args.output_md)
    print(f"qwen-review-quality-judge: {report['status']} ({report['summary']})")
    return 1 if report["status"] == "fail" else 0


def run_tasks(
    tasks: list[JudgeTask],
    *,
    judge_mode: str = "offline",
    allow_network: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    if judge_mode == "qwen":
        judge = QwenJudge(enabled=not dry_run, allow_network=allow_network)
    else:
        judge = OfflineJudge()
    results = [judge.judge(task).to_dict() for task in tasks]
    errors = [row for row in results if row["status"] == "error"]
    disabled = [row for row in results if row["status"] == "disabled"]
    status = "fail" if errors else ("warn" if disabled else "pass")
    return {
        "status": status,
        "summary": f"{len(results)} judge tasks, {len(errors)} errors, {len(disabled)} disabled",
        "judge_mode": judge_mode,
        "allow_network": allow_network,
        "results": results,
        "errors": errors,
        "warnings": disabled,
        "metadata": {
            "network": "not_used" if not allow_network else "allowed_by_flag",
            "paper_body_read": "not_read",
            "uploads": "not_used",
            "knowledge_base_created": "not_used",
            "image_api": "not_used",
        },
    }


def write_outputs(report: dict[str, Any], output_json: Path | None, output_md: Path | None) -> None:
    if output_json:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if output_md:
        output_md.parent.mkdir(parents=True, exist_ok=True)
        output_md.write_text(render_markdown(report), encoding="utf-8")


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Qwen Review Quality Judge Report",
        "",
        f"- Status: {report['status']}",
        f"- Summary: {report['summary']}",
        f"- Judge mode: {report['judge_mode']}",
        f"- Allow network: {report['allow_network']}",
        f"- Network: {report['metadata']['network']}",
        "",
        "## Results",
        "",
    ]
    for row in report["results"]:
        lines.append(f"- `{row['task_id']}` {row['status']} / {row['verdict']}: {row['rationale']}")
    if not report["results"]:
        lines.append("None.")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
