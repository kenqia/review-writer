from __future__ import annotations

import difflib
import re
from collections import Counter
from pathlib import Path
from typing import Any

from .ai_adjudication import atomic_write_json, atomic_write_jsonl, atomic_write_text, sha256_file
from .phase8b_grounded_revision_v2 import (
    CONFLICT_DISPOSITION,
    _chemical_tokens,
    _claim_text,
    _normal_text,
    _numeric_signature,
    _numeric_tokens,
    _supported_numeric_tokens,
    canonicalize_model_payload,
)


STAGE_READY = "PHASE8B_SALVAGED_CANDIDATE_READY_FOR_HUMAN_REVIEW"
STAGE_FAILED = "PHASE8B_SALVAGE_BLOCKED"
CITATION_BY_PAPER = {"F3I": 1, "F47A": 2, "P403": 3}
PAPER_BY_CITATION = {value: key for key, value in CITATION_BY_PAPER.items()}
REVIEW_FRAME_RE = re.compile(r"\b(review|review-level|review literature|survey|overview)\b", re.IGNORECASE)
NUMERIC_CITATION_RE = re.compile(r"\[\d+(?:\s*,\s*\d+)*\]")
ALIAS_PATTERNS = {
    "CO2_EQUIVALENT_TO_CARBON_DIOXIDE": re.compile(r"\b(?:co2|carbon[ -]dioxide)\b", re.IGNORECASE),
}


def _validate_final_rows(rows: list[dict[str, Any]]) -> None:
    if len(rows) != 44 or len({row.get("claim_id") for row in rows}) != 44:
        raise ValueError("salvage requires 44 unique final claims")
    conflict_count = sum(row.get("final_disposition") == CONFLICT_DISPOSITION for row in rows)
    if conflict_count != 7:
        raise ValueError("salvage requires seven retained source conflicts")


def _sentence_score(sentence: dict[str, Any]) -> tuple[int, int, int, int]:
    text = _normal_text(sentence.get("text"))
    return (
        int(bool(re.search(r"\[\d", text))),
        int(bool(REVIEW_FRAME_RE.search(text))),
        len(_numeric_tokens(text)),
        len(text),
    )


def _deduplicate_sentence_ids(
    paragraph_sentence_ids: list[str], sentence_by_id: dict[str, dict[str, Any]]
) -> set[str]:
    removed: set[str] = set()
    for index, left_id in enumerate(paragraph_sentence_ids):
        if left_id in removed or left_id not in sentence_by_id:
            continue
        left = sentence_by_id[left_id]
        left_supports = set(left.get("supporting_claim_ids", []))
        left_numbers = _numeric_tokens(_normal_text(left.get("text")))
        for right_id in paragraph_sentence_ids[index + 1 :]:
            if right_id in removed or right_id not in sentence_by_id:
                continue
            right = sentence_by_id[right_id]
            if set(left.get("source_paper_ids", [])) != set(right.get("source_paper_ids", [])):
                continue
            right_supports = set(right.get("supporting_claim_ids", []))
            right_numbers = _numeric_tokens(_normal_text(right.get("text")))
            if left_supports == right_supports:
                loser = left_id if _sentence_score(left) < _sentence_score(right) else right_id
                removed.add(loser)
                if loser == left_id:
                    break
            elif left_supports < right_supports and left_numbers.issubset(right_numbers):
                removed.add(left_id)
                break
            elif right_supports < left_supports and right_numbers.issubset(left_numbers):
                removed.add(right_id)
    return removed


def _fixed_citation_marker(paper_ids: list[str]) -> tuple[list[int], str]:
    citation_ids = sorted({CITATION_BY_PAPER[paper_id] for paper_id in paper_ids})
    marker = "[" + ", ".join(str(value) for value in citation_ids) + "]"
    return citation_ids, marker


def _rewrite_citation(text: str, marker: str) -> str:
    without = NUMERIC_CITATION_RE.sub("", _normal_text(text))
    without = re.sub(r"\s+([,.;:!?])", r"\1", without).rstrip(". ")
    return f"{without} {marker}."


