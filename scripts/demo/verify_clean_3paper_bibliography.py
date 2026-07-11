#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review_writer.metadata_sources.base import MetadataQuery, MetadataSourceResult
from review_writer.metadata_sources.crossref import CrossrefSource
from review_writer.metadata_sources.openalex import OpenAlexSource
from review_writer.metadata_sources.semantic_scholar import SemanticScholarSource

EXPECTED_TOP3 = ["F3I", "F47A", "P403"]
METADATA_CONFIDENCE = {"low", "medium", "high"}
DOI_RE = re.compile(r"^10\.\S+/\S+$", re.I)


class BibliographyError(Exception):
    pass


def main() -> int:
    args = parse_args()
    try:
        report = verify_bibliography(args.dataset_root, args.paper_root, allow_network=args.allow_network_metadata)
    except BibliographyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.output_json:
        write_json(args.output_json, report)
    if args.output_md:
        write_markdown(args.output_md, report)
    write_dataset_outputs(args.dataset_root, report)
    print(
        "clean-3paper-bibliography-verification: "
        f"{report['status']} network={'used' if args.allow_network_metadata else 'not_used'} "
        f"insufficient={report['summary']['insufficient_metadata_count']}"
    )
    return 1 if args.strict and report["errors"] else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify clean 3-paper bibliographic metadata with optional public metadata lookup.")
    parser.add_argument("--dataset-root", type=Path, default=Path("demo_projects/clean_3paper_allene_review"))
    parser.add_argument("--paper-root", type=Path, default=Path("chem_papers"))
    parser.add_argument("--allow-network-metadata", action="store_true")
    parser.add_argument("--output-json", type=Path, default=Path("/tmp/clean_3paper_bibliography_verification.json"))
    parser.add_argument("--output-md", type=Path, default=Path("/tmp/clean_3paper_bibliography_verification.md"))
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def verify_bibliography(dataset_root: Path, paper_root: Path, *, allow_network: bool) -> dict[str, Any]:
    inputs = dataset_root / "inputs"
    approval = load_json(inputs / "candidate_approval_pack.json")
    selected = load_json(inputs / "selected_papers.verified_draft.json")
    rows = approval.get("recommended_top3") or []
    if [row.get("candidate_id") for row in rows] != EXPECTED_TOP3:
        raise BibliographyError("approval pack top3 does not match expected F3I/F47A/P403 order")
    errors: list[str] = []
    warnings: list[str] = []
    papers = [verify_one(row, selected, inputs, paper_root, allow_network, errors, warnings) for row in rows]
    insufficient_count = sum(1 for row in papers if row["verification_status"] == "insufficient_metadata")
    conflict_count = sum(1 for row in papers if row["conflicts"])
    status = "fail" if errors else "warn" if warnings or insufficient_count else "pass"
    phase5k_ready = insufficient_count == 0
    return {
        "status": status,
        "summary": {
            "top3": EXPECTED_TOP3,
            "allow_network_metadata": allow_network,
            "network_metadata": "used" if allow_network else "not_used",
            "insufficient_metadata_count": insufficient_count,
            "conflict_count": conflict_count,
            "phase5k_ready": phase5k_ready,
            "phase5k_gate_reason": "ready_for_human_review" if phase5k_ready else "metadata_insufficient_needs_user_decision",
        },
        "papers": papers,
        "errors": errors,
        "warnings": warnings,
        "safety": {
            "network": "used_for_public_metadata_only" if allow_network else "not_used",
            "pdf_body_read": "not_used",
            "pdf_upload": "not_used",
            "qwen": "not_used",
            "mineru_api": "not_used",
            "bailian": "not_used",
            "knowledge_base": "not_created",
            "image_api": "not_used",
        },
    }


