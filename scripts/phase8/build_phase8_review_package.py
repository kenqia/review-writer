#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz
import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.phase8.schemas import AI_STATUSES, CLAIM_SUPPORT_STATUSES, EVIDENCE_DIRECTNESS, MECHANISM_CLASSES

PAPERS = {
    "F3I": {
        "source_document_id": "F3I_MAIN",
        "title": "Allenes in Catalytic Asymmetric Synthesis and Natural Product Syntheses",
        "doi_seed_path": "demo_projects/clean_3paper_allene_review/inputs/verified_metadata/F3I.metadata.verified_draft.json",
        "filename_contains": ["3i-", "Allenes in Catalytic Asymmetric Synthesis"],
        "role": "review_background",
    },
    "F47A": {
        "source_document_id": "F47A_MAIN",
        "title": "Palladium-Catalyzed Asymmetric Synthesis of Axially Chiral Allenes",
        "doi_seed_path": "demo_projects/clean_3paper_allene_review/inputs/verified_metadata/F47A.metadata.verified_draft.json",
        "filename_contains": ["47a-", "dibenzalacetone"],
        "role": "representative_method",
    },
    "P403": {
        "source_document_id": "P403_MAIN",
        "title": "Pd-Catalyzed Asymmetric Allenylation of Secondary Phosphine Oxides",
        "doi_seed_path": "demo_projects/clean_3paper_allene_review/inputs/verified_metadata/P403.metadata.verified_draft.json",
        "filename_contains": ["pd-catalyzed-asymmetric-allenylation", "secondary-phosphine"],
        "role": "recent_method",
    },
}

FIELDS = [
    "bibliography",
    "research objective",
    "reaction class",
    "substrates/products",
    "catalyst",
    "ligand",
    "loading",
    "reagents/additives",
    "solvent",
    "temperature",
    "time",
    "atmosphere",
    "yield",
    "ee",
    "er",
    "dr",
    "conversion",
    "selectivity",
    "scope",
    "failed substrates",
    "limitations",
    "author conclusions",
    "mechanism claims",
    "figures/schemes/tables",
]

NUMERIC_FIELDS = {"yield", "ee", "er", "dr", "conversion", "selectivity", "temperature", "time", "loading"}
MECHANISM_FIELDS = {"mechanism claims"}
FIGURE_FIELDS = {"figures/schemes/tables"}


@dataclass(frozen=True)
class SourceDoc:
    paper_id: str
    source_document_id: str
    path: Path | None
    sha256: str | None
    file_size: int | None
    page_count: int | None
    text_pages: list[dict[str, Any]]


def main() -> int:
    args = parse_args()
    build(args)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Phase 8A human-review evidence package.")
    parser.add_argument("--paper-root", type=Path, action="append", default=[])
    parser.add_argument("--output-root", type=Path, default=Path("local/phase8_evidence"))
    parser.add_argument("--public-report-json", type=Path, default=Path("docs/phase8/phase8a_status_report.json"))
    parser.add_argument("--public-report-md", type=Path, default=Path("docs/phase8/phase8a_status_report.md"))
    parser.add_argument("--phase7-section", type=Path, default=Path("/tmp/review_writer_phase7_full_e2e_r2_attempt1/generated_section.md"))
    parser.add_argument("--allow-network-metadata", action="store_true")
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def build(args: argparse.Namespace) -> dict[str, Any]:
    roots = args.paper_root or [Path("chem_papers")]
    make_dirs(args.output_root)
    sources = [build_source_doc(args, paper_id, roots) for paper_id in PAPERS]
    source_records = [write_source_outputs(args.output_root, source) for source in sources]
    source_records.extend(build_missing_si_records(source.paper_id) for source in sources)
    phase7_claims = split_phase7_claims(args.phase7_section)
    extraction_records = build_extraction_records(sources)
    evidence_records = build_evidence_records(extraction_records, sources)
    review_units = build_review_units(extraction_records, phase7_claims)
    biblio_records, update_records, network_calls = build_bibliography_records(args.allow_network_metadata, sources)
    write_json(args.output_root / "inventories/source_inventory.local.json", source_records)
    write_json(args.output_root / "inventories/bibliography_candidates.local.json", biblio_records)
    write_json(args.output_root / "reports/update_queries.local.json", update_records)
    write_jsonl(args.output_root / "ai_extraction/ai_extraction.jsonl", extraction_records)
    write_jsonl(args.output_root / "ai_extraction/evidence_records.jsonl", evidence_records)
    write_jsonl(args.output_root / "review_queue/core_review_queue.jsonl", review_units[:90])
    write_jsonl(args.output_root / "review_queue/extended_review_queue.jsonl", review_units)
    write_json(args.output_root / "review_queue/core_review_queue.json", {"items": review_units[:90]})
    write_json(args.output_root / "review_queue/extended_review_queue.json", {"items": review_units})
    write_json(args.output_root / "review_queue/phase7_claims.json", {"claims": phase7_claims})
    write_csv(args.output_root / "review_queue/core_review_queue.csv", review_units[:90])
    write_csv(args.output_root / "review_queue/extended_review_queue.csv", review_units)
    write_manual_download(args.output_root, source_records)
    report = build_public_report(source_records, biblio_records, update_records, extraction_records, review_units, phase7_claims, network_calls)
    args.public_report_json.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.public_report_json, report)
    args.public_report_md.write_text(render_report(report), encoding="utf-8")
    return report


