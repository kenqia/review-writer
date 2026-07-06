#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


STAGES: list[dict[str, Any]] = [
    {
        "id": "discovery",
        "name": "Topic discovery",
        "dir": "00_discovery",
        "skill": "review-topic-paper-discovery",
        "required": [
            "topic_input.md",
            "keyword_set.draft.json",
            "combined_results_by_keyword.json",
            "selected_discovery_results.json",
            "human_check_state.json",
        ],
        "human_check": "Check keywords and selected papers in http://127.0.0.1:8765/discovery.",
        "confirmed_by": ["human_check_state.json"],
    },
    {
        "id": "matrix_outline",
        "name": "Literature matrix and outline",
        "dir": "01_matrix_outline",
        "skill": "review-literature-matrix-outline",
        "required": [
            "paper_reading_notes.json",
            "literature_matrix.json",
            "literature_matrix.csv",
            "outline_options.md",
            "matrix_outline_report.md",
        ],
        "human_check": "Choose or edit the outline and write selected_outline.md.",
        "confirmed_by": ["selected_outline.md"],
    },
    {
        "id": "section_blueprint",
        "name": "Section blueprint",
        "dir": "01_matrix_outline",
        "skill": "review-section-blueprint",
        "required": [
            "section_blueprint.json",
            "section_writing_plan.md",
        ],
        "human_check": "Check section_blueprint.json and section_writing_plan.md before section drafting.",
        "confirmed_by": ["human_check.json"],
    },
    {
        "id": "section_drafting",
        "name": "Section drafting and figure picking",
        "dir": "02_section_drafting",
        "skill": "review-section-drafting-figure-picking",
        "required": [
            "section_tasks.json",
            "section_drafts.json",
            "section_drafts.md",
            "paper_figure_inventory.json",
            "paper_figure_candidates.json",
            "figure_candidates.json",
            "section_drafting_report.md",
        ],
        "human_check": "Check section drafts and figure candidates before redraw.",
        "confirmed_by": ["human_check.json"],
    },
    {
        "id": "figure_redraw",
        "name": "Figure style redraw",
        "dir": "03_figure_redraw",
        "skill": "review-figure-style-redraw",
        "required": [
            "style_config.json",
            "source_figure_manifest.json",
            "redrawn_figure_manifest.json",
            "figure_redraw_report.md",
        ],
        "human_check": "Compare every redrawn figure with its source before merging.",
        "confirmed_by": ["human_check.json"],
        "skip_anchor": "skip_reason.md",
    },
    {
        "id": "first_draft",
        "name": "First draft merge",
        "dir": "04_first_draft",
        "skill": "review-draft-merge-polish",
        "required": [
            "draft_bundle.json",
            "first_draft.md",
            "merge_report.md",
            "remaining_issues.md",
        ],
        "human_check": "Review the unified first draft in http://127.0.0.1:8765/draft.",
        "confirmed_by": ["human_check.json"],
    },
    {
        "id": "final_audit",
        "name": "Final content and format audit",
        "dir": "05_final_audit",
        "skill": "review-final-audit-release",
        "required": [
            "format_scan.json",
            "format_scan.md",
            "content_audit_report.md",
            "format_audit_report.md",
            "final_draft.md",
            "final_remaining_issues.md",
            "release_report.md",
        ],
        "human_check": "Check final_draft.md and release_report.md before export.",
        "confirmed_by": ["human_check.json"],
    },
    {
        "id": "docx_export",
        "name": "DOCX export",
        "dir": "05_final_audit",
        "skill": "review-export-docx",
        "required": [
            "final_draft.docx",
        ],
        "human_check": "Download final_draft.docx from /final and open it in Word to confirm styling.",
        "confirmed_by": ["human_check.json"],
    },
]


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def discover_projects(review_root: Path) -> list[str]:
    root = review_root / "review-projects"
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())


