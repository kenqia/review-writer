#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

EXPECTED_TOP3 = ["F3I", "F47A", "P403"]
MAX_EXCERPT_CHARS_PER_PAPER = 1200
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{12,}"),
    re.compile(r"api[_-]?key\s*[:=]\s*[^<\s]+", re.I),
    re.compile(r"token\s*[:=]\s*[^<\s]+", re.I),
    re.compile(r"secret\s*[:=]\s*[^<\s]+", re.I),
]


class ExtractionError(Exception):
    pass


def main() -> int:
    args = parse_args()
    try:
        report = extract_claims_and_figures(args.dataset_root, args.paper_root)
    except ExtractionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.output_json:
        write_json(args.output_json, report)
    if args.output_md:
        write_markdown(args.output_md, report)
    write_dataset_outputs(args.dataset_root, report)
    print(
        "clean-3paper-claims-figures: "
        f"{report['status']} claims={report['summary']['claim_count']} "
        f"figure_notes={report['summary']['figure_note_count']} "
        f"needs_manual_extraction={report['summary']['needs_manual_extraction_count']}"
    )
    return 1 if args.strict and report["errors"] else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create clean 3-paper key claims and figure notes drafts without external APIs.")
    parser.add_argument("--dataset-root", type=Path, default=Path("demo_projects/clean_3paper_allene_review"))
    parser.add_argument("--paper-root", type=Path, default=Path("chem_papers"))
    parser.add_argument("--output-json", type=Path, default=Path("/tmp/clean_3paper_claims_figures.json"))
    parser.add_argument("--output-md", type=Path, default=Path("/tmp/clean_3paper_claims_figures.md"))
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def extract_claims_and_figures(dataset_root: Path, paper_root: Path) -> dict[str, Any]:
    inputs = dataset_root / "inputs"
    bibliography = load_json(inputs / "bibliography_verification_summary.json")
    papers = bibliography.get("papers") or []
    if [row.get("candidate_id") for row in papers] != EXPECTED_TOP3:
        raise ExtractionError("bibliography summary does not contain expected Top 3 in order")
    errors: list[str] = []
    warnings: list[str] = []
    paper_reports = []
    claims = []
    figure_notes = []
    for paper in papers:
        row = extract_one_paper(paper, paper_root, errors, warnings)
        paper_reports.append(row)
        claims.extend(row["claims"])
        figure_notes.extend(row["figure_notes"])

    needs_manual = sum(1 for item in claims + figure_notes if item["evidence_source" if "evidence_source" in item else "source"] == "needs_manual_extraction")
    status = "fail" if errors else "warn" if warnings or needs_manual else "pass"
    return {
        "status": status,
        "summary": {
            "paper_ids": EXPECTED_TOP3,
            "claim_count": len(claims),
            "figure_note_count": len(figure_notes),
            "needs_manual_extraction_count": needs_manual,
            "pdf_read_scope": "filesystem_stat_only_no_text_extraction",
            "max_excerpt_chars_per_paper": MAX_EXCERPT_CHARS_PER_PAPER,
        },
        "papers": paper_reports,
        "claims": claims,
        "figure_notes": figure_notes,
        "errors": errors,
        "warnings": warnings,
        "trusted_for_scientific_quality": False,
        "safety": {
            "network": "not_used",
            "pdf_body_text_extracted": "not_used",
            "qwen": "not_used",
            "mineru_api": "not_used",
            "bailian": "not_used",
            "upload": "not_used",
            "knowledge_base": "not_created",
            "image_api": "not_used",
        },
    }


def extract_one_paper(paper: dict[str, Any], paper_root: Path, errors: list[str], warnings: list[str]) -> dict[str, Any]:
    paper_id = str(paper.get("candidate_id") or "")
    pdf_path = paper_root / Path(str(paper.get("filename") or "")).name
    if not pdf_path.exists():
        errors.append(f"{paper_id}: PDF path missing")
    pdf_size = pdf_path.stat().st_size if pdf_path.exists() else 0
    claims = draft_claims(paper)
    figure_notes = draft_figure_notes(paper)
    if paper_id == "P403" and ("authors" in paper.get("missing_fields", []) or "doi" in paper.get("missing_fields", [])):
        warnings.append("P403: authors/DOI remain missing and require human review")
    return {
        "paper_id": paper_id,
        "pdf_path": str(pdf_path),
        "pdf_exists": pdf_path.exists(),
        "pdf_size_bytes": pdf_size,
        "pdf_read_scope": "filesystem_stat_only_no_text_extraction",
        "claims": claims,
        "figure_notes": figure_notes,
        "human_verified": False,
        "needs_human_review": True,
    }


