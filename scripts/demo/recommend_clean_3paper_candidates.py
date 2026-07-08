#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

TOPIC_TERMS = {
    "allene": 18,
    "allenes": 18,
    "allenyl": 14,
    "allenamide": 12,
    "allenamides": 12,
    "asymmetric": 14,
    "enantioselective": 14,
    "enantiospecific": 12,
    "chiral": 12,
    "axially": 10,
    "catalytic": 8,
    "catalyzed": 8,
    "palladium": 8,
    "copper": 8,
    "gold": 8,
    "nickel": 8,
    "rhodium": 8,
    "organocatalytic": 8,
    "synthesis": 5,
}

CLASSIC_TERMS = ["review", "overview", "advances", "critical assessment", "modern allene chemistry", "synthesis and properties"]
REPRESENTATIVE_TERMS = ["asymmetric", "enantioselective", "chiral", "axially", "palladium", "copper", "gold", "rhodium"]
RECENT_TERMS = ["2023", "2024", "2025"]

MANUAL_BOOSTS = {
    "3i-angew chem int ed - 2012 - yu - allenes in catalytic asymmetric synthesis and natural product syntheses.pdf": 80,
    "4a-angew chem int ed - 2002 - hoffmann": 45,
    "4g-recent-advances-in-the-catalytic-syntheses-of-allenes-a-critical-assessment.pdf": 55,
    "47a-palladium-catalyzed-asymmetric-synthesis-of-axially-chiral-allenes": 60,
    "24a-gold-catalyzed-highly-enantioselective-synthesis-of-axially-chiral-allenes.pdf": 42,
    "14-copper-catalyzed-enantioselective-synthesis-of-axially-chiral-allenes.pdf": 42,
    "pd-catalyzed-asymmetric-allenylation-of-secondary-phosphine-oxides": 75,
    "ligand-controlled-preparation-of-aryl-substituted-allenes": 55,
    "angew chem int ed - 2024 - wen - remote enantioselective": 50,
}


class RecommendationError(Exception):
    pass


def main() -> int:
    args = parse_args()
    try:
        report = recommend(args.paper_root, args.real_lite_root)
    except RecommendationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.output_json:
        write_json(args.output_json, report)
    if args.output_md:
        write_markdown(args.output_md, report)
    print(
        "clean-3paper-recommendation: "
        f"{report['status']} candidates={len(report['candidates'])} "
        f"top3={','.join(report['recommended_sets'][0]['selected_candidates'])}"
    )
    return 1 if args.strict and report["status"] == "fail" else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recommend clean 3-paper allene dataset candidates without reading PDFs.")
    parser.add_argument("--paper-root", type=Path, default=Path("chem_papers"))
    parser.add_argument("--real-lite-root", type=Path, default=Path("demo_projects/real_lite_allene_review"))
    parser.add_argument("--output-json", type=Path, default=Path("/tmp/clean_3paper_recommendations.json"))
    parser.add_argument("--output-md", type=Path, default=Path("/tmp/clean_3paper_recommendations.md"))
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def recommend(paper_root: Path, real_lite_root: Path) -> dict[str, Any]:
    pdf_rows = scan_pdf_filenames(paper_root)
    real_lite_rows = load_real_lite_candidates(real_lite_root)
    merged = merge_candidates(pdf_rows, real_lite_rows)
    if not merged:
        raise RecommendationError("no candidates found from PDF filenames or real-lite metadata")
    for row in merged:
        score_candidate(row)
    selected = choose_candidate_pool(merged)
    if len(selected) < 6:
        raise RecommendationError(f"expected at least 6 candidates, found {len(selected)}")
    for rank, row in enumerate(selected, start=1):
        row["rank"] = rank
    top3 = choose_top3(selected)
    if len(top3) != 3:
        raise RecommendationError("could not form a balanced top-3 set")
    report = {
        "status": "pass",
        "summary": {
            "paper_root_exists": paper_root.exists(),
            "pdf_filename_count": len(pdf_rows),
            "real_lite_candidate_count": len(real_lite_rows),
            "candidate_count": len(selected),
            "selection_basis": [
                "PDF filenames only",
                "committed real-lite metadata and selected_papers.json",
                "no PDF body reads",
                "no API calls",
            ],
        },
        "recommended_sets": [
            {
                "recommended_set_id": "clean_3paper_allene_v1_candidate_set",
                "selected_candidates": [row["candidate_id"] for row in top3],
                "coverage_rationale": [
                    "one classic or review-like background paper",
                    "one representative asymmetric/chiral allene method paper",
                    "one 2023-2025 recent-progress method paper",
                ],
                "why_this_trio_is_balanced": (
                    "The trio gives a review/background anchor, a focused asymmetric allene synthesis method, "
                    "and a recent progress paper with committed real-lite metadata. It is balanced for building "
                    "a small human-verified dataset, not for final scientific claims yet."
                ),
            }
        ],
        "candidates": selected,
        "alternative_candidates": [row["candidate_id"] for row in selected if row["candidate_id"] not in {item["candidate_id"] for item in top3}],
        "safety": {
            "network": "not_used",
            "pdf_body_read": "not_used",
            "qwen": "not_used",
            "mineru_api": "not_used",
            "upload": "not_used",
            "knowledge_base": "not_created",
            "image_api": "not_used",
        },
        "human_selection_required": True,
        "next_actions": [
            "User accepts top 3 or requests replacements.",
            "User explicitly authorizes read-only parsing for only the selected 3 PDFs.",
            "Keep uploads and knowledge-base creation disabled unless separately approved later.",
        ],
    }
    return report


