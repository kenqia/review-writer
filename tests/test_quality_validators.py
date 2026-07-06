#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validators" / "validate_review_quality.py"
FIXTURES = ROOT / "tests" / "fixtures" / "quality"


def run_validator(name: str, *extra: str) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "report.json"
        cmd = [sys.executable, str(SCRIPT), "--draft", str(FIXTURES / name), "--output-json", str(out), *extra]
        result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
        if not out.exists():
            raise AssertionError(f"report not written for {name}: rc={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}")
        return json.loads(out.read_text(encoding="utf-8"))


def assert_status(name: str, allowed: set[str]) -> dict:
    report = run_validator(name)
    status = report.get("status")
    if status not in allowed:
        raise AssertionError(f"{name}: expected {allowed}, got {status}\n{json.dumps(report, ensure_ascii=False, indent=2)}")
    return report


def main() -> int:
    good = assert_status("good_minimal_review.md", {"pass"})
    assert good["llm_judge_tasks"], "good fixture should still produce title/section LLM judge tasks"

    bad_citations = assert_status("bad_citation_order.md", {"fail"})
    assert any(row["rule_id"] == "CRQ002_CITATION_CALLOUT_ORDER" for row in bad_citations["errors"])

    bad_caption = assert_status("bad_duplicate_caption.md", {"fail"})
    assert any(row["rule_id"] == "CRQ003_DUPLICATE_CAPTIONS" for row in bad_caption["errors"])

    bad_leakage = assert_status("bad_prompt_leakage.md", {"fail", "warn"})
    assert any(row["rule_id"] == "CRQ008_PROMPT_WORKFLOW_LEAKAGE" for row in bad_leakage["checks"])

    bad_figure = assert_status("bad_missing_figure.md", {"fail"})
    assert any(row["rule_id"] == "CRQ001_SOURCE_FIGURE_TRACEABILITY" for row in bad_figure["errors"])

    print("quality validator tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
