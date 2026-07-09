#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

EXPECTED_TOP3 = ["F3I", "F47A", "P403"]
MAX_TEXT_CHARS = 10000
DOI_RE = re.compile(r"^10\.\S+/\S+$", re.I)
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
    bibliography_path = inputs / "bibliography_verification_summary.json"
    claims_path = dataset_root / "expected" / "expected_claims.draft.json"
    figures_path = dataset_root / "expected" / "expected_figures.draft.json"
    if not verified_path.exists():
        raise AuditError(f"missing verified draft: {verified_path}")
    payload = load_json(verified_path)
    bibliography = load_json(bibliography_path) if bibliography_path.exists() else None
    claims_payload = load_json(claims_path) if claims_path.exists() else None
    figures_payload = load_json(figures_path) if figures_path.exists() else None
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
        confidence = row.get("metadata_confidence")
        if confidence not in {"low", "medium", "high"}:
            blocking.append(f"{paper_id}: missing or invalid metadata_confidence")
        if row.get("needs_human_review") is not True:
            blocking.append(f"{paper_id}: needs_human_review must be true")
        doi = row.get("doi_draft")
        if doi not in (None, "", "unknown") and not DOI_RE.match(str(doi)):
            blocking.append(f"{paper_id}: doi_draft is not a DOI-shaped value")
        if "source_conflicts" not in row:
            blocking.append(f"{paper_id}: source_conflicts field is missing")

    text_files = (
        list(inputs.glob("verified_metadata/*"))
        + list(inputs.glob("verified_excerpts/*"))
        + list(inputs.glob("figure_notes/*"))
        + ([claims_path] if claims_path.exists() else [])
        + ([figures_path] if figures_path.exists() else [])
    )
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
    if bibliography is None:
        blocking.append(f"missing bibliography verification summary: {bibliography_path}")
    else:
        bibliography_papers = bibliography.get("papers") or []
        if [row.get("candidate_id") for row in bibliography_papers] != EXPECTED_TOP3:
            blocking.append("bibliography verification summary does not contain the expected Top 3")
        insufficient = [
            row.get("candidate_id")
            for row in bibliography_papers
            if row.get("verification_status") == "insufficient_metadata"
        ]
        if insufficient and bibliography.get("summary", {}).get("phase5k_ready") is not False:
            blocking.append("insufficient metadata must set phase5k_ready=false")
        for row in bibliography_papers:
            paper_id = row.get("candidate_id")
            if row.get("metadata_confidence") not in {"low", "medium", "high"}:
                blocking.append(f"{paper_id}: bibliography metadata_confidence missing")
            if row.get("human_verified") is not False:
                blocking.append(f"{paper_id}: bibliography human_verified must be false")
            if row.get("needs_human_review") is not True:
                blocking.append(f"{paper_id}: bibliography needs_human_review must be true")
            if "conflicts" not in row:
                blocking.append(f"{paper_id}: bibliography conflicts field missing")
            doi = row.get("doi_draft")
            if doi not in (None, "", "unknown") and not DOI_RE.match(str(doi)):
                blocking.append(f"{paper_id}: bibliography doi_draft is not DOI-shaped")
    if claims_payload is None:
        blocking.append(f"missing claims draft: {claims_path}")
    else:
        audit_claims(claims_payload, blocking)
    if figures_payload is None:
        blocking.append(f"missing figure notes draft: {figures_path}")
    else:
        audit_figures(figures_payload, blocking)

    status = "fail" if blocking else "warn" if warnings else "pass"
    return {
        "status": status,
        "summary": {
            "top3_count": len(papers),
            "ids": ids,
            "human_verified_false_count": sum(1 for row in papers if row.get("human_verified") is False),
            "upload_not_used_count": sum(1 for row in papers if row.get("upload_status") == "not_uploaded"),
            "api_unused_count": sum(1 for row in papers if row.get("api_used") is False),
            "bibliography_summary_exists": bibliography is not None,
            "insufficient_metadata_count": (
                bibliography.get("summary", {}).get("insufficient_metadata_count", 0) if bibliography else None
            ),
            "phase5k_ready": bibliography.get("summary", {}).get("phase5k_ready") if bibliography else False,
            "claims_draft_exists": claims_payload is not None,
            "figures_draft_exists": figures_payload is not None,
            "claim_count": len(claims_payload.get("claims", [])) if claims_payload else None,
            "figure_note_count": len(figures_payload.get("figure_notes", [])) if figures_payload else None,
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


def audit_claims(payload: dict[str, Any], blocking: list[str]) -> None:
    claims = payload.get("claims") or []
    if payload.get("trusted_for_scientific_quality") is not False:
        blocking.append("claims draft must not be trusted_for_scientific_quality")
    counts = count_by_paper(claims)
    for paper_id in EXPECTED_TOP3:
        count = counts.get(paper_id, 0)
        if count > 4:
            blocking.append(f"{paper_id}: too many claim drafts ({count})")
    for item in claims:
        claim_id = item.get("claim_id", "unknown")
        if item.get("paper_id") not in EXPECTED_TOP3:
            blocking.append(f"{claim_id}: unexpected paper_id")
        if item.get("human_verified") is not False:
            blocking.append(f"{claim_id}: human_verified must be false")
        if item.get("needs_human_review") is not True:
            blocking.append(f"{claim_id}: needs_human_review must be true")
        if item.get("confidence") not in {"low", "medium", "high"}:
            blocking.append(f"{claim_id}: invalid confidence")
        if len(str(item.get("claim_text_draft") or "")) > 700:
            blocking.append(f"{claim_id}: claim_text_draft is too long")


def audit_figures(payload: dict[str, Any], blocking: list[str]) -> None:
    notes = payload.get("figure_notes") or []
    if payload.get("trusted_for_scientific_quality") is not False:
        blocking.append("figure notes draft must not be trusted_for_scientific_quality")
    counts = count_by_paper(notes)
    for paper_id in EXPECTED_TOP3:
        count = counts.get(paper_id, 0)
        if count > 3:
            blocking.append(f"{paper_id}: too many figure note drafts ({count})")
    for item in notes:
        note_id = item.get("figure_note_id", "unknown")
        if item.get("paper_id") not in EXPECTED_TOP3:
            blocking.append(f"{note_id}: unexpected paper_id")
        if item.get("human_verified") is not False:
            blocking.append(f"{note_id}: human_verified must be false")
        if item.get("needs_human_review") is not True:
            blocking.append(f"{note_id}: needs_human_review must be true")
        if len(str(item.get("note_draft") or "")) > 700:
            blocking.append(f"{note_id}: note_draft is too long")


def count_by_paper(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        paper_id = str(row.get("paper_id") or "")
        counts[paper_id] = counts.get(paper_id, 0) + 1
    return counts


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