def stage_status(project: Path, stage: dict[str, Any]) -> dict[str, Any]:
    stage_dir = project / stage["dir"]
    missing = [name for name in stage["required"] if not (stage_dir / name).exists()]
    semantic_issues: list[str] = []
    if stage["id"] == "figure_redraw":
        skip_anchor = stage_dir / stage.get("skip_anchor", "skip_reason.md")
        skip_active = skip_anchor.exists() and bool(skip_anchor.read_text(encoding="utf-8", errors="ignore").strip())
        if skip_active:
            # User explicitly opted out. Clear `missing` so the stage can complete.
            missing = []
        else:
            manifest = read_json(stage_dir / "redrawn_figure_manifest.json")
            if isinstance(manifest, dict):
                if manifest.get("status") == "skipped":
                    semantic_issues.append("figure_redraw_skipped_without_reason")
                figures = manifest.get("figures")
                if isinstance(figures, list) and not any(isinstance(f, dict) and f.get("status") == "redrawn" for f in figures):
                    semantic_issues.append("no_redrawn_figures")
            elif not missing:
                semantic_issues.append("invalid_redrawn_figure_manifest")
    if stage["id"] == "section_drafting":
        candidates = read_json(stage_dir / "figure_candidates.json")
        if isinstance(candidates, dict):
            figures = candidates.get("figures")
        else:
            figures = candidates
        if isinstance(figures, list) and not figures:
            semantic_issues.append("empty_figure_candidates")
        elif not isinstance(figures, list) and "figure_candidates.json" not in missing:
            semantic_issues.append("invalid_figure_candidates")
        sections_dir = stage_dir / "sections"
        section_files = sorted(sections_dir.glob("*.md")) if sections_dir.exists() else []
        if not section_files:
            semantic_issues.append("sections_directory_empty")
        tasks = read_json(stage_dir / "section_tasks.json")
        task_list = tasks if isinstance(tasks, list) else (tasks.get("sections") if isinstance(tasks, dict) else None)
        if isinstance(task_list, list) and section_files:
            have = {p.stem for p in section_files}
            missing_ids = [t.get("section_id") for t in task_list if isinstance(t, dict) and t.get("section_id") and t["section_id"] not in have]
            if missing_ids:
                semantic_issues.append("section_files_missing_for_tasks")
    if stage["id"] == "docx_export":
        # DOCX is only valid when the final audit passed all blocking checks.
        final_scan = read_json(project / "05_final_audit" / "format_scan.json")
        if isinstance(final_scan, dict) and final_scan.get("blocking_issues"):
            semantic_issues.append("final_audit_has_blocking_issues")
        elif not (project / "05_final_audit" / "final_draft.md").exists():
            semantic_issues.append("final_draft_md_missing")
    if stage["id"] in {"first_draft", "final_audit"}:
        draft_path = stage_dir / ("first_draft.md" if stage["id"] == "first_draft" else "final_draft.md")
        if draft_path.exists():
            draft_text = draft_path.read_text(encoding="utf-8", errors="ignore")
            import re as _re
            has_image = bool(_re.search(r"!\[[^\]]*\]\(([^)]+)\)", draft_text))
            has_citation = bool(_re.search(r"\[\d+(?:\s*[-,]\s*\d+)*\]", draft_text))
            has_references = bool(_re.search(
                r"^\s*#{1,6}\s*(references|reference list|bibliography|cited literature|参考文献)\s*$",
                draft_text,
                _re.I | _re.M,
            ))
            skip_reason = project / "03_figure_redraw" / "skip_reason.md"
            figures_skipped_with_reason = skip_reason.exists() and bool(skip_reason.read_text(encoding="utf-8", errors="ignore").strip())
            if not has_image and not figures_skipped_with_reason:
                semantic_issues.append("draft_has_no_figures")
            if not has_citation:
                semantic_issues.append("draft_has_no_citation_callouts")
            if not has_references:
                semantic_issues.append("missing_references_section")
        if stage["id"] == "final_audit":
            scan = read_json(stage_dir / "format_scan.json")
            if isinstance(scan, dict):
                blockers = scan.get("blocking_issues") or []
                for issue in blockers:
                    if issue not in semantic_issues:
                        semantic_issues.append(issue)
    complete = not missing and not semantic_issues
    expects_confirmation = bool(stage.get("confirmed_by"))
    confirmed = False
    confirmation_notes: list[str] = []
    for name in stage.get("confirmed_by", []):
        path = stage_dir / name
        if not path.exists():
            continue
        if path.suffix == ".json":
            data = read_json(path)
            if isinstance(data, dict):
                confirmed = bool(data.get("confirmed") or data.get("human_confirmed") or data.get("reviewed"))
                if confirmed:
                    confirmation_notes.append(name)
        else:
            if path.read_text(encoding="utf-8", errors="ignore").strip():
                confirmed = True
                confirmation_notes.append(name)
    if expects_confirmation and not confirmed:
        complete = False
    return {
        "id": stage["id"],
        "name": stage["name"],
        "skill": stage["skill"],
        "directory": str(stage_dir),
        "complete": complete,
        "expects_confirmation": expects_confirmation,
        "missing": missing,
        "semantic_issues": semantic_issues,
        "human_check": stage["human_check"],
        "confirmed": confirmed,
        "confirmation_notes": confirmation_notes,
        "skipped_by_user": bool(stage.get("skip_anchor")) and (stage_dir / stage.get("skip_anchor", "")).exists(),
    }


