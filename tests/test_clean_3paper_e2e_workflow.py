#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts/demo/run_clean_3paper_e2e.py"
DEMO_ROOT = ROOT / "demo_projects/clean_3paper_allene_review"
OUTPUT_ROOT = Path("/tmp/review_writer_clean_3paper_e2e_test")

EXPECTED_FILES = [
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
    "eval/clean_3paper_eval_report.json",
    "eval/clean_3paper_eval_report.md",
    "export/final_draft.md",
    "run_summary.json",
]

LEAKAGE_TERMS = ["写作思路", "本节应当", "请生成", "LLM judge", "rule pack", "workflow", "不要直接出现在正文"]


def main() -> int:
    if OUTPUT_ROOT.exists():
        shutil.rmtree(OUTPUT_ROOT)
    result = subprocess.run(
        [sys.executable, str(RUNNER), "--demo-root", str(DEMO_ROOT), "--output-root", str(OUTPUT_ROOT), "--strict"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        return 1
    checks = [
        test_expected_files_exist,
        test_checkpoint_log_has_nine,
        test_final_draft_markers_and_no_leakage,
        test_quality_warns_for_metadata,
        test_figure_manifest_not_empty,
        test_review_pack_exists,
        test_run_summary_safety,
        test_clean_input_package_written,
    ]
    failures: list[str] = []
    for check in checks:
        try:
            check()
            print(f"PASS {check.__name__}")
        except AssertionError as exc:
            failures.append(f"{check.__name__}: {exc}")
            print(f"FAIL {check.__name__}: {exc}")
    if failures:
        return 1
    print(f"clean 3-paper e2e workflow tests passed: {len(checks)}")
    return 0


def test_expected_files_exist() -> None:
    missing = [rel for rel in EXPECTED_FILES if not (OUTPUT_ROOT / rel).exists()]
    assert not missing, missing


def test_checkpoint_log_has_nine() -> None:
    payload = read_json(OUTPUT_ROOT / "checkpoint_log.json")
    checkpoints = payload.get("checkpoints") or []
    assert len(checkpoints) == 9
    assert all(row["human_review_required"] is True for row in checkpoints)


def test_final_draft_markers_and_no_leakage() -> None:
    text = (OUTPUT_ROOT / "04_first_draft/final_draft.md").read_text(encoding="utf-8")
    assert "clean_draft" in text
    assert "needs_human_review" in text
    assert "not_final_scientific_review" in text
    hits = [term for term in LEAKAGE_TERMS if term.lower() in text.lower()]
    assert not hits, hits


def test_quality_warns_for_metadata() -> None:
    quality = read_json(OUTPUT_ROOT / "05_final_audit/quality_report.json")
    assert quality["status"] in {"pass", "warn"}
    assert not quality.get("errors")
    warnings_text = json.dumps(quality.get("warnings") or [], ensure_ascii=False)
    assert "P403" in warnings_text
    assert "missing fields" in warnings_text


def test_figure_manifest_not_empty() -> None:
    manifest = read_json(OUTPUT_ROOT / "03_figure_redraw/figure_manifest.json")
    figures = manifest.get("figures") or []
    assert figures
    assert all(row["human_verified"] is False for row in figures)
    assert (OUTPUT_ROOT / "03_figure_redraw/clean_3paper_note_placeholder.svg").exists()


def test_review_pack_exists() -> None:
    text = (OUTPUT_ROOT / "05_final_audit/clean_3paper_review_pack.md").read_text(encoding="utf-8")
    assert "clean_draft" in text
    assert "human_verified: false" in text


def test_run_summary_safety() -> None:
    summary = read_json(OUTPUT_ROOT / "run_summary.json")
    assert summary["trusted_for_scientific_quality"] is False
    assert summary["needs_human_review"] is True
    assert summary["network"] == "not_used"
    assert summary["pdf_read"] == "not_used"
    assert summary["qwen"] == "not_used"
    assert summary["mineru_api"] == "not_used"
    assert summary["upload"] == "not_used"
    assert summary["knowledge_base"] == "not_created"


def test_clean_input_package_written() -> None:
    selected = read_json(DEMO_ROOT / "inputs/selected_papers.clean_draft.json")
    assert [row["paper_id"] for row in selected["papers"]] == ["F3I", "F47A", "P403"]
    assert all(row["human_verified"] is False for row in selected["papers"])
    assert (DEMO_ROOT / "inputs/clean_registry.jsonl").exists()
    assert (DEMO_ROOT / "inputs/claims/F3I.claims.draft.json").exists()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