def scan_pdf_filenames(paper_root: Path) -> list[dict[str, Any]]:
    if not paper_root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(paper_root.glob("*.pdf")):
        filename = path.name
        stem = path.stem
        rows.append(
            {
                "source": "pdf_filename",
                "paper_id": None,
                "candidate_id": candidate_id_from_filename(filename),
                "filename": str(Path("chem_papers") / filename),
                "inferred_title": infer_title_from_filename(stem),
                "inferred_year": infer_year(filename),
                "inferred_journal": infer_journal(filename),
                "metadata_source": "filename_only",
                "metadata_completeness_score": 0.35,
            }
        )
    return rows


def load_real_lite_candidates(real_lite_root: Path) -> list[dict[str, Any]]:
    inputs = real_lite_root / "inputs"
    selected_path = inputs / "selected_papers.json"
    if not selected_path.exists():
        return []
    selected_payload = load_json(selected_path)
    selected = selected_payload.get("selected_papers") if isinstance(selected_payload, dict) else []
    rows: list[dict[str, Any]] = []
    for item in selected or []:
        paper_id = str(item.get("paper_id") or "").strip()
        if not paper_id:
            continue
        meta_path = inputs / "paper_metadata" / f"{paper_id}.metadata.json"
        metadata = load_json(meta_path) if meta_path.exists() else {}
        title = field_value(metadata.get("title")) or item.get("title") or paper_id
        year = field_value(metadata.get("year")) or item.get("year")
        journal = field_value(metadata.get("journal")) or ""
        slug = item.get("slug") or slugify(title)
        filename = f"chem_papers/{slug}.pdf"
        rows.append(
            {
                "source": "real_lite_metadata",
                "paper_id": paper_id,
                "candidate_id": paper_id,
                "filename": filename,
                "inferred_title": str(title),
                "inferred_year": int(year) if str(year).isdigit() else None,
                "inferred_journal": str(journal) if journal else infer_journal(str(title)),
                "metadata_source": "real_lite_selected_papers",
                "metadata_completeness_score": float(item.get("completeness_score") or 0) / 6.0,
            }
        )
    return rows


