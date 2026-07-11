#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ALLOWED = {"F3I", "F47A", "P403"}
PROMPT_LEAKAGE_RE = re.compile(r"\b(system prompt|developer message|workflow|skill instructions|qoderwork)\b", re.I)
UNSUPPORTED_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:%|ee|yield|mol\s*%)\b|doi\s*[:/]|10\.\d{4,9}/", re.I)


def main() -> int:
    args = parse_args()
    report, claim_map = validate(args.section_md, args.evidence_pack_json)
    write_json(args.output_json, report)
    write_json(args.claim_map_json, claim_map)
    write_md(args.output_md, report)
    print(
        "grounded-section-validation: "
        f"{report['status']} coverage={report['claim_evidence_coverage']} "
        f"unsupported={report['unsupported_claim_count']}"
    )
    return 1 if args.strict and report["status"] == "fail" else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a generated section against a safe EvidencePack.")
    parser.add_argument("--section-md", type=Path, required=True)
    parser.add_argument("--evidence-pack-json", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, default=Path("/tmp/grounding_report.json"))
    parser.add_argument("--output-md", type=Path, default=Path("/tmp/grounding_report.md"))
    parser.add_argument("--claim-map-json", type=Path, default=Path("/tmp/claim_evidence_map.json"))
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def validate(section_md: Path, evidence_pack_json: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    section = section_md.read_text(encoding="utf-8")
    pack = json.loads(evidence_pack_json.read_text(encoding="utf-8"))
    evidence_ids = {item["paper_id"] for item in pack.get("items", []) if item.get("paper_id") in ALLOWED}
    evidence_chunk_by_id = {
        item["paper_id"]: item.get("chunk_id")
        for item in pack.get("items", [])
        if item.get("paper_id") in ALLOWED
    }
    paragraphs = claim_paragraphs(section)
    rows = []
    unsupported_citations: list[str] = []
    unsupported_claims = []
    prompt_leakage = []
    needs_evidence_tasks = []
    covered = 0
    for index, paragraph in enumerate(paragraphs, start=1):
        citations = sorted(set(re.findall(r"\[([A-Z0-9]+)\]", paragraph)))
        unsupported = [paper_id for paper_id in citations if paper_id not in evidence_ids]
        unsupported_citations.extend(unsupported)
        has_needs = "[NEEDS_EVIDENCE:" in paragraph or paragraph.strip().upper().startswith("[NEEDS_E")
        if has_needs:
            needs_evidence_tasks.append({"claim_id": f"C{index:03d}", "task": paragraph})
        numeric = bool(UNSUPPORTED_NUMBER_RE.search(paragraph))
        leakage = bool(PROMPT_LEAKAGE_RE.search(paragraph))
        if leakage:
            prompt_leakage.append(f"C{index:03d}")
        factual = not has_needs
        mapped = [paper_id for paper_id in citations if paper_id in evidence_ids]
        if factual and mapped and not unsupported and not numeric:
            covered += 1
        if factual and (not mapped or unsupported or numeric):
            unsupported_claims.append(f"C{index:03d}")
        rows.append(
            {
                "claim_id": f"C{index:03d}",
                "citations": citations,
                "evidence_chunk_ids": [evidence_chunk_by_id[paper_id] for paper_id in mapped],
                "needs_evidence": has_needs,
                "unsupported_citations": unsupported,
                "unsupported_number_or_doi": numeric,
                "prompt_leakage": leakage,
            }
        )
    factual_total = sum(1 for row in rows if not row["needs_evidence"])
    coverage = round(covered / factual_total, 4) if factual_total else 1.0
    errors = []
    if unsupported_citations:
        errors.append("unsupported citations present")
    if unsupported_claims:
        errors.append("unsupported factual claims present")
    if prompt_leakage:
        errors.append("prompt leakage present")
    if pack.get("needs_human_review") is not True:
        errors.append("needs_human_review must be true")
    if pack.get("trusted_for_scientific_quality") is not False:
        errors.append("trusted_for_scientific_quality must remain false")
    report = {
        "status": "fail" if errors else "pass",
        "errors": errors,
        "allowed_paper_ids": sorted(evidence_ids),
        "unsupported_citations": sorted(set(unsupported_citations)),
        "claim_evidence_coverage": coverage,
        "unsupported_claim_count": len(unsupported_claims),
        "unsupported_claim_ids": unsupported_claims,
        "prompt_leakage_count": len(prompt_leakage),
        "needs_human_review": pack.get("needs_human_review") is True,
        "trusted_for_scientific_quality": False,
        "human_review_tasks": [
            "Verify generated claims against source PDFs before scientific use.",
            *[item["task"] for item in needs_evidence_tasks],
        ],
    }
    return report, {"claims": rows}


def claim_paragraphs(section: str) -> list[str]:
    paragraphs = []
    for chunk in section.split("\n\n"):
        text = " ".join(chunk.split())
        if text and not re.match(r"^#{1,6}\s+", text):
            paragraphs.append(text)
    return paragraphs


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_md(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Grounding Report",
        "",
        f"- status: `{report['status']}`",
        f"- claim_evidence_coverage: `{report['claim_evidence_coverage']}`",
        f"- unsupported_claim_count: `{report['unsupported_claim_count']}`",
        f"- prompt_leakage_count: `{report['prompt_leakage_count']}`",
        f"- needs_human_review: `{report['needs_human_review']}`",
        "",
        "## Human Review Tasks",
    ]
    lines.extend(f"- {task}" for task in report["human_review_tasks"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
