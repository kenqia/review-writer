#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

EXPECTED_TOP3 = ["F3I", "F47A", "P403"]
MAX_TEXT_CHARS = 2500
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{12,}"),
    re.compile(r"api[_-]?key\s*[:=]\s*[^<\s]+", re.I),
    re.compile(r"token\s*[:=]\s*[^<\s]+", re.I),
    re.compile(r"secret\s*[:=]\s*[^<\s]+", re.I),
]
PDF_BODY_MARKERS = ["%PDF-", "endobj", "xref", "trailer", "/Type /Page"]
RAW_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}


class AuditError(Exception):
    pass


def main() -> int:
    args = parse_args()
    try:
        report = audit_dataset(args.dataset_root)
    except AuditError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.output_json:
        write_json(args.output_json, report)
    if args.output_md:
        write_markdown(args.output_md, report)
    print(
        "clean-3paper-dataset-audit: "
        f"{report['status']} top3={report['summary']['top3_count']} "
        f"trusted_for_scientific_quality={report['trusted_for_scientific_quality']}"
    )
    return 1 if args.strict and report["blocking_issues"] else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit clean 3-paper verified-draft dataset safety.")
    parser.add_argument("--dataset-root", type=Path, default=Path("demo_projects/clean_3paper_allene_review"))
    parser.add_argument("--output-json", type=Path, default=Path("/tmp/clean_3paper_audit.json"))
    parser.add_argument("--output-md", type=Path, default=Path("/tmp/clean_3paper_audit.md"))
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def audit_dataset(dataset_root: Path) -> dict[str, Any]:
    inputs = dataset_root / "inputs"
    verified_path = inputs / "selected_papers.verified_draft.json"
    if not verified_path.exists():
        raise AuditError(f"missing verified draft: {verified_path}")
    payload = load_json(verified_path)
    papers = payload.get("papers") or []
    blocking: list[str] = []
    warnings: list[str] = []

    ids = [row.get("candidate_id") for row in papers]
    if ids != EXPECTED_TOP3:
        blocking.append(f"expected top3 {EXPECTED_TOP3}, got {ids}")
    if len(papers) != 3:
        blocking.append(f"expected 3 papers, got {len(papers)}")

    for row in papers:
        paper_id = str(row.get("candidate_id") or "unknown")
        if row.get("human_verified") is not False:
            blocking.append(f"{paper_id}: human_verified must remain false")
        if row.get("upload_status") != "not_uploaded":
            blocking.append(f"{paper_id}: upload_status must be not_uploaded")
        if row.get("api_used") is not False:
            blocking.append(f"{paper_id}: api_used must be false")
        if row.get("verification_status") not in {"verified_draft", "needs_human_review"}:
            blocking.append(f"{paper_id}: invalid verification_status")
        if row.get("trusted_for_scientific_quality") is not False:
            blocking.append(f"{paper_id}: scientific quality trust must remain false")

    text_files = list(inputs.glob("verified_metadata/*")) + list(inputs.glob("verified_excerpts/*")) + list(inputs.glob("figure_notes/*"))
    for path in text_files:
        if path.suffix.lower() in RAW_IMAGE_SUFFIXES:
            blocking.append(f"raw image file found in draft inputs: {path}")
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if len(text) > MAX_TEXT_CHARS:
            blocking.append(f"{path}: text exceeds short-draft limit ({len(text)} chars)")
        if any(marker in text for marker in PDF_BODY_MARKERS):
            blocking.append(f"{path}: PDF body marker found")
        if any(pattern.search(text) for pattern in SECRET_PATTERNS):
            blocking.append(f"{path}: secret-like pattern found")

    if payload.get("trusted_for_scientific_quality") is not False:
        blocking.append("dataset-level trusted_for_scientific_quality must remain false")
    if payload.get("trusted_for_engineering_fixture") is not True:
        warnings.append("dataset is not marked as trusted_for_engineering_fixture")

    status = "fail" if blocking else "warn" if warnings else "pass"
    return {
        "status": status,
        "summary": {
            "top3_count": len(papers),
            "ids": ids,
            "human_verified_false_count": sum(1 for row in papers if row.get("human_verified") is False),
            "upload_not_used_count": sum(1 for row in papers if row.get("upload_status") == "not_uploaded"),
            "api_unused_count": sum(1 for row in papers if row.get("api_used") is False),
        },
        "trusted_for_engineering_fixture": payload.get("trusted_for_engineering_fixture") is True,
        "trusted_for_scientific_quality": False,
        "blocking_issues": blocking,
        "warnings": warnings,
        "safety": {
            "network": "not_used",
            "pdf_body_read": "not_used",
            "qwen": "not_used",
            "mineru_api": "not_used",
            "bailian": "not_used",
            "upload": "not_used",
            "knowledge_base": "not_created",
            "image_api": "not_used",
        },
    }


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AuditError(f"invalid JSON: {path} ({exc})") from exc


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# Clean 3-Paper Dataset Audit",
        "",
        f"Status: `{payload['status']}`",
        f"Top 3 count: {payload['summary']['top3_count']}",
        f"Trusted for engineering fixture: `{payload['trusted_for_engineering_fixture']}`",
        f"Trusted for scientific quality: `{payload['trusted_for_scientific_quality']}`",
        "",
        "This audit intentionally keeps scientific quality untrusted until human review is complete.",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