def draft_claims(paper: dict[str, Any]) -> list[dict[str, Any]]:
    paper_id = str(paper["candidate_id"])
    title = str(paper.get("verified_title_draft") or "")
    publication_type = str(paper.get("publication_type_draft") or "")
    claims: list[dict[str, Any]] = []
    if paper_id == "F3I":
        claims.append(claim(paper_id, "C1", f"The paper can serve as background for allene-centered catalytic asymmetric synthesis because its verified draft title is '{title}'.", "background", "bibliographic_metadata", "medium"))
        claims.append(claim(paper_id, "C2", "The title also signals relevance to natural product synthesis context, but specific examples still require manual extraction from the PDF.", "background", "needs_manual_extraction", "low"))
    elif paper_id == "F47A":
        claims.append(claim(paper_id, "C1", f"The paper is a representative method candidate for palladium-catalyzed asymmetric synthesis of axially chiral allenes, based on the verified draft title '{title}'.", "method", "bibliographic_metadata", "medium"))
        claims.append(claim(paper_id, "C2", "The title indicates a dibenzalacetone-related effect on enantioselectivity; the detailed mechanistic or optimization claim still needs manual PDF extraction.", "method", "needs_manual_extraction", "low"))
    elif paper_id == "P403":
        claims.append(claim(paper_id, "C1", f"The paper is a recent-progress method candidate for Pd-catalyzed asymmetric allenylation of secondary phosphine oxides, based on the verified draft title '{title}'.", "recent_progress", "bibliographic_metadata", "medium"))
        claims.append(claim(paper_id, "C2", "The title indicates enyne-type propargylic carbamates and chiral allenyl phosphine oxides as central scope elements; exact substrate scope and outcomes need manual extraction.", "recent_progress", "needs_manual_extraction", "low"))
    else:
        claims.append(claim(paper_id, "C1", f"The paper title suggests relevance to the clean 3-paper allene review: {title}", "background", "bibliographic_metadata", "low"))
    if publication_type == "review_or_background":
        claims.append(claim(paper_id, "C3", "The publication type draft marks this item as review/background rather than a single-method evidence source.", "background", "bibliographic_metadata", "medium"))
    return claims[:4]


def claim(
    paper_id: str,
    suffix: str,
    text: str,
    support_type: str,
    evidence_source: str,
    confidence: str,
) -> dict[str, Any]:
    return {
        "claim_id": f"{paper_id}-{suffix}",
        "paper_id": paper_id,
        "claim_text_draft": text,
        "support_type": support_type,
        "evidence_source": evidence_source,
        "confidence": confidence,
        "needs_human_review": True,
        "human_verified": False,
    }


def draft_figure_notes(paper: dict[str, Any]) -> list[dict[str, Any]]:
    paper_id = str(paper["candidate_id"])
    if paper_id == "F3I":
        note_text = "Potential review use is likely a background concept or summary scheme, but no source figure or caption was extracted."
    elif paper_id == "F47A":
        note_text = "Potential review use is a reaction scheme or optimization figure related to Pd/asymmetric axially chiral allene synthesis; exact figure label is unknown."
    elif paper_id == "P403":
        note_text = "Potential review use is a reaction scheme for Pd-catalyzed allenylation of secondary phosphine oxides; exact figure/scheme label is unknown."
    else:
        note_text = "Potential figure use requires manual extraction."
    return [
        {
            "figure_note_id": f"{paper_id}-FN1",
            "paper_id": paper_id,
            "figure_or_scheme_label": "unknown",
            "note_draft": note_text,
            "source": "needs_manual_extraction",
            "should_use_in_review": "yes_after_human_review" if paper_id in {"F47A", "P403"} else "maybe",
            "needs_human_review": True,
            "human_verified": False,
        }
    ]


