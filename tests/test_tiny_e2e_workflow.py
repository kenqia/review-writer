#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts/demo/run_tiny_e2e.py"
DEMO_ROOT = ROOT / "demo_projects/tiny_allene_review"
OUTPUT_ROOT = Path("/tmp/review_writer_tiny_e2e_test")

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
        test_quality_report_exists_and_passes,
        test_final_draft_has_no_prompt_leakage,
        test_figure_manifest_not_empty,
        test_checkpoint_log_has_nine_checkpoints,
        test_no_network_markers,
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
    print(f"tiny e2e workflow tests passed: {len(checks)}")
    return 0


def test_expected_files_exist() -> None:
    missing = [name for name in EXPECTED_FILES if not (OUTPUT_ROOT / name).exists()]
    assert not missing, f"missing expected files: {missing}"


def test_quality_report_exists_and_passes() -> None:
    report = read_json(OUTPUT_ROOT / "05_final_audit/quality_report.json")
    assert report["status"] == "pass", report


def test_final_draft_has_no_prompt_leakage() -> None:
    text = (OUTPUT_ROOT / "04_first_draft/final_draft.md").read_text(encoding="utf-8")
    hits = [term for term in LEAKAGE_TERMS if term.lower() in text.lower()]
    assert not hits, f"prompt leakage terms found: {hits}"


def test_figure_manifest_not_empty() -> None:
    manifest = read_json(OUTPUT_ROOT / "03_figure_redraw/figure_manifest.json")
    assert manifest.get("figures"), manifest
    assert (OUTPUT_ROOT / "03_figure_redraw/allene_placeholder.svg").exists()


def test_checkpoint_log_has_nine_checkpoints() -> None:
    payload = read_json(OUTPUT_ROOT / "checkpoint_log.json")
    checkpoints = payload.get("checkpoints") or []
    assert len(checkpoints) == 9, checkpoints
    assert all(row.get("status") == "approved_mock" for row in checkpoints)
    assert all("ready_for_human_review" in row.get("states", []) for row in checkpoints)


def test_no_network_markers() -> None:
    report = read_json(OUTPUT_ROOT / "05_final_audit/final_audit_report.json")
    assert report["network"] == "not_used"
    assert report["qwen"] == "not_called"
    assert report["mineru"] == "not_called"
    assert report["pdf_body_read"] == "not_read"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
