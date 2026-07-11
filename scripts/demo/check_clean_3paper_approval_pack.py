#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{12,}"),
    re.compile(r"api[_-]?key\s*[:=]\s*[^<\s]+", re.I),
    re.compile(r"token\s*[:=]\s*[^<\s]+", re.I),
    re.compile(r"secret\s*[:=]\s*[^<\s]+", re.I),
]
LOCAL_PATH_PATTERNS = [
    re.compile(re.escape("/home/" + "kenqia")),
    re.compile(re.escape("/mnt/c/Users/" + "26960")),
    re.compile(re.escape("C:\\" + "Users\\" + "26960")),
    re.compile(r"Desktop[\\/]review-writer"),
]
PDF_CONTENT_MARKERS = [
    "%PDF-",
    "endobj",
    "xref",
    "trailer",
    "/Type /Page",
]
AUTH_TEXT = "allow read-only verify top 3 PDFs"


class CheckError(Exception):
    pass


def main() -> int:
    args = parse_args()
    try:
        report = check_pack(args.dataset_root)
    except CheckError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"clean-3paper-approval-check: {report['status']} ({len(report['checks'])} checks)")
    if args.strict and report["errors"]:
        for error in report["errors"]:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check clean 3-paper approval pack safety and completeness.")
    parser.add_argument("--dataset-root", type=Path, default=Path("demo_projects/clean_3paper_allene_review"))
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def check_pack(dataset_root: Path) -> dict[str, Any]:
    inputs = dataset_root / "inputs"
    json_path = inputs / "candidate_approval_pack.json"
    md_path = inputs / "candidate_approval_pack.md"
    errors: list[str] = []
    checks: list[dict[str, Any]] = []

    def add(check_id: str, ok: bool, detail: str) -> None:
        checks.append({"check_id": check_id, "status": "pass" if ok else "fail", "detail": detail})
        if not ok:
            errors.append(f"{check_id}: {detail}")

    add("approval_pack_json_exists", json_path.exists(), str(json_path))
    add("approval_pack_md_exists", md_path.exists(), str(md_path))
    if not json_path.exists() or not md_path.exists():
        return {"status": "fail", "checks": checks, "errors": errors}

    payload = load_json(json_path)
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    combined = json.dumps(payload, ensure_ascii=False) + "\n" + text

    top3 = payload.get("recommended_top3") or []
    alternatives = payload.get("alternatives") or []
    add("top3_count", len(top3) == 3, f"top3={len(top3)}")
    add("alternatives_count", len(alternatives) >= 5, f"alternatives={len(alternatives)}")
    add(
        "top3_human_verified_false",
        all(row.get("human_verified") is False for row in top3),
        "all top3 must be human_verified=false",
    )
    add(
        "top3_need_pdf_verification",
        all(row.get("needs_pdf_read_verification") is True for row in top3),
        "all top3 must need PDF verification",
    )
    add("no_pdf_content_markers", not any(marker in combined for marker in PDF_CONTENT_MARKERS), "no PDF body markers")
    add("no_secret_like_text", not any(pattern.search(combined) for pattern in SECRET_PATTERNS), "no secret-like pattern")
    add("no_local_absolute_paths", not any(pattern.search(combined) for pattern in LOCAL_PATH_PATTERNS), "no personal local path")
    add("has_option_a", "Option A: accept Top 3" in text, "Option A present")
    add("has_option_b", "Option B: replace candidate ___ with alternative ___" in text, "Option B present")
    add("has_option_c", "Option C: regenerate candidates with changed topic focus" in text, "Option C present")
    add("has_authorization_text", AUTH_TEXT in combined, AUTH_TEXT)
    add(
        "safe_boundaries_present",
        all(phrase in text for phrase in ["do not upload files", "do not call external APIs", "do not create a knowledge base"]),
        "next-stage safety scope present",
    )

    return {"status": "fail" if errors else "pass", "checks": checks, "errors": errors}


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CheckError(f"invalid JSON: {path} ({exc})") from exc


if __name__ == "__main__":
    raise SystemExit(main())