def make_dirs(root: Path) -> None:
    for rel in [
        "sources/F3I",
        "sources/F47A",
        "sources/P403",
        "extracted",
        "figures",
        "inventories",
        "ai_extraction",
        "review_queue",
        "review_decisions",
        "reports",
        "cache",
    ]:
        (root / rel).mkdir(parents=True, exist_ok=True)


def build_source_doc(args: argparse.Namespace, paper_id: str, roots: list[Path]) -> SourceDoc:
    meta = PAPERS[paper_id]
    source_id = meta["source_document_id"]
    found = find_pdf(meta["filename_contains"], roots)
    copied = None
    if found:
        copied = args.output_root / "sources" / paper_id / f"{source_id}.pdf"
        if found.resolve() != copied.resolve():
            shutil.copy2(found, copied)
    pages = extract_pages(copied) if copied else []
    return SourceDoc(
        paper_id=paper_id,
        source_document_id=source_id,
        path=copied,
        sha256=sha256_file(copied) if copied else None,
        file_size=copied.stat().st_size if copied else None,
        page_count=len(pages) if pages else None,
        text_pages=pages,
    )


def find_pdf(markers: list[str], roots: list[Path]) -> Path | None:
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.pdf"):
            lower = path.name.lower()
            if any(marker.lower() in lower for marker in markers):
                return path
    return None


def extract_pages(path: Path) -> list[dict[str, Any]]:
    doc = fitz.open(path)
    pages = []
    for idx, page in enumerate(doc):
        text = page.get_text("text") or ""
        pages.append(
            {
                "pdf_page_index": idx,
                "printed_page_label": str(idx + 1),
                "section_heading": guess_heading(text),
                "text": text,
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            }
        )
    return pages


def write_source_outputs(root: Path, source: SourceDoc) -> dict[str, Any]:
    extracted = root / "extracted" / source.source_document_id
    extracted.mkdir(parents=True, exist_ok=True)
    write_jsonl(extracted / "page_text.jsonl", source.text_pages)
    section_map = [
        {
            "pdf_page_index": page["pdf_page_index"],
            "printed_page_label": page["printed_page_label"],
            "section_heading": page["section_heading"],
        }
        for page in source.text_pages
    ]
    write_json(extracted / "section_map.json", {"pages": section_map})
    figures = detect_labels(source, r"\b(Figure|Fig\.|Scheme|Table)\s+\d+\b")
    write_json(extracted / "table_inventory.json", {"items": [item for item in figures if item["label"].lower().startswith("table")]})
    write_json(extracted / "figure_inventory.json", {"items": [item for item in figures if not item["label"].lower().startswith("table")]})
    write_json(
        extracted / "extraction_warnings.json",
        {
            "extraction_method": "PyMuPDF text extraction",
            "extraction_version": fitz.VersionBind,
            "source_hash": source.sha256,
            "confidence": "medium" if source.path else "missing_source",
            "warnings": [] if source.path else ["main PDF not found"],
        },
    )
    return {
        "source_document_id": source.source_document_id,
        "paper_id": source.paper_id,
        "source_role": "MAIN",
        "sha256": source.sha256,
        "file_size": source.file_size,
        "page_count": source.page_count,
        "mime_type": "application/pdf" if source.path else None,
        "title_candidate": PAPERS[source.paper_id]["title"],
        "doi_candidate": doi_from_seed(source.paper_id),
        "publisher_candidate": None,
        "acquisition_source_type": "local_recursive_search" if source.path else "missing",
        "acquisition_date": today(),
        "correction_query_date": today(),
        "retraction_query_date": today(),
        "needs_human_review": True,
        "status": "SOURCE_FOUND" if source.path else "MISSING_SOURCE",
    }


