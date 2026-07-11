#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/demo/build_real_lite_manifest.py"
DEMO = ROOT / "demo_projects/real_lite_allene_review"
GAP = ROOT / "docs/demo/real_lite_asset_gap_report.md"


def main() -> int:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--search-root",
            str(ROOT),
            "--repo-root",
            str(ROOT),
            "--output-json",
            "/tmp/real_lite_asset_manifest_test.json",
            "--output-md",
            "/tmp/real_lite_asset_manifest_test.md",
            "--max-papers",
            "5",
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
    report = json.loads(Path("/tmp/real_lite_asset_manifest_test.json").read_text(encoding="utf-8"))
    if DEMO.exists():
        tests = [
            test_selected_papers_exist,
            test_each_paper_has_metadata_or_markdown,
            test_no_pdf_content_or_files,
            test_outputs_only_gitkeep,
            test_safety_report,
        ]
    else:
        tests = [test_gap_report_exists]
    failures: list[str] = []
    for test in tests:
        try:
            test(report)
            print(f"PASS {test.__name__}")
        except AssertionError as exc:
            failures.append(f"{test.__name__}: {exc}")
            print(f"FAIL {test.__name__}: {exc}")
    if failures:
        return 1
    print(f"real-lite manifest tests passed: {len(tests)}")
    return 0


def test_selected_papers_exist(report: dict) -> None:
    selected_path = DEMO / "inputs/selected_papers.json"
    assert selected_path.exists()
    payload = json.loads(selected_path.read_text(encoding="utf-8"))
    selected = payload.get("selected_papers") or []
    assert len(selected) >= 3
    assert len(report.get("selected_papers") or []) >= 3


def test_each_paper_has_metadata_or_markdown(report: dict) -> None:
    for row in report["selected_papers"]:
        paper_id = row["paper_id"]
        metadata = DEMO / f"inputs/paper_metadata/{paper_id}.metadata.json"
        markdown = DEMO / f"inputs/mineru_markdown/{paper_id}.excerpt.md"
        assert metadata.exists() or markdown.exists(), paper_id


def test_no_pdf_content_or_files(report: dict) -> None:
    pdfs = list(DEMO.rglob("*.pdf"))
    assert not pdfs, pdfs
    for path in DEMO.rglob("*"):
        if path.is_file() and path.name != ".gitkeep":
            data = path.read_bytes()[:8]
            assert not data.startswith(b"%PDF"), str(path)


def test_outputs_only_gitkeep(report: dict) -> None:
    files = sorted(path.name for path in (DEMO / "outputs").iterdir() if path.is_file())
    assert files == [".gitkeep"], files


def test_safety_report(report: dict) -> None:
    safety = report["safety"]
    assert safety["pdf_body_read"] == "not_read"
    assert safety["api_calls"] == "not_used"
    assert safety["qwen"] == "not_called"
    assert safety["mineru_api"] == "not_called"
    assert safety["uploads"] == "not_used"


def test_gap_report_exists(report: dict) -> None:
    assert report["status"] == "blocked"
    assert GAP.exists()
    text = GAP.read_text(encoding="utf-8")
    assert "blocked_reason" in text


if __name__ == "__main__":
    raise SystemExit(main())