def summarize(review_root: Path, project_id: str) -> dict[str, Any]:
    project = review_root / "review-projects" / project_id
    if not project.exists():
        return {
            "project_id": project_id,
            "exists": False,
            "error": f"Project not found: {project}",
            "available_projects": discover_projects(review_root),
        }

    stages = [stage_status(project, stage) for stage in STAGES]
    completed = [s for s in stages if s["complete"]]
    # Skip stages explicitly opted out by the user (skip_reason.md present).
    next_stage = next((s for s in stages if not s["complete"] and not s.get("skipped_by_user")), None)
    blocking_check = None
    # A stage that has all artifacts/checks done but is still waiting for human
    # confirmation should drive the blocking message uniformly.
    for stage in stages:
        if stage.get("expects_confirmation") and not stage["confirmed"]:
            inputs_ready = not stage["missing"] and not stage["semantic_issues"]
            if inputs_ready:
                blocking_check = stage["human_check"]
                break
    if blocking_check is None and next_stage is None:
        blocking_check = stages[-1]["human_check"]

    return {
        "project_id": project_id,
        "exists": True,
        "project_dir": str(project),
        "completed_stage_ids": [s["id"] for s in completed],
        "next_stage": next_stage,
        "blocking_human_check": blocking_check,
        "stages": stages,
    }


def print_text(summary: dict[str, Any]) -> None:
    if not summary.get("exists"):
        print(f"Project: {summary['project_id']}")
        print(summary["error"])
        if summary.get("available_projects"):
            print("Available projects:")
            for project in summary["available_projects"]:
                print(f"- {project}")
        return

    print(f"Project: {summary['project_id']}")
    print(f"Completed stages: {', '.join(summary['completed_stage_ids']) or 'none'}")
    if summary.get("blocking_human_check"):
        print(f"Blocking human check: {summary['blocking_human_check']}")
    next_stage = summary.get("next_stage")
    if next_stage:
        print(f"Next skill: {next_stage['skill']}")
        print(f"Next stage: {next_stage['name']}")
        if next_stage["missing"]:
            print("Missing files:")
            for name in next_stage["missing"]:
                print(f"- {name}")
        if next_stage.get("semantic_issues"):
            print("Stage issues:")
            for issue in next_stage["semantic_issues"]:
                print(f"- {issue}")
    else:
        print("Next skill: none")
        print("Status: final audit outputs exist")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect review project workflow status.")
    parser.add_argument("--review-root", default=str(Path(__file__).resolve().parents[3]))
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = summarize(Path(args.review_root).resolve(), args.project_id)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print_text(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
