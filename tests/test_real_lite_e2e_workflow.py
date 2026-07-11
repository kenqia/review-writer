#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts/demo/run_real_lite_e2e.py"
DEMO_ROOT = ROOT / "demo_projects/real_lite_allene_review"
OUTPUT_ROOT = Path("/tmp/review_writer_real_lite_e2e_test")

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


def main() -> int:
    if OUTPUT_ROOT.exists():
        shutil.rmtree(OUTPUT_ROOT)
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--demo-root",
            str(DEMO_ROOT),
            "--output-root",
            str(OUTPUT_ROOT),
            "--strict",
        ],
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
        test_selected_papers_count,
        test_final_draft_exists_and_clean,
        test_quality_and_audit_reports_exist,
        test_figure_manifest_not_empty,
        test_checkpoint_log_has_nine_checkpoints,
        test_output_has_no_pdfs,
        test_run_summary_safety_markers,
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
    print(f"real-lite e2e workflow tests passed: {len(checks)}")
    return 0


def test_expected_files_exist() -> None:
    missing = [name for name in EXPECTED_FILES if not (OUTPUT_ROOT / name).exists()]
    assert not missing, f"missing expected files: {missing}"


def test_selected_papers_count() -> None:
    selected = read_json(DEMO_ROOT / "inputs/selected_papers.json")
    papers = selected.get("selected_papers") or []
    assert len(papers) >= 3, len(papers)


def test_final_draft_exists_and_clean() -> None:
    draft_path = OUTPUT_ROOT / "04_first_draft/final_draft.md"
    text = draft_path.read_text(encoding="utf-8")
    assert text.strip(), "final draft is empty"
    hits = [term for term in LEAKAGE_TERMS if term.lower() in text.lower()]
    assert not hits, f"prompt leakage terms found: {hits}"


def test_quality_and_audit_reports_exist() -> None:
    quality = read_json(OUTPUT_ROOT / "05_final_audit/quality_report.json")
    audit = read_json(OUTPUT_ROOT / "05_final_audit/final_audit_report.json")
    assert quality.get("status") in {"pass", "warn"}, quality
    assert audit.get("final_quality_gate_enforced") is True, audit


def test_figure_manifest_not_empty() -> None:
    manifest = read_json(OUTPUT_ROOT / "03_figure_redraw/figure_manifest.json")
    figures = manifest.get("figures") or []
    assert figures, manifest
    assert (OUTPUT_ROOT / "03_figure_redraw/real_lite_pointer_placeholder.svg").exists()


def test_checkpoint_log_has_nine_checkpoints() -> None:
    payload = read_json(OUTPUT_ROOT / "checkpoint_log.json")
    checkpoints = payload.get("checkpoints") or []
    assert len(checkpoints) == 9, checkpoints
    assert all(row.get("status") == "approved_mock" for row in checkpoints)
    assert all(row.get("human_review_required") is True for row in checkpoints)
    assert all("ready_for_human_review" in row.get("states", []) for row in checkpoints)


def test_output_has_no_pdfs() -> None:
    pdfs = list(OUTPUT_ROOT.rglob("*.pdf"))
    assert not pdfs, [str(path) for path in pdfs]


def test_run_summary_safety_markers() -> None:
    summary = read_json(OUTPUT_ROOT / "run_summary.json")
    assert summary["network"] == "not_used"
    assert summary["pdf_read"] == "not_used"
    assert summary["qwen"] == "not_used"
    assert summary["mineru_api"] == "not_used"
    assert summary["upload"] == "not_used"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