def merge_candidates(pdf_rows: list[dict[str, Any]], real_lite_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for row in pdf_rows + real_lite_rows:
        key = slugify(row.get("paper_id") or Path(row["filename"]).stem)
        existing = by_key.get(key)
        if existing is None or row["metadata_completeness_score"] > existing["metadata_completeness_score"]:
            by_key[key] = row
    return list(by_key.values())


def score_candidate(row: dict[str, Any]) -> None:
    text = " ".join(str(row.get(key) or "") for key in ["filename", "inferred_title", "inferred_journal"]).lower()
    topic_score = sum(weight for term, weight in TOPIC_TERMS.items() if term in text)
    for needle, boost in MANUAL_BOOSTS.items():
        if needle in text:
            topic_score += boost
    row["topic_match_score"] = min(100, topic_score)
    row["recency_or_classic_score"] = recency_or_classic_score(row, text)
    row["role"] = infer_role(row, text)
    row["risks"] = risks_for(row)
    row["why_selected"] = why_selected(row)
    row["needs_pdf_read_verification"] = True
    row["human_verified"] = False
    row["_sort_score"] = (
        row["topic_match_score"] * 0.55
        + row["metadata_completeness_score"] * 100 * 0.25
        + row["recency_or_classic_score"] * 0.20
    )


def recency_or_classic_score(row: dict[str, Any], text: str) -> int:
    year = row.get("inferred_year")
    if "allenes in catalytic asymmetric synthesis and natural product syntheses" in text:
        return 98
    if "palladium catalyzed asymmetric synthesis of axially chiral allenes" in text:
        return 88
    if isinstance(year, int) and year >= 2023:
        return 95
    if any(term in text for term in CLASSIC_TERMS):
        return 90
    if isinstance(year, int) and year <= 2012 and any(term in text for term in ["review", "catalytic asymmetric", "enantioselective synthesis"]):
        return 80
    if isinstance(year, int) and year >= 2013:
        return 65
    return 45


def infer_role(row: dict[str, Any], text: str) -> str:
    year = row.get("inferred_year")
    if any(term in text for term in CLASSIC_TERMS) or "natural product syntheses" in text:
        return "review_background"
    if isinstance(year, int) and year >= 2023:
        return "recent_progress"
    if any(term in text for term in REPRESENTATIVE_TERMS):
        return "representative_method"
    return "fallback"


def risks_for(row: dict[str, Any]) -> list[str]:
    risks = [
        "candidate only; not human verified",
        "PDF body has not been read",
        "claims, figures, DOI, and citations still require verification",
    ]
    if row["metadata_source"] == "filename_only":
        risks.append("metadata inferred from filename only")
    if row.get("paper_id") and row["metadata_source"] == "real_lite_selected_papers":
        risks.append("real-lite metadata may contain extraction artifacts and still needs human cleanup")
    if not row.get("inferred_year"):
        risks.append("year inferred as unknown")
    return risks


def why_selected(row: dict[str, Any]) -> str:
    role = row["role"]
    if role == "review_background":
        return "Strong background candidate for orienting allene synthesis and catalytic asymmetric synthesis taxonomy."
    if role == "representative_method":
        return "Strong method candidate for chiral or asymmetric allene synthesis with catalyst-specific relevance."
    if role == "recent_progress":
        return "Recent allene-synthesis candidate useful for testing whether the clean dataset captures 2023-2025 progress."
    return "Fallback allene-related candidate retained as a replacement option if a top candidate fails human verification."


def choose_candidate_pool(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    eligible = [row for row in rows if row["topic_match_score"] >= 35]
    by_role: dict[str, list[dict[str, Any]]] = {}
    for row in sorted(eligible, key=lambda item: item["_sort_score"], reverse=True):
        by_role.setdefault(row["role"], []).append(row)
    selected: list[dict[str, Any]] = []
    for role, limit in [("review_background", 3), ("representative_method", 5), ("recent_progress", 4), ("fallback", 2)]:
        selected.extend(by_role.get(role, [])[:limit])
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in sorted(selected, key=lambda item: item["_sort_score"], reverse=True):
        if row["candidate_id"] in seen:
            continue
        seen.add(row["candidate_id"])
        unique.append(strip_internal(row))
    return unique[:10]


def choose_top3(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    top: list[dict[str, Any]] = []
    preferred = {
        "review_background": ["F3I", "F4G", "F4A"],
        "representative_method": ["F47A", "F14", "F24A", "F4A"],
        "recent_progress": ["P403", "P401", "C2024-angew-chem-int-ed-2024-wen-remote-enantios"],
    }
    for role in ["review_background", "representative_method", "recent_progress"]:
        choices = [row for row in rows if row["role"] == role and row["candidate_id"] not in {item["candidate_id"] for item in top}]
        if choices:
            pref = preferred.get(role, [])
            choices.sort(key=lambda row: pref.index(row["candidate_id"]) if row["candidate_id"] in pref else len(pref))
            top.append(choices[0])
    return top


def strip_internal(row: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(row)
    cleaned.pop("_sort_score", None)
    cleaned["metadata_completeness_score"] = round(float(cleaned["metadata_completeness_score"]), 2)
    return cleaned


def infer_title_from_filename(stem: str) -> str:
    title = re.sub(r"^\d+[a-z]?-", "", stem)
    title = re.sub(r"^1-s2\.0-[^-]+-main(?: \(1\))?$", stem, title)
    title = title.replace("_", " ").replace("-", " ")
    title = re.sub(r"\s+", " ", title).strip()
    return title[:1].upper() + title[1:] if title else stem


def infer_year(text: str) -> int | None:
    matches = [int(match) for match in re.findall(r"(?:19|20)\d{2}", text)]
    return matches[0] if matches else None


def infer_journal(text: str) -> str:
    lowered = text.lower()
    journal_patterns = [
        ("Angew Chem Int Ed", "Angew. Chem. Int. Ed."),
        ("J. Am. Chem. Soc.", "J. Am. Chem. Soc."),
        ("Org. Lett.", "Org. Lett."),
        ("ACS Catal.", "ACS Catal."),
        ("Adv Synth Catal", "Adv. Synth. Catal."),
        ("Eur J Org Chem", "Eur. J. Org. Chem."),
        ("Chemistry A European J", "Chem. Eur. J."),
        ("Nature Communications", "Nature Communications"),
        ("Nat. Commun.", "Nature Communications"),
        ("Chinese Journal of Chemistry", "Chinese Journal of Chemistry"),
        ("Chinese Chemical Letters", "Chinese Chemical Letters"),
    ]
    for needle, journal in journal_patterns:
        if needle.lower() in lowered:
            return journal
    return ""


def candidate_id_from_filename(filename: str) -> str:
    stem = Path(filename).stem
    prefix = re.match(r"^(\d+[a-z]?)", stem)
    if prefix:
        return f"F{prefix.group(1).upper()}"
    year = infer_year(filename)
    base = slugify(stem)[:42].strip("-")
    return f"C{year or 'UNK'}-{base}"


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def field_value(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return field_value(value["value"])
    return value


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RecommendationError(f"invalid JSON: {path} ({exc})") from exc


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    top = report["recommended_sets"][0]["selected_candidates"]
    by_id = {row["candidate_id"]: row for row in report["candidates"]}
    lines = [
        "# Clean 3-Paper Candidate Recommendations",
        "",
        "This is an AI-assisted candidate shortlist based on filenames and committed real-lite metadata only.",
        "No PDF body was read and no API was called.",
        "",
        "## Top 3",
        "",
    ]
    for candidate_id in top:
        row = by_id[candidate_id]
        lines.extend(
            [
                f"### {row['rank']}. `{candidate_id}`",
                "",
                f"- Title: {row['inferred_title']}",
                f"- File: `{row['filename']}`",
                f"- Year: {row.get('inferred_year') or 'unknown'}",
                f"- Role: `{row['role']}`",
                f"- Why: {row['why_selected']}",
                f"- Risks: {'; '.join(row['risks'])}",
                "",
            ]
        )
    lines.extend(["## Alternatives", ""])
    for candidate_id in report["alternative_candidates"]:
        row = by_id[candidate_id]
        lines.append(f"- `{candidate_id}` ({row['role']}): {row['inferred_title']}")
    lines.extend(["", "## Human Confirmation Needed", ""])
    lines.extend(f"- {item}" for item in report["next_actions"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