def verify_one(
    approval_row: dict[str, Any],
    selected: dict[str, Any],
    inputs: Path,
    paper_root: Path,
    allow_network: bool,
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    candidate_id = str(approval_row.get("candidate_id") or "")
    selected_row = find_selected(selected, candidate_id)
    existing = load_json(inputs / "verified_metadata" / f"{candidate_id}.metadata.verified_draft.json")
    filename = Path(str(approval_row.get("filename") or selected_row.get("filename") or "")).name
    pdf_path = paper_root / filename
    if not pdf_path.exists():
        errors.append(f"{candidate_id}: PDF not found")

    query = best_query(approval_row, selected_row, existing)
    matches = existing_source_matches(existing)
    if allow_network:
        matches = merge_matches(matches, query_public_sources(candidate_id, query, filename))
    elif not matches:
        matches = [
            MetadataSourceResult(
                source_name="local_verified_draft",
                query=query,
                matched_title=str(existing.get("title_draft") or approval_row.get("inferred_title") or ""),
                authors=coerce_authors(existing.get("authors_draft")),
                year=coerce_year(existing.get("year_draft")),
                venue=str(existing.get("journal_draft") or ""),
                doi=normalize_unknown(existing.get("doi_draft")),
                confidence=0.55,
                warnings=["offline seed only; public metadata lookup disabled"],
            ).as_dict()
        ]

    merged = merge_bibliographic_fields(candidate_id, query, matches, approval_row, selected_row, existing)
    if merged["verification_status"] == "insufficient_metadata":
        warnings.append(f"{candidate_id}: insufficient metadata remains")
    return {
        "candidate_id": candidate_id,
        "filename": str(approval_row.get("filename") or selected_row.get("filename") or ""),
        "pdf_exists": pdf_path.exists(),
        "verified_title_draft": merged["title"],
        "authors_draft": merged["authors"],
        "year_draft": merged["year"],
        "journal_draft": merged["journal"],
        "doi_draft": merged["doi"],
        "publication_type_draft": merged["publication_type"],
        "source_matches": matches,
        "metadata_confidence": merged["metadata_confidence"],
        "conflicts": merged["conflicts"],
        "missing_fields": merged["missing_fields"],
        "needs_human_review": True,
        "human_verified": False,
        "verification_status": merged["verification_status"],
        "upload_status": "not_uploaded",
        "api_used": False,
        "trusted_for_scientific_quality": False,
        "notes": [
            "Metadata is a draft based on filename/local draft and optional public bibliographic sources.",
            "No long PDF body text was saved.",
            "Human review remains required before scientific-quality use.",
        ],
    }


def query_public_sources(candidate_id: str, query: str, filename: str) -> list[dict[str, Any]]:
    metadata_query = MetadataQuery(candidate_id=candidate_id, query=query, filename=filename)
    sources = [CrossrefSource(), OpenAlexSource(), SemanticScholarSource()]
    return [source.search(metadata_query, allow_network=True, timeout_seconds=12.0).as_dict() for source in sources]


def best_query(*rows: dict[str, Any]) -> str:
    approval = rows[0] if rows else {}
    value = approval.get("inferred_title")
    if isinstance(value, str) and value and value != "unknown":
        return value
    for row in rows:
        for key in ["verified_title_draft", "title_draft", "inferred_title"]:
            value = row.get(key)
            if isinstance(value, str) and value and value != "unknown":
                return value
    return ""


def merge_bibliographic_fields(
    candidate_id: str,
    query: str,
    matches: list[dict[str, Any]],
    approval_row: dict[str, Any],
    selected_row: dict[str, Any],
    existing: dict[str, Any],
) -> dict[str, Any]:
    viable = [row for row in matches if is_reliable_match(query, row)]
    best = max(viable, key=lambda row: float(row.get("confidence") or 0), default={})
    existing_is_biblio_output = isinstance(existing.get("source_matches"), list)
    existing_title = existing.get("title_draft") if not existing_is_biblio_output else None
    existing_authors = existing.get("authors_draft") if not existing_is_biblio_output else None
    existing_year = existing.get("year_draft") if not existing_is_biblio_output else None
    existing_journal = existing.get("journal_draft") if not existing_is_biblio_output else None
    existing_doi = existing.get("doi_draft") if not existing_is_biblio_output else None
    title = first_non_unknown(best.get("matched_title"), approval_row.get("inferred_title"), existing_title, query)
    authors = best.get("authors") or coerce_authors(existing_authors)
    year = first_non_unknown(best.get("year"), approval_row.get("inferred_year"), existing_year)
    journal = first_non_unknown(best.get("venue"), approval_row.get("inferred_journal"), existing_journal)
    doi = normalize_unknown(first_non_unknown(best.get("doi"), existing_doi))
    conflicts = detect_conflicts(matches)
    if doi != "unknown" and str(doi).lower().endswith(".s001"):
        conflicts.append({"field": "doi", "values": [doi], "reason": "matched DOI appears to identify supporting information"})
        doi = "unknown"
    missing = []
    if not title or title == "unknown":
        missing.append("title")
    if not authors:
        missing.append("authors")
    if not year or year == "unknown":
        missing.append("year")
    if not journal or journal == "unknown":
        missing.append("journal")
    if doi != "unknown" and not DOI_RE.match(str(doi)):
        conflicts.append({"field": "doi", "values": [doi], "reason": "doi_draft does not match DOI pattern"})
        doi = "unknown"
        missing.append("doi")
    elif doi == "unknown":
        missing.append("doi")

    best_confidence = max([float(row.get("confidence") or 0) for row in matches] or [0.0])
    reliable_confidences = [float(row.get("confidence") or 0) for row in matches if is_reliable_match(query, row)]
    best_reliable_confidence = max(reliable_confidences or [0.0])
    if best_reliable_confidence >= 0.72 and len(missing) <= 1 and not conflicts:
        confidence = "high"
    elif best_reliable_confidence >= 0.45 and len(missing) <= 3:
        confidence = "medium"
    else:
        confidence = "low"
    verification_status = "bibliographic_verified_draft" if confidence in {"medium", "high"} and "title" not in missing else "insufficient_metadata"
    publication_type = infer_publication_type(candidate_id, selected_row, approval_row)
    return {
        "title": title or "unknown",
        "authors": authors or [],
        "year": year or "unknown",
        "journal": journal or "unknown",
        "doi": doi,
        "publication_type": publication_type,
        "metadata_confidence": confidence,
        "conflicts": conflicts,
        "missing_fields": sorted(set(missing)),
        "verification_status": verification_status,
    }


def detect_conflicts(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for field in ["year", "doi"]:
        values = sorted({str(row.get(field)).strip() for row in matches if row.get(field) not in (None, "", "unknown")})
        if len(values) > 1:
            conflicts.append({"field": field, "values": values, "reason": "metadata sources disagree"})
    titles = [str(row.get("matched_title") or "") for row in matches if row.get("matched_title")]
    if len(titles) > 1:
        token_sets = [set(re.findall(r"[a-z0-9]+", title.lower())) for title in titles]
        first = token_sets[0]
        if any(len(first & other) / max(1, len(first | other)) < 0.55 for other in token_sets[1:]):
            conflicts.append({"field": "title", "values": titles, "reason": "title similarity below threshold"})
    return conflicts


def is_reliable_match(query: str, row: dict[str, Any]) -> bool:
    title = str(row.get("matched_title") or "")
    if float(row.get("confidence") or 0) < 0.45 or not title:
        return False
    query_tokens = set(re.findall(r"[a-z0-9]+", query.lower()))
    title_tokens = set(re.findall(r"[a-z0-9]+", title.lower()))
    required_groups = [
        {"allene", "allenes", "allenyl", "allenylation"},
        {"phosphine", "phosphines"},
        {"oxide", "oxides"},
    ]
    for group in required_groups:
        if query_tokens & group and not (title_tokens & group):
            return False
    return True


def infer_publication_type(candidate_id: str, selected_row: dict[str, Any], approval_row: dict[str, Any]) -> str:
    role = str(approval_row.get("role") or selected_row.get("role") or "")
    if role == "review_background":
        return "review_or_background"
    return "research_article"


def find_selected(selected: dict[str, Any], candidate_id: str) -> dict[str, Any]:
    for row in selected.get("papers") or []:
        if row.get("candidate_id") == candidate_id:
            return row
    return {}


def existing_source_matches(existing: dict[str, Any]) -> list[dict[str, Any]]:
    rows = existing.get("source_matches")
    if isinstance(rows, list):
        return rows
    return []


def merge_matches(existing: list[dict[str, Any]], fresh: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {str(row.get("source_name")): row for row in existing}
    for row in fresh:
        merged[str(row.get("source_name"))] = row
    return list(merged.values())


def first_non_unknown(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", "unknown", [], {}):
            return value
    return "unknown"


def normalize_unknown(value: Any) -> str:
    if value in (None, "", "unknown"):
        return "unknown"
    return str(value).strip()


def coerce_year(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def coerce_authors(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str) and value not in {"", "unknown"}:
        return [value]
    return []


def write_dataset_outputs(dataset_root: Path, report: dict[str, Any]) -> None:
    inputs = dataset_root / "inputs"
    metadata_dir = inputs / "verified_metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    for paper in report["papers"]:
        path = metadata_dir / f"{paper['candidate_id']}.metadata.verified_draft.json"
        write_json(path, paper)
    summary_json = inputs / "bibliography_verification_summary.json"
    summary_md = inputs / "bibliography_verification_summary.md"
    write_json(summary_json, report)
    write_markdown(summary_md, report)
    selected_path = inputs / "selected_papers.verified_draft.json"
    selected = load_json(selected_path)
    by_id = {paper["candidate_id"]: paper for paper in report["papers"]}
    for row in selected.get("papers") or []:
        paper = by_id.get(row.get("candidate_id"))
        if not paper:
            continue
        row.update(
            {
                "title_draft": paper["verified_title_draft"],
                "authors_draft": paper["authors_draft"] or "unknown",
                "year_draft": paper["year_draft"],
                "journal_draft": paper["journal_draft"],
                "doi_draft": paper["doi_draft"],
                "bibliography_verification_status": paper["verification_status"],
                "metadata_confidence": paper["metadata_confidence"],
                "source_conflicts": paper["conflicts"],
                "missing_fields": paper["missing_fields"],
                "human_verified": False,
                "needs_human_review": True,
            }
        )
    selected["bibliography_verification_summary_path"] = "inputs/bibliography_verification_summary.json"
    selected["phase5k_ready"] = report["summary"]["phase5k_ready"]
    selected["trusted_for_scientific_quality"] = False
    write_json(selected_path, selected)


def load_json(path: Path) -> Any:
    if not path.exists():
        raise BibliographyError(f"required file not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BibliographyError(f"invalid JSON: {path} ({exc})") from exc


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_markdown(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Clean 3-Paper Bibliography Verification",
        "",
        f"Status: `{payload['status']}`",
        f"Network metadata: `{payload['summary']['network_metadata']}`",
        f"Phase 5k ready: `{payload['summary']['phase5k_ready']}`",
        "",
        "| candidate | title draft | year | journal | DOI | confidence | status |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for paper in payload["papers"]:
        lines.append(
            f"| {paper['candidate_id']} | {paper['verified_title_draft']} | {paper['year_draft']} | "
            f"{paper['journal_draft']} | {paper['doi_draft']} | {paper['metadata_confidence']} | "
            f"{paper['verification_status']} |"
        )
    lines.extend(
        [
            "",
            "All rows remain `human_verified=false` and `needs_human_review=true`.",
            "No PDF upload, LLM call, MinerU API call, Bailian call, knowledge-base creation, or image API call was used.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