def write_dataset_outputs(dataset_root: Path, report: dict[str, Any]) -> None:
    expected = dataset_root / "expected"
    inputs = dataset_root / "inputs"
    write_json(expected / "expected_claims.draft.json", {"claims": report["claims"], "trusted_for_scientific_quality": False})
    write_json(expected / "expected_figures.draft.json", {"figure_notes": report["figure_notes"], "trusted_for_scientific_quality": False})
    for paper in report["papers"]:
        paper_id = paper["paper_id"]
        excerpt = build_excerpt_note(paper_id, paper["claims"])
        figure_note = build_figure_note_markdown(paper_id, paper["figure_notes"])
        (inputs / "verified_excerpts").mkdir(parents=True, exist_ok=True)
        (inputs / "figure_notes").mkdir(parents=True, exist_ok=True)
        (inputs / "verified_excerpts" / f"{paper_id}.excerpt_note.md").write_text(excerpt, encoding="utf-8")
        (inputs / "figure_notes" / f"{paper_id}.figure_notes.md").write_text(figure_note, encoding="utf-8")
    selected_path = inputs / "selected_papers.verified_draft.json"
    selected = load_json(selected_path)
    claims_by_id = group_by(report["claims"], "paper_id")
    figures_by_id = group_by(report["figure_notes"], "paper_id")
    for row in selected.get("papers") or []:
        paper_id = row.get("candidate_id")
        row["key_claims_draft"] = claims_by_id.get(paper_id, [])
        row["figure_notes_draft"] = figures_by_id.get(paper_id, [])
        row["claims_figures_extraction_status"] = "draft_needs_human_review"
        row["human_verified"] = False
        row["needs_human_review"] = True
    selected["claims_figures_summary"] = {
        "claim_count": report["summary"]["claim_count"],
        "figure_note_count": report["summary"]["figure_note_count"],
        "needs_manual_extraction_count": report["summary"]["needs_manual_extraction_count"],
    }
    selected["trusted_for_scientific_quality"] = False
    write_json(selected_path, selected)


def build_excerpt_note(paper_id: str, claims: list[dict[str, Any]]) -> str:
    lines = [
        f"# {paper_id} Verified Draft Excerpt Note",
        "",
        "No long PDF body text is stored in this fixture.",
        "",
        "Draft claim cues:",
    ]
    for item in claims:
        lines.append(f"- {item['claim_id']}: {item['claim_text_draft']}")
    lines.extend(["", "All claim cues need human review before scientific use."])
    text = "\n".join(lines) + "\n"
    return text[:MAX_EXCERPT_CHARS_PER_PAPER]


def build_figure_note_markdown(paper_id: str, notes: list[dict[str, Any]]) -> str:
    lines = [
        f"# {paper_id} Figure Notes",
        "",
        "- figure_extraction_status: needs_manual_extraction",
        "- copied_source_images: false",
        "- needs_human_review: true",
        "",
        "Draft notes:",
    ]
    for item in notes:
        lines.append(f"- {item['figure_note_id']}: {item['figure_or_scheme_label']} - {item['note_draft']}")
    return "\n".join(lines) + "\n"


def group_by(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get(key)), []).append(row)
    return grouped


def load_json(path: Path) -> Any:
    if not path.exists():
        raise ExtractionError(f"required file not found: {path}")
    text = path.read_text(encoding="utf-8")
    if any(pattern.search(text) for pattern in SECRET_PATTERNS):
        raise ExtractionError(f"secret-like pattern found in {path}")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ExtractionError(f"invalid JSON: {path} ({exc})") from exc


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Clean 3-Paper Claims and Figure Notes Draft",
        "",
        f"Status: `{report['status']}`",
        f"Claims: {report['summary']['claim_count']}",
        f"Figure notes: {report['summary']['figure_note_count']}",
        f"Needs manual extraction markers: {report['summary']['needs_manual_extraction_count']}",
        "",
        "| paper | claims | figure notes |",
        "| --- | ---: | ---: |",
    ]
    for paper in report["papers"]:
        lines.append(f"| {paper['paper_id']} | {len(paper['claims'])} | {len(paper['figure_notes'])} |")
    lines.extend(
        [
            "",
            "No long PDF body text, raw image, API call, upload, or knowledge-base creation was used.",
            "All claims and figure notes remain draft items requiring human review.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
