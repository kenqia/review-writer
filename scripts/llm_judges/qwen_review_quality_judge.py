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
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    parser.add_argument("--max-output-tokens", type=int, default=128)
    parser.add_argument("--compact", action="store_true")
    parser.add_argument("--task-limit", type=int, default=1)
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
    report = run_tasks(
        tasks,
        judge_mode=args.judge_mode,
        allow_network=args.allow_network,
        dry_run=args.dry_run,
        timeout_seconds=args.timeout_seconds,
        max_output_tokens=args.max_output_tokens,
        compact=args.compact,
        task_limit=args.task_limit,
    )
    write_outputs(report, args.output_json, args.output_md)
    print(f"qwen-review-quality-judge: {report['status']} ({report['summary']})")
    return 1 if report["status"] == "fail" else 0


def run_tasks(
    tasks: list[JudgeTask],
    *,
    judge_mode: str = "offline",
    allow_network: bool = False,
    dry_run: bool = False,
    timeout_seconds: float = 90.0,
    max_output_tokens: int = 128,
    compact: bool = False,
    task_limit: int = 1,
) -> dict[str, Any]:
    selected_tasks = tasks[: max(0, task_limit)]
    if judge_mode == "qwen" or dry_run:
        judge = QwenJudge(
            enabled=not dry_run,
            allow_network=allow_network,
            timeout_seconds=timeout_seconds,
            max_output_tokens=max_output_tokens,
            compact=compact,
        )
    else:
        judge = OfflineJudge()
    results = [judge.judge(task).to_dict() for task in selected_tasks]
    errors = [row for row in results if row["status"] == "error"]
    disabled = [row for row in results if row["status"] == "disabled"]
    status = "fail" if errors else ("warn" if disabled else "pass")
    network_values = {row.get("metadata", {}).get("network") for row in results}
    network = "used_once" if "used_once" in network_values else ("attempted_once" if "attempted_once" in network_values else "not_used")
    return {
        "status": status,
        "summary": f"{len(results)} judge tasks, {len(errors)} errors, {len(disabled)} disabled",
        "judge_mode": judge_mode,
        "allow_network": allow_network,
        "dry_run": dry_run,
        "timeout_seconds": timeout_seconds,
        "max_output_tokens": max_output_tokens,
        "compact_mode": compact,
        "task_limit": task_limit,
        "results": results,
        "errors": errors,
        "warnings": disabled,
        "metadata": {
            "network": network,
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
        f"- Dry run: {report['dry_run']}",
        f"- Timeout seconds: {report['timeout_seconds']}",
        f"- Max output tokens: {report['max_output_tokens']}",
        f"- Compact mode: {report['compact_mode']}",
        f"- Task limit: {report['task_limit']}",
        f"- Network: {report['metadata']['network']}",
        "",
        "## Results",
        "",
    ]
    for row in report["results"]:
        md = row.get("metadata", {})
        lines.append(f"- `{row['task_id']}` {row['status']} / {row['verdict']}: {row['rationale']}")
        lines.append(
            "  "
            + "; ".join(
                [
                    f"prompt_chars={md.get('prompt_chars', 'MISSING')}",
                    f"input_excerpt_chars={md.get('input_excerpt_chars', 'MISSING')}",
                    f"rubric_chars={md.get('rubric_chars', 'MISSING')}",
                    f"timeout_seconds={md.get('timeout_seconds', 'MISSING')}",
                    f"max_output_tokens={md.get('max_output_tokens', 'MISSING')}",
                    f"compact_mode={md.get('compact_mode', 'MISSING')}",
                    f"elapsed_seconds={md.get('elapsed_seconds', 'MISSING')}",
                    f"error_category={md.get('error_category', 'MISSING')}",
                    f"network_attempts={md.get('network_attempts', 'MISSING')}",
                ]
            )
        )
    if not report["results"]:
        lines.append("None.")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
