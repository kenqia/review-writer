#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

EXPECTED_TOP3 = ["F3I", "F47A", "P403"]
ROLE_SET = {"review_background", "representative_method", "recent_progress"}
READ_SCOPE = "filename_metadata_or_first_page_only"
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{12,}"),
    re.compile(r"api[_-]?key\s*[:=]\s*[^<\s]+", re.I),
    re.compile(r"token\s*[:=]\s*[^<\s]+", re.I),
    re.compile(r"secret\s*[:=]\s*[^<\s]+", re.I),
]


class VerificationError(Exception):
    pass


def main() -> int:
    args = parse_args()
    try:
        report = verify_pdfs(args.dataset_root, args.paper_root)
    except VerificationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.output_json:
        write_json(args.output_json, report)
    if args.output_md:
        write_markdown(args.output_md, report)
    print(
        "clean-3paper-pdf-verification: "
        f"{report['status']} top3={len(report['papers'])} "
        f"found={report['summary']['found_count']}"
    )
    return 1 if args.strict and report["errors"] else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify approved clean 3-paper PDF candidates with a read-only scope.")
    parser.add_argument("--dataset-root", type=Path, default=Path("demo_projects/clean_3paper_allene_review"))
    parser.add_argument("--paper-root", type=Path, default=Path("chem_papers"))
    parser.add_argument("--output-json", type=Path, default=Path("/tmp/clean_3paper_pdf_verification.json"))
    parser.add_argument("--output-md", type=Path, default=Path("/tmp/clean_3paper_pdf_verification.md"))
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def verify_pdfs(dataset_root: Path, paper_root: Path) -> dict[str, Any]:
    approval = load_json(dataset_root / "inputs" / "candidate_approval_pack.json")
    rows = approval.get("recommended_top3") or []
    if [row.get("candidate_id") for row in rows] != EXPECTED_TOP3:
        raise VerificationError("approval pack top3 does not match expected F3I/F47A/P403 order")

    errors: list[str] = []
    warnings: list[str] = []
    papers = [verify_one(row, paper_root, errors, warnings) for row in rows]
    found_count = sum(1 for row in papers if row["pdf_exists"])
    all_human_unverified = all(row["human_verified"] is False for row in papers)
    if not all_human_unverified:
        errors.append("verified draft must keep all human_verified=false")

    status = "fail" if errors else "warn" if warnings else "pass"
    return {
        "status": status,
        "summary": {
            "expected_ids": EXPECTED_TOP3,
            "found_count": found_count,
            "read_scope": READ_SCOPE,
            "pdf_body_read": "not_used",
            "full_chem_papers_scan": "not_used",
            "verification_level": "verified_draft_not_final",
        },
        "papers": papers,
        "errors": errors,
        "warnings": warnings,
        "safety": {
            "network": "not_used",
            "qwen": "not_used",
            "mineru_api": "not_used",
            "bailian": "not_used",
            "upload": "not_used",
            "knowledge_base": "not_created",
            "image_api": "not_used",
            "raw_pdf_text_saved": "not_used",
        },
    }


def verify_one(row: dict[str, Any], paper_root: Path, errors: list[str], warnings: list[str]) -> dict[str, Any]:
    candidate_id = str(row.get("candidate_id") or "")
    filename = Path(str(row.get("filename") or "")).name
    pdf_path = paper_root / filename
    if not filename:
        errors.append(f"{candidate_id}: missing filename")
    pdf_exists = pdf_path.exists() and pdf_path.is_file()
    if not pdf_exists:
        errors.append(f"{candidate_id}: PDF not found at {paper_root / filename}")
    role = str(row.get("role") or "")
    if role not in ROLE_SET:
        warnings.append(f"{candidate_id}: role is outside expected role set: {role}")
    size_bytes = pdf_path.stat().st_size if pdf_exists else 0
    title_signal = title_signal_score(str(row.get("inferred_title") or ""), filename)
    if title_signal < 0.45:
        warnings.append(f"{candidate_id}: weak title signal in filename")
    status = "verified_draft" if pdf_exists else "needs_human_review"
    return {
        "candidate_id": candidate_id,
        "pdf_path": str(pdf_path),
        "pdf_exists": pdf_exists,
        "file_size_bytes": size_bytes,
        "title_signal_in_filename": round(title_signal, 3),
        "inferred_title": row.get("inferred_title") or "unknown",
        "inferred_year": row.get("inferred_year") if row.get("inferred_year") is not None else "unknown",
        "inferred_journal": row.get("inferred_journal") or "unknown",
        "candidate_role": role,
        "candidate_role_plausible": role in ROLE_SET,
        "verification_status": status,
        "human_verified": False,
        "needs_human_review": True,
        "pdf_read_scope": READ_SCOPE,
        "upload_status": "not_uploaded",
        "api_used": False,
        "notes": [
            "PDF presence and filename signal were checked only for the approved Top 3.",
            "No long PDF body text was extracted or stored.",
            "Title/authors/DOI/claims/figures still require human confirmation.",
        ],
    }


def title_signal_score(title: str, filename: str) -> float:
    title_tokens = meaningful_tokens(title)
    file_tokens = set(meaningful_tokens(filename.replace("-", " ").replace("_", " ")))
    if not title_tokens:
        return 0.0
    overlap = sum(1 for token in title_tokens if token in file_tokens)
    return overlap / len(title_tokens)


def meaningful_tokens(text: str) -> list[str]:
    stop = {"the", "and", "of", "in", "with", "for", "a", "an", "on", "to", "via", "type"}
    return [token for token in re.findall(r"[a-z0-9]+", text.lower()) if len(token) > 2 and token not in stop]


def load_json(path: Path) -> Any:
    if not path.exists():
        raise VerificationError(f"required file not found: {path}")
    text = path.read_text(encoding="utf-8")
    if any(pattern.search(text) for pattern in SECRET_PATTERNS):
        raise VerificationError(f"secret-like pattern found in {path}")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise VerificationError(f"invalid JSON: {path} ({exc})") from exc


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_markdown(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Clean 3-Paper PDF Verification Draft",
        "",
        f"Status: `{payload['status']}`",
        f"Found PDFs: {payload['summary']['found_count']}/3",
        f"Read scope: `{payload['summary']['read_scope']}`",
        "",
        "| candidate | status | path | size |",
        "| --- | --- | --- | ---: |",
    ]
    for row in payload["papers"]:
        lines.append(
            f"| {row['candidate_id']} | {row['verification_status']} | `{row['pdf_path']}` | "
            f"{row['file_size_bytes']} |"
        )
    lines.extend(
        [
            "",
            "Safety: no network, no Qwen, no MinerU API, no upload, no knowledge base, no image API.",
            "This is a verified draft only; human verification remains required.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