def build_bibliography_records(allow_network: bool, sources: list[SourceDoc]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    records = []
    updates = []
    network_calls = 0
    for source in sources:
        doi_seed = doi_from_seed(source.paper_id)
        pdf_text = "\n".join(page["text"][:2000] for page in source.text_pages[:2])
        doi_pdf = find_doi(pdf_text)
        crossref = {}
        checked_sources = ["local_pdf_text", "repo_registry"]
        if allow_network:
            crossref, calls = query_crossref(doi_seed if doi_seed != "unknown" else PAPERS[source.paper_id]["title"])
            network_calls += calls
            checked_sources.append("crossref")
        doi_crossref = crossref.get("doi")
        doi_values = {v.lower() for v in [doi_pdf, doi_seed, doi_crossref] if v and v != "unknown"}
        status = "BIBLIOGRAPHY_CANDIDATE_CONFIRMED" if len(doi_values) == 1 and len([v for v in [doi_pdf, doi_seed, doi_crossref] if v and v != "unknown"]) >= 2 else "BIBLIOGRAPHY_UNCONFIRMED"
        if len(doi_values) > 1:
            status = "BIBLIOGRAPHY_CONFLICT"
        records.append(
            {
                "paper_id": source.paper_id,
                "title_as_reported": PAPERS[source.paper_id]["title"],
                "authors_as_reported": authors_from_seed(source.paper_id),
                "doi_from_pdf": doi_pdf or "unknown",
                "doi_from_registry": doi_seed,
                "doi_from_publisher": crossref.get("publisher_doi", "not_checked" if not allow_network else "unknown"),
                "doi_from_crossref": doi_crossref or ("not_checked" if not allow_network else "unknown"),
                "status": status,
                "needs_human_review": True,
            }
        )
        updates.append(
            {
                "paper_id": source.paper_id,
                "checked_sources": checked_sources,
                "checked_at": today(),
                "query_result": crossref.get("update_status", "NO_UPDATE_FOUND_IN_CHECKED_SOURCES" if allow_network else "NOT_CHECKED_OFFLINE_GATE"),
                "correction_candidates": crossref.get("correction_candidates", []),
                "retraction_candidates": crossref.get("retraction_candidates", []),
            }
        )
    return records, updates, network_calls


def build_extraction_records(sources: list[SourceDoc]) -> list[dict[str, Any]]:
    records = []
    for source in sources:
        snippets = snippets_for_source(source)
        for idx, field in enumerate(FIELDS, start=1):
            locator = snippets[idx % len(snippets)] if snippets else empty_locator(source)
            status = "AI_EXTRACTED" if source.path else "MISSING_SOURCE"
            if field in NUMERIC_FIELDS | MECHANISM_FIELDS | FIGURE_FIELDS:
                status = "HUMAN_REVIEW_REQUIRED"
            record = {
                "record_id": f"{source.paper_id}-FIELD-{idx:02d}",
                "paper_id": source.paper_id,
                "source_document_id": source.source_document_id,
                "field_name": field,
                "status": status,
                "value_as_reported": candidate_value(source.paper_id, field),
                "normalized_value_candidate": candidate_value(source.paper_id, field),
                "unit_as_reported": unit_for(field),
                "normalized_unit_candidate": unit_for(field),
                "normalization_rule": "no silent normalization; candidate mirrors reported value",
                "normalization_requires_human_review": True,
                "chemical_entity": {
                    "name_as_reported": "HUMAN_REVIEW_REQUIRED",
                    "normalized_name_candidate": "HUMAN_REVIEW_REQUIRED",
                    "structure_available": False,
                    "structure_source": "not_inferred_from_image",
                    "normalization_status": "HUMAN_REVIEW_REQUIRED",
                },
                "mechanism_classification": mechanism_class(field),
                "source_locator": locator,
                "short_quote": locator["short_quote"],
                "ai_rationale_hidden_by_default": True,
                "needs_human_review": True,
            }
            assert record["status"] in AI_STATUSES
            assert record["mechanism_classification"] in MECHANISM_CLASSES
            records.append(with_hash(record))
    return records


def build_evidence_records(extraction_records: list[dict[str, Any]], sources: list[SourceDoc]) -> list[dict[str, Any]]:
    source_hash = {source.source_document_id: source.sha256 for source in sources}
    records = []
    for record in extraction_records:
        locator = record["source_locator"]
        directness = "DIRECT_NUMERIC" if record["field_name"] in NUMERIC_FIELDS else "DIRECT_TEXTUAL"
        if record["field_name"] in FIGURE_FIELDS:
            directness = "FIGURE_SUPPORTED"
        if record["field_name"] in MECHANISM_FIELDS:
            directness = "AUTHOR_INTERPRETATION"
        evidence = {
            "evidence_id": f"EVID-{record['record_id']}",
            "paper_id": record["paper_id"],
            "source_document_id": record["source_document_id"],
            "source_hash": source_hash.get(record["source_document_id"]),
            "pdf_page_index": locator["pdf_page_index"],
            "printed_page_label": locator["printed_page_label"],
            "section_heading": locator["section_heading"],
            "figure_id": locator.get("figure_id"),
            "table_id": locator.get("table_id"),
            "scheme_id": locator.get("scheme_id"),
            "entry_id": locator.get("entry_id"),
            "compound_label": locator.get("compound_label"),
            "short_quote": locator["short_quote"],
            "extended_excerpt_pointer": f"local/phase8_evidence/extracted/{record['source_document_id']}/page_text.jsonl",
            "evidence_directness": directness,
            "extraction_confidence": "candidate",
            "conflict_status": "HUMAN_REVIEW_REQUIRED",
        }
        assert evidence["evidence_directness"] in EVIDENCE_DIRECTNESS
        records.append(evidence)
    return records


def build_review_units(extraction_records: list[dict[str, Any]], phase7_claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    units = []
    priority_fields = set(FIELDS)
    for record in extraction_records:
        tier = "core" if record["field_name"] in priority_fields else "extended"
        units.append(
            {
                "review_item_id": f"RU-{record['record_id']}",
                "tier": tier,
                "paper_id": record["paper_id"],
                "field_name": record["field_name"],
                "candidate_value": record["value_as_reported"],
                "source_locator": record["source_locator"],
                "short_evidence": record["short_quote"],
                "blinded_first": True,
                "initially_hidden": ["ai_confidence", "ai_rationale", "qwen_output"],
                "allowed_actions": ["accept", "reject", "edit", "cannot_verify", "defer", "add_note"],
                "ai_record_hash": record["record_hash"],
                "status": "HUMAN_REVIEW_REQUIRED",
            }
        )
    for claim in phase7_claims:
        units.append(
            {
                "review_item_id": f"RU-{claim['claim_id']}",
                "tier": "core",
                "paper_id": ",".join(claim["citation_ids"]) or "PHASE7",
                "field_name": "phase7_claim",
                "candidate_value": claim["claim_text"],
                "source_locator": {"source_document_id": "PHASE7_GENERATED_SECTION", "pdf_page_index": None, "printed_page_label": None, "section_heading": "Phase 7 generated section"},
                "short_evidence": trim_quote(claim["claim_text"]),
                "blinded_first": True,
                "initially_hidden": ["ai_confidence", "ai_rationale", "qwen_output"],
                "allowed_actions": ["accept", "reject", "edit", "cannot_verify", "defer", "add_note"],
                "ai_record_hash": claim["claim_hash"],
                "status": "HUMAN_REVIEW_REQUIRED",
                "risk_tier": claim["risk_tier"],
            }
        )
    core = [unit for unit in units if unit["tier"] == "core"]
    extended = [unit for unit in units if unit["tier"] != "core"]
    return core + extended


def split_phase7_claims(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return [
            {
                "claim_id": "PHASE7-MISSING",
                "sentence_id": "PHASE7-S0",
                "claim_text": "Phase 7 generated section artifact was not found.",
                "claim_type": "missing_source",
                "citation_ids": [],
                "numeric_tokens": [],
                "mechanism_terms": [],
                "figure_reference": None,
                "candidate_evidence_ids": [],
                "support_status": "MISSING_SOURCE",
                "risk_tier": "tier1",
                "claim_hash": hashlib.sha256(b"PHASE7-MISSING").hexdigest(),
            }
        ]
    text = path.read_text(encoding="utf-8")
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", re.sub(r"^#+.*$", "", text, flags=re.MULTILINE)) if s.strip()]
    claims = []
    for idx, sentence in enumerate(sentences, start=1):
        citations = re.findall(r"\[([A-Z0-9]+)\]", sentence)
        numeric = re.findall(r"\b\d+(?:\.\d+)?\s*%?\b", sentence)
        mechanism = [term for term in ["mechanistic", "mechanism", "pathway", "stereocontrol"] if term in sentence.lower()]
        risk = "tier1" if numeric or mechanism or "NEEDS_EVIDENCE" in sentence else "tier2"
        support = "HUMAN_REVIEW_REQUIRED"
        claim = {
            "claim_id": f"PHASE7-C{idx:02d}",
            "sentence_id": f"PHASE7-S{idx:02d}",
            "claim_text": sentence,
            "claim_type": "generated_section_fact_candidate",
            "citation_ids": citations,
            "numeric_tokens": numeric,
            "mechanism_terms": mechanism,
            "figure_reference": None,
            "candidate_evidence_ids": [f"EVID-{c}" for c in citations],
            "support_status": support,
            "risk_tier": risk,
        }
        assert claim["support_status"] in CLAIM_SUPPORT_STATUSES
        claims.append(with_hash(claim, "claim_hash"))
    return claims


def query_crossref(query: str) -> tuple[dict[str, Any], int]:
    url = "https://api.crossref.org/works"
    try:
        if query.startswith("10."):
            response = requests.get(f"{url}/{query}", timeout=20)
            calls = 1
            item = response.json().get("message", {}) if response.ok else {}
        else:
            response = requests.get(url, params={"query.title": query, "rows": 1}, timeout=20)
            calls = 1
            items = response.json().get("message", {}).get("items", []) if response.ok else []
            item = items[0] if items else {}
        relations = item.get("relation", {}) if isinstance(item, dict) else {}
        correction = [str(v) for values in relations.values() for v in (values if isinstance(values, list) else []) if "correct" in str(v).lower()]
        retraction = [str(v) for values in relations.values() for v in (values if isinstance(values, list) else []) if "retract" in str(v).lower()]
        return {
            "doi": item.get("DOI"),
            "publisher_doi": item.get("DOI"),
            "update_status": "UPDATE_FOUND" if correction or retraction else "NO_UPDATE_FOUND_IN_CHECKED_SOURCES",
            "correction_candidates": correction[:5],
            "retraction_candidates": retraction[:5],
        }, calls
    except Exception as exc:  # noqa: BLE001
        return {"update_status": "QUERY_FAILED", "error_type": type(exc).__name__}, 1


def snippets_for_source(source: SourceDoc) -> list[dict[str, Any]]:
    snippets = []
    for page in source.text_pages:
        text = compact(page["text"])
        if not text:
            continue
        snippets.append(
            {
                "source_document_id": source.source_document_id,
                "pdf_page_index": page["pdf_page_index"],
                "printed_page_label": page["printed_page_label"],
                "section_heading": page["section_heading"],
                "figure_id": first_label(text, "Fig"),
                "scheme_id": first_label(text, "Scheme"),
                "table_id": first_label(text, "Table"),
                "entry_id": None,
                "compound_label": first_compound_label(text),
                "short_quote": trim_quote(text),
            }
        )
    return snippets[:12] or [empty_locator(source)]


def empty_locator(source: SourceDoc) -> dict[str, Any]:
    return {
        "source_document_id": source.source_document_id,
        "pdf_page_index": None,
        "printed_page_label": None,
        "section_heading": "MISSING_SOURCE",
        "figure_id": None,
        "scheme_id": None,
        "table_id": None,
        "entry_id": None,
        "compound_label": None,
        "short_quote": "Source missing; human download required.",
    }


def detect_labels(source: SourceDoc, pattern: str) -> list[dict[str, Any]]:
    items = []
    seen = set()
    for page in source.text_pages:
        for match in re.finditer(pattern, page["text"]):
            label = match.group(0)
            key = (label, page["pdf_page_index"])
            if key in seen:
                continue
            seen.add(key)
            items.append(
                {
                    "label": label,
                    "pdf_page_index": page["pdf_page_index"],
                    "printed_page_label": page["printed_page_label"],
                    "section_heading": page["section_heading"],
                }
            )
    return items


def build_public_report(source_records: list[dict[str, Any]], biblio: list[dict[str, Any]], updates: list[dict[str, Any]], extraction: list[dict[str, Any]], queue: list[dict[str, Any]], phase7: list[dict[str, Any]], network_calls: int) -> dict[str, Any]:
    field_counts: dict[str, int] = {}
    for record in extraction:
        field_counts[record["paper_id"]] = field_counts.get(record["paper_id"], 0) + 1
    core_count = sum(1 for unit in queue if unit["tier"] == "core")
    verified_count = sum(1 for record in extraction + queue + phase7 if str(record).find("VERIFIED") >= 0)
    missing_sources = sum(1 for source in source_records if source["status"] != "SOURCE_FOUND")
    biblio_conflicts = sum(1 for row in biblio if row["status"] == "BIBLIOGRAPHY_CONFLICT")
    return {
        "status": "HUMAN_REVIEW_REQUIRED",
        "methodology": "AI-assisted pre-extraction followed by single-human verification. It is not independent dual-human data extraction.",
        "source_inventory": source_records,
        "main_pdf_status": {row["paper_id"]: row["status"] for row in source_records if row["source_role"] == "MAIN"},
        "si_status": {row["paper_id"]: row["status"] for row in source_records if row["source_role"] == "SI"},
        "bibliography_status_counts": count_by(biblio, "status"),
        "bibliography_conflict_count": biblio_conflicts,
        "update_query_summary": count_by(updates, "query_result"),
        "field_counts_by_paper": field_counts,
        "numeric_candidate_count": sum(1 for r in extraction if r["field_name"] in NUMERIC_FIELDS),
        "mechanism_candidate_count": sum(1 for r in extraction if r["field_name"] in MECHANISM_FIELDS),
        "figure_candidate_count": sum(1 for r in extraction if r["field_name"] in FIGURE_FIELDS),
        "phase7_claim_count": len(phase7),
        "phase7_risk_distribution": count_by(phase7, "risk_tier"),
        "core_review_queue_size": core_count,
        "extended_review_queue_size": len(queue),
        "conflict_or_missing_source_count": missing_sources + biblio_conflicts,
        "qwen_calls": 0,
        "mineru_calls": 0,
        "network_calls": network_calls,
        "dashboard_command": "make phase8-dashboard-check && conda run -n review-writer-phase8 python scripts/review/serve_phase8_evidence_review.py --root local/phase8_evidence --host 127.0.0.1 --port 8787",
        "local_package_path": "local/phase8_evidence",
        "estimated_human_review_hours": "2-4",
        "verified_status_present": verified_count > 0,
        "human_download_required": missing_sources > 0,
        "checkpoint": "HUMAN_REVIEW_REQUIRED",
        "phase8b_started": False,
    }


def render_report(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Phase 8A Human Review Package Status",
            "",
            f"- status: `{report['status']}`",
            f"- methodology: {report['methodology']}",
            f"- source documents: `{len(report['source_inventory'])}`",
            f"- bibliography status counts: `{report['bibliography_status_counts']}`",
            f"- update query summary: `{report['update_query_summary']}`",
            f"- numeric candidates: `{report['numeric_candidate_count']}`",
            f"- mechanism candidates: `{report['mechanism_candidate_count']}`",
            f"- figure candidates: `{report['figure_candidate_count']}`",
            f"- Phase 7 claims: `{report['phase7_claim_count']}`",
            f"- core queue size: `{report['core_review_queue_size']}`",
            f"- extended queue size: `{report['extended_review_queue_size']}`",
            f"- Qwen calls: `{report['qwen_calls']}`",
            f"- MinerU calls: `{report['mineru_calls']}`",
            f"- network calls: `{report['network_calls']}`",
            f"- VERIFIED status present: `{report['verified_status_present']}`",
            f"- local package path: `{report['local_package_path']}`",
            f"- dashboard command: `{report['dashboard_command']}`",
            "",
            "Current checkpoint: HUMAN_REVIEW_REQUIRED.",
            "Phase 8B has not started.",
            "",
        ]
    )


def write_manual_download(root: Path, source_records: list[dict[str, Any]]) -> None:
    lines = ["# Manual Download Required", ""]
    missing_any = False
    for record in source_records:
        if record.get("source_role") != "SI" or record.get("status") == "SOURCE_FOUND":
            continue
        si_id = record["source_document_id"]
        missing_any = True
        lines.extend(
            [
                f"## {record['paper_id']}",
                "",
                f"- confirmed DOI candidate: `{record.get('doi_candidate')}`",
                f"- file type: `SI`",
                "- status: `MISSING_SOURCE_REQUIRES_HUMAN_DOWNLOAD`",
                "- official source description: publisher supplementary information or DOI landing page",
                f"- suggested local save path: `local/phase8_evidence/sources/{record['paper_id']}/{si_id}.pdf`",
                "",
            ]
        )
    if not missing_any:
        lines.append("No manual downloads are currently required.\n")
    (root / "reports/manual_download_required.md").write_text("\n".join(lines), encoding="utf-8")


def build_missing_si_records(paper_id: str) -> dict[str, Any]:
    return {
        "source_document_id": f"{paper_id}_SI",
        "paper_id": paper_id,
        "source_role": "SI",
        "sha256": None,
        "file_size": None,
        "page_count": None,
        "mime_type": None,
        "title_candidate": PAPERS[paper_id]["title"],
        "doi_candidate": doi_from_seed(paper_id),
        "publisher_candidate": None,
        "acquisition_source_type": "not_found_local_or_offline",
        "acquisition_date": today(),
        "correction_query_date": today(),
        "retraction_query_date": today(),
        "needs_human_review": True,
        "status": "MISSING_SOURCE_REQUIRES_HUMAN_DOWNLOAD",
    }


def candidate_value(paper_id: str, field: str) -> str:
    if field == "bibliography":
        return PAPERS[paper_id]["title"]
    if field in NUMERIC_FIELDS or field in MECHANISM_FIELDS or field in FIGURE_FIELDS:
        return "HUMAN_REVIEW_REQUIRED"
    return f"{field} candidate for {paper_id}; requires human source check"


def mechanism_class(field: str) -> str:
    if field in MECHANISM_FIELDS:
        return "AUTHOR_PROPOSED"
    return "REVIEWER_INFERENCE_CANDIDATE"


def unit_for(field: str) -> str | None:
    if field in {"yield", "ee", "conversion", "selectivity", "loading"}:
        return "%"
    if field == "temperature":
        return "deg C"
    if field == "time":
        return "h"
    return None


def doi_from_seed(paper_id: str) -> str:
    path = REPO_ROOT / PAPERS[paper_id]["doi_seed_path"]
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("doi_draft") or data.get("doi") or "unknown"


def authors_from_seed(paper_id: str) -> list[str]:
    path = REPO_ROOT / PAPERS[paper_id]["doi_seed_path"]
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("authors_draft") or data.get("authors") or []


def find_doi(text: str) -> str | None:
    match = re.search(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", text)
    return match.group(0).rstrip(".,);") if match else None


def first_label(text: str, prefix: str) -> str | None:
    match = re.search(rf"\b{prefix}(?:ure|\.|)\s+\d+\b", text, flags=re.IGNORECASE)
    return match.group(0) if match else None


def first_compound_label(text: str) -> str | None:
    match = re.search(r"\b\d+[a-z]\b", text)
    return match.group(0) if match else None


def guess_heading(text: str) -> str:
    for line in text.splitlines():
        clean = line.strip()
        if 4 <= len(clean) <= 90 and not re.match(r"^\d+$", clean):
            return clean
    return "unknown"


def trim_quote(text: str) -> str:
    words = compact(text).split()
    return " ".join(words[:25])


def compact(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def with_hash(record: dict[str, Any], key: str = "record_hash") -> dict[str, Any]:
    payload = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    record[key] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return record


def count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key))
        counts[value] = counts.get(value, 0) + 1
    return counts


def today() -> str:
    return time.strftime("%Y-%m-%d")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["review_item_id", "tier", "paper_id", "field_name", "candidate_value", "short_evidence", "status"])
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in writer.fieldnames})


if __name__ == "__main__":
    raise SystemExit(main())
