#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET_ROOT = ROOT / "demo_projects/clean_3paper_allene_review"
CHECKER = ROOT / "scripts/demo/check_clean_3paper_approval_pack.py"


def main() -> int:
    result = subprocess.run(
        [sys.executable, str(CHECKER), "--dataset-root", str(DATASET_ROOT), "--strict"],
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

    payload = json.loads((DATASET_ROOT / "inputs/candidate_approval_pack.json").read_text(encoding="utf-8"))
    text = (DATASET_ROOT / "inputs/candidate_approval_pack.md").read_text(encoding="utf-8")
    checks = [
        test_top3_and_alternatives,
        test_candidates_not_verified,
        test_user_options_present,
        test_authorization_text_present,
        test_no_forbidden_markers,
    ]
    failures: list[str] = []
    for check in checks:
        try:
            check(payload, text)
            print(f"PASS {check.__name__}")
        except AssertionError as exc:
            failures.append(f"{check.__name__}: {exc}")
            print(f"FAIL {check.__name__}: {exc}")
    if failures:
        return 1
    print(f"clean 3-paper approval pack tests passed: {len(checks)}")
    return 0


def test_top3_and_alternatives(payload: dict, text: str) -> None:
    assert len(payload["recommended_top3"]) == 3
    assert len(payload["alternatives"]) >= 5
    assert [row["candidate_id"] for row in payload["recommended_top3"]] == ["F3I", "F47A", "P403"]


def test_candidates_not_verified(payload: dict, text: str) -> None:
    assert all(row["human_verified"] is False for row in payload["recommended_top3"])
    assert all(row["needs_pdf_read_verification"] is True for row in payload["recommended_top3"])
    assert "human_verified: true" not in text


def test_user_options_present(payload: dict, text: str) -> None:
    assert "Option A: accept Top 3" in text
    assert "Option B: replace candidate ___ with alternative ___" in text
    assert "Option C: regenerate candidates with changed topic focus" in text


def test_authorization_text_present(payload: dict, text: str) -> None:
    assert payload["next_stage_authorization_text"] == "allow read-only verify top 3 PDFs"
    assert "allow read-only verify top 3 PDFs" in text


def test_no_forbidden_markers(payload: dict, text: str) -> None:
    combined = json.dumps(payload, ensure_ascii=False) + text
    assert "%PDF-" not in combined
    assert "/home/kenqia" not in combined
    assert "C:\\Users\\26960" not in combined
    assert "sk-" not in combined
    assert "api_key=" not in combined.lower()


if __name__ == "__main__":
    raise SystemExit(main())