def _rewrite_s13(sentence: dict[str, Any], row_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    support_rows = [row_by_id[claim_id] for claim_id in sentence.get("supporting_claim_ids", [])]
    by_value = {
        str(row["final_claim"].get("value_as_reported")): row
        for row in support_rows
        if row["final_claim"].get("value_as_reported") is not None
    }
    if not {"84", "74", "62"}.issubset(by_value):
        raise ValueError("S13 salvage requires the supported 84%, 74%, and 62% claims")
    complex_product = _normal_text(by_value["84"]["final_claim"].get("product_id")) or "Complex 5"
    product = _normal_text(by_value["74"]["final_claim"].get("product_id")) or "3an"
    sentence = dict(sentence)
    sentence["text"] = (
        f"{complex_product[0].upper() + complex_product[1:]} was isolated in 84% yield; "
        f"the SI reports stoichiometric conversion to {product} in 74% isolated yield with DBA "
        "and 62% isolated yield without DBA [2]."
    )
    sentence["source_paper_ids"] = ["F47A"]
    sentence["numeric_citation_ids"] = [2]
    sentence.pop("factual_bindings", None)
    return sentence


def salvage_attempt2(raw_payload: dict[str, Any], final_rows: list[dict[str, Any]]) -> dict[str, Any]:
    _validate_final_rows(final_rows)
    row_by_id = {row["claim_id"]: row for row in final_rows}
    canonical = canonicalize_model_payload(raw_payload)
    sentence_by_id = {
        sentence["sentence_id"]: dict(sentence)
        for sentence in canonical.get("sentences", [])
        if isinstance(sentence, dict) and isinstance(sentence.get("sentence_id"), str)
    }
    paragraph_ids = [
        list(paragraph.get("sentence_ids", []))
        for paragraph in canonical.get("paragraphs", [])
        if isinstance(paragraph, dict)
    ]
    removed: set[str] = set()
    for sentence_ids in paragraph_ids:
        removed.update(_deduplicate_sentence_ids(sentence_ids, sentence_by_id))
    if "S13" not in sentence_by_id:
        raise ValueError("Attempt 2 lacks required sentence S13")
    sentence_by_id["S13"] = _rewrite_s13(sentence_by_id["S13"], row_by_id)

    ordered_sentences = []
    for sentence in canonical["sentences"]:
        sentence_id = sentence["sentence_id"]
        if sentence_id in removed:
            continue
        current = dict(sentence_by_id[sentence_id])
        support_ids = list(dict.fromkeys(current.get("supporting_claim_ids", [])))
        support_rows = [row_by_id[claim_id] for claim_id in support_ids if claim_id in row_by_id]
        paper_ids = sorted(
            {row["final_claim"]["paper_id"] for row in support_rows},
            key=lambda paper_id: CITATION_BY_PAPER[paper_id],
        )
        citation_ids, marker = _fixed_citation_marker(paper_ids)
        current["supporting_claim_ids"] = support_ids
        current["source_paper_ids"] = paper_ids
        current["numeric_citation_ids"] = citation_ids
        if sentence_id != "S13":
            current["text"] = _rewrite_citation(current["text"], marker)
        current.pop("factual_bindings", None)
        ordered_sentences.append(current)

    surviving_ids = {sentence["sentence_id"] for sentence in ordered_sentences}
    paragraphs = []
    for paragraph in canonical["paragraphs"]:
        sentence_ids = [value for value in paragraph.get("sentence_ids", []) if value in surviving_ids]
        if not sentence_ids:
            continue
        paragraphs.append(
            {
                "paragraph_id": paragraph.get("paragraph_id"),
                "sentence_ids": sentence_ids,
                "text": " ".join(sentence_by_id[value]["text"] if value == "S13" else next(
                    sentence["text"] for sentence in ordered_sentences if sentence["sentence_id"] == value
                ) for value in sentence_ids),
            }
        )
    selected_ids = sorted(
        {claim_id for sentence in ordered_sentences for claim_id in sentence["supporting_claim_ids"]}
    )
    allowed_ids = {
        row["claim_id"] for row in final_rows if row["final_disposition"] != CONFLICT_DISPOSITION
    }
    omitted = [
        {"claim_id": claim_id, "reason_code": "NOT_USED_BY_SALVAGED_SENTENCE_SUPPORT_UNION"}
        for claim_id in sorted(allowed_ids - set(selected_ids))
    ]
    payload = {
        "section_title": canonical.get("section_title"),
        "section_outline": canonical.get("section_outline", []),
        "selected_claim_ids": selected_ids,
        "paragraphs": paragraphs,
        "sentences": ordered_sentences,
        "citation_order": [
            {"citation_id": citation_id, "paper_id": PAPER_BY_CITATION[citation_id]}
            for citation_id in sorted(PAPER_BY_CITATION)
        ],
        "omitted_claims_and_reasons": omitted,
    }
    auto_fixes = [
        {"code": "SCHEMA_REPRESENTATION_NORMALIZED", "count": 1},
        {"code": "PARAGRAPH_SENTENCE_STRUCTURE_REBUILT", "count": len(paragraphs)},
        {"code": "SELECTED_CLAIMS_REBUILT_FROM_SUPPORT_UNION", "count": len(selected_ids)},
        {"code": "CITATIONS_RENUMBERED_BY_PAPER", "count": len(ordered_sentences)},
        {"code": "FACTUAL_BINDINGS_REBUILT_PROGRAMMATICALLY", "count": len(ordered_sentences)},
        {"code": "UNSUPPORTED_S13_RANGE_REPLACED_FROM_FINAL_CLAIMS", "count": 1},
        {"code": "DUPLICATE_CONTEXT_SENTENCES_REMOVED", "count": len(removed), "sentence_ids": sorted(removed)},
    ]
    return {"payload": payload, "auto_fixes_applied": auto_fixes, "removed_sentence_ids": sorted(removed)}


def _alias_normalize(text: str) -> tuple[str, list[str]]:
    normalized = text.casefold()
    applied = []
    for alias_name, pattern in ALIAS_PATTERNS.items():
        if pattern.search(normalized):
            normalized = pattern.sub("co2", normalized)
            applied.append(alias_name)
    return normalized, applied


def _blocker(code: str, message: str, sentence_id: str | None = None) -> dict[str, Any]:
    item = {"code": code, "message": message}
    if sentence_id:
        item["sentence_id"] = sentence_id
    return item


def validate_salvaged_payload(payload: dict[str, Any], final_rows: list[dict[str, Any]]) -> dict[str, Any]:
    _validate_final_rows(final_rows)
    row_by_id = {row["claim_id"]: row for row in final_rows}
    conflict_ids = {
        row["claim_id"] for row in final_rows if row["final_disposition"] == CONFLICT_DISPOSITION
    }
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    aliases_applied: set[str] = set()
    sentence_by_id = {}
    numeric_seen: dict[tuple[str, ...], str] = {}
    for sentence in payload.get("sentences", []):
        sentence_id = sentence.get("sentence_id")
        text = _normal_text(sentence.get("text"))
        support_ids = sentence.get("supporting_claim_ids", [])
        sentence_by_id[sentence_id] = sentence
        unknown = set(support_ids) - set(row_by_id)
        if unknown:
            blockers.append(_blocker("UNKNOWN_CLAIM_ID", f"unknown claim IDs: {sorted(unknown)}", sentence_id))
        if set(support_ids) & conflict_ids:
            blockers.append(_blocker("SOURCE_CONFLICT_CLAIM_IN_PROSE", "retained source conflict supports prose", sentence_id))
        support_rows = [row_by_id[claim_id] for claim_id in support_ids if claim_id in row_by_id]
        expected_papers = sorted(
            {row["final_claim"]["paper_id"] for row in support_rows},
            key=lambda paper_id: CITATION_BY_PAPER[paper_id],
        )
        expected_citations, marker = _fixed_citation_marker(expected_papers)
        if sentence.get("source_paper_ids") != expected_papers or sentence.get("numeric_citation_ids") != expected_citations:
            blockers.append(_blocker("CITATION_WRONG_PAPER", "citation metadata does not match supporting paper", sentence_id))
        markers = NUMERIC_CITATION_RE.findall(text)
        if markers != [marker] or not text.endswith(f"{marker}."):
            blockers.append(_blocker("CITATION_WRONG_PAPER", "citation marker does not match supporting paper", sentence_id))
        unsupported_numbers = _numeric_tokens(text) - _supported_numeric_tokens(support_rows)
        if unsupported_numbers:
            blockers.append(
                _blocker(
                    "UNSUPPORTED_SCIENTIFIC_NUMBER",
                    f"unsupported numeric tokens: {sorted(unsupported_numbers)}",
                    sentence_id,
                )
            )
        support_text = " ".join(_claim_text(row) for row in support_rows)
        normalized_support, support_aliases = _alias_normalize(support_text)
        normalized_text, text_aliases = _alias_normalize(text)
        aliases_applied.update(set(support_aliases) & set(text_aliases))
        for token in sorted(_chemical_tokens(text)):
            normalized_token, token_aliases = _alias_normalize(token)
            aliases_applied.update(set(token_aliases) & set(support_aliases))
            if normalized_token not in normalized_support:
                blockers.append(
                    _blocker("UNSUPPORTED_CHEMICAL_ENTITY", f"unsupported entity token: {token}", sentence_id)
                )
        if re.search(r"\b(?:dba|dibenzalacetone)\b", normalized_text) and not re.search(
            r"\b(?:dba|dibenzalacetone)\b", normalized_support
        ):
            blockers.append(_blocker("UNSUPPORTED_DBA_BINDING", "DBA is absent from supporting claims", sentence_id))
        for row in support_rows:
            signature = _numeric_signature(row)
            if signature is None:
                continue
            previous = numeric_seen.get(signature)
            if previous and previous != sentence_id:
                warnings.append(
                    {
                        "code": "POTENTIALLY_DUPLICATED_NARRATIVE_RESULT",
                        "sentence_id": sentence_id,
                        "related_sentence_id": previous,
                    }
                )
            numeric_seen[signature] = sentence_id

    support_union = sorted(
        {claim_id for sentence in payload.get("sentences", []) for claim_id in sentence.get("supporting_claim_ids", [])}
    )
    if payload.get("selected_claim_ids") != support_union:
        blockers.append(_blocker("SELECTED_SUPPORT_CONTRADICTION", "selected claims differ from sentence support union"))
    for paragraph in payload.get("paragraphs", []):
        sentence_ids = paragraph.get("sentence_ids", [])
        paragraph_sentences = [sentence_by_id[value] for value in sentence_ids if value in sentence_by_id]
        paragraph_papers = {
            paper_id for sentence in paragraph_sentences for paper_id in sentence.get("source_paper_ids", [])
        }
        paragraph_text = " ".join(sentence.get("text", "") for sentence in paragraph_sentences)
        if paragraph_papers == {"F3I"} and not REVIEW_FRAME_RE.search(paragraph_text):
            warnings.append(
                {
                    "code": "REVIEW_LEVEL_FRAMING_NOT_EXPLICIT_AT_PARAGRAPH_LEVEL",
                    "paragraph_id": paragraph.get("paragraph_id"),
                }
            )
        if len(paragraph_text.split()) > 220:
            warnings.append(
                {"code": "LONG_PARAGRAPH", "paragraph_id": paragraph.get("paragraph_id")}
            )
    return {
        "schema_version": "salvage-1.0",
        "status": "PASS" if not blockers else "FAIL",
        "blocker_count": len(blockers),
        "blockers": blockers,
        "warning_count": len(warnings),
        "warnings": warnings,
        "aliases_applied": sorted(aliases_applied),
        "sentence_count": len(payload.get("sentences", [])),
        "selected_claim_count": len(payload.get("selected_claim_ids", [])),
        "final_claim_accounting_count": 44,
    }


def build_issue_reclassification(
    old_report: dict[str, Any], raw_payload: dict[str, Any], final_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    row_by_id = {row["claim_id"]: row for row in final_rows}
    sentence_by_id = {
        sentence.get("sentence_id"): sentence
        for sentence in raw_payload.get("sentences", [])
        if isinstance(sentence, dict)
    }
    items = []
    for issue in old_report.get("issues", []):
        code = issue.get("code")
        sentence = sentence_by_id.get(issue.get("sentence_id"), {})
        if code in {
            "INVALID_FACTUAL_BINDING",
            "CITATION_TEXT_MISMATCH",
            "INVALID_CITATION_ORDER",
            "PARAGRAPH_SENTENCE_MISMATCH",
            "SELECTED_SUPPORT_MISMATCH",
        }:
            category = "AUTO_FIX"
        elif code == "CITATION_PAPER_MISMATCH":
            support_papers = {
                row_by_id[claim_id]["final_claim"]["paper_id"]
                for claim_id in sentence.get("supporting_claim_ids", [])
                if claim_id in row_by_id
            }
            category = "AUTO_FIX" if support_papers == set(sentence.get("source_paper_ids", [])) else "BLOCKER"
        elif code == "UNSUPPORTED_ENTITY" and "co2" in str(issue.get("message", "")).casefold():
            category = "AUTO_FIX"
        elif code in {
            "UNSUPPORTED_NUMBER",
            "SOURCE_CONFLICT_IN_PROSE",
            "UNSUPPORTED_DBA_BINDING",
            "UNKNOWN_CLAIM_ID",
            "CORE_FACT_CONTRADICTION",
        }:
            category = "BLOCKER"
        else:
            category = "WARNING"
        items.append(
            {
                "original_code": code,
                "sentence_id": issue.get("sentence_id"),
                "category": category,
            }
        )
    return {
        "schema_version": "salvage-1.0",
        "counts": dict(Counter(row["category"] for row in items)),
        "items": items,
    }


def _render_section(payload: dict[str, Any]) -> str:
    sentence_by_id = {row["sentence_id"]: row["text"] for row in payload["sentences"]}
    lines = [f"## {payload['section_title']}", ""]
    for paragraph in payload["paragraphs"]:
        lines.extend([" ".join(sentence_by_id[value] for value in paragraph["sentence_ids"]), ""])
    return "\n".join(lines)


def _render_original(payload: dict[str, Any]) -> str:
    lines = [f"## {payload['section_title']}", ""]
    for paragraph in payload.get("paragraphs", []):
        lines.extend([_normal_text(paragraph.get("text")), ""])
    return "\n".join(lines)


def _citation_map(metadata: dict[str, dict[str, Any]]) -> dict[str, Any]:
    entries = []
    for paper_id, citation_id in CITATION_BY_PAPER.items():
        row = metadata[paper_id]
        complete = bool(row.get("authors") and row.get("doi"))
        entries.append(
            {
                "citation_id": citation_id,
                "paper_id": paper_id,
                "title": row.get("title"),
                "authors": row.get("authors") or [],
                "year": row.get("year"),
                "journal": row.get("journal"),
                "doi": row.get("doi"),
                "metadata_status": "COMPLETE_DRAFT" if complete else "BIBLIOGRAPHY_METADATA_PENDING",
            }
        )
    return {
        "schema_version": "salvage-1.0",
        "status": (
            "BIBLIOGRAPHY_METADATA_PENDING"
            if any(row["metadata_status"] == "BIBLIOGRAPHY_METADATA_PENDING" for row in entries)
            else "COMPLETE_DRAFT"
        ),
        "entries": entries,
    }


def _write_hash_manifest(root: Path) -> str:
    paths = sorted(path for path in root.rglob("*") if path.is_file() and path.name != "HASH_MANIFEST.sha256")
    atomic_write_text(
        root / "HASH_MANIFEST.sha256",
        "\n".join(f"{sha256_file(path)}  {path.relative_to(root).as_posix()}" for path in paths) + "\n",
    )
    return sha256_file(root / "HASH_MANIFEST.sha256")


def prepare_salvage_run(
    *,
    run_root: Path,
    original_payload: dict[str, Any],
    salvage: dict[str, Any],
    validation: dict[str, Any],
    issue_reclassification: dict[str, Any],
    citation_metadata: dict[str, dict[str, Any]],
    run_manifest: dict[str, Any],
) -> dict[str, Any]:
    if run_root.exists():
        raise FileExistsError(f"salvage run already exists: {run_root}")
    stage = STAGE_READY if validation["blocker_count"] == 0 else STAGE_FAILED
    for relative in ("revision", "mapping", "citations", "reports", "coordinator"):
        (run_root / relative).mkdir(parents=True, exist_ok=True)
    payload = salvage["payload"]
    original = _render_original(original_payload)
    revision = _render_section(payload)
    atomic_write_text(run_root / "revision/grounded_revision_salvaged.md", revision)
    atomic_write_text(
        run_root / "revision/salvage.diff",
        "".join(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                revision.splitlines(keepends=True),
                fromfile="attempt2_original.md",
                tofile="grounded_revision_salvaged.md",
            )
        ),
    )
    mapping = [
        {
            "sentence_id": sentence["sentence_id"],
            "text": sentence["text"],
            "supporting_claim_ids": sentence["supporting_claim_ids"],
            "source_paper_ids": sentence["source_paper_ids"],
            "numeric_citation_ids": sentence["numeric_citation_ids"],
            "binding_status": "PROGRAMMATIC_SENTENCE_TO_FINAL_CLAIM_BINDING",
        }
        for sentence in payload["sentences"]
    ]
    atomic_write_jsonl(run_root / "mapping/sentence_claim_map_salvaged.jsonl", mapping)
    citation_map = _citation_map(citation_metadata)
    atomic_write_json(run_root / "citations/citation_map.json", citation_map)
    validation_report = {**validation, "auto_fixes_applied": salvage["auto_fixes_applied"]}
    atomic_write_json(run_root / "reports/salvage_validation.json", validation_report)
    atomic_write_json(run_root / "reports/validator_issue_reclassification.json", issue_reclassification)
    packet = [
        "# Phase 8B Salvaged Candidate Human Review Packet",
        "",
        revision.rstrip(),
        "",
        "## Deterministic Salvage",
        "",
        "- Rebuilt numeric citations from supporting paper IDs.",
        "- Rebuilt selected claims from the sentence-support union.",
        "- Removed redundant contextual sentences.",
        "- Replaced the unsupported S13 range with the supported 84%, 74%, and 62% records.",
        "- Treated CO2 and carbon dioxide as a controlled alias.",
        "",
        "## Citation Map",
        "",
        *(f"- [{row['citation_id']}] `{row['paper_id']}` ({row['metadata_status']})" for row in citation_map["entries"]),
        "",
        "## Validation",
        "",
        f"- blocker count: `{validation['blocker_count']}`",
        f"- warning count: `{validation['warning_count']}`",
        f"- status: `{validation['status']}`",
        "",
        "Choose one: `ACCEPT`, `ACCEPT_WITH_MINOR_CHANGES`, or `REVISE`.",
        "",
    ]
    atomic_write_text(run_root / "reports/human_review_packet.md", "\n".join(packet))
    manifest = {
        **run_manifest,
        "schema_version": "salvage-1.0",
        "stage": stage,
        "blocker_count": validation["blocker_count"],
        "warning_count": validation["warning_count"],
        "sentence_count": validation["sentence_count"],
        "selected_claim_count": validation["selected_claim_count"],
        "final_claim_accounting_count": 44,
        "model_requests": 0,
        "human_decisions_created": 0,
        "whole_review_expanded": False,
    }
    atomic_write_json(run_root / "coordinator/run_manifest.json", manifest)
    manifest_hash = _write_hash_manifest(run_root)
    return {
        "status": validation["status"],
        "stage": stage,
        "run_root": str(run_root),
        "hash_manifest_sha256": manifest_hash,
        "model_requests": 0,
    }
