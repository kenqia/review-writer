from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

from .ai_adjudication import _is_within, atomic_write_json, atomic_write_jsonl, atomic_write_text, sha256_file


RUN_ID_RE = re.compile(r"^phase8b_grounded_vertical_slice_\d{8}T\d{6}Z$")
PAPER_ORDER = ("F3I", "F47A", "P403")
EXPECTED_FINAL_CLAIM_COUNT = 44
EXPECTED_NON_CONFLICT_COUNT = 37
EXPECTED_CONFLICT_COUNT = 7
EXPECTED_PHASE7_SENTENCE_COUNT = 10
PER_PAPER_SELECTION_LIMIT = 4
SECTION_TITLE = "Representative strategies for asymmetric allene synthesis"
METHOD_LABEL = "HUMAN_SPOT_CHECKED_AI_ADJUDICATION"
CLAIM_TYPE_PRIORITY = {
    "target_reaction_numeric_outcome": 0,
    "optimization_result": 0,
    "stoichiometric_result": 1,
    "scope_result": 2,
    "experimental_mechanistic_observation": 3,
    "author_proposed_mechanism": 4,
    "negative_scope": 5,
    "explicit_limitation": 6,
}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()


def _verify_hash(path: Path, expected: str, label: str) -> str:
    if not path.is_file() or sha256_file(path) != expected:
        raise ValueError(f"{label} hash mismatch")
    return expected


def _validate_final_claims(rows: list[dict[str, Any]]) -> None:
    if len(rows) != EXPECTED_FINAL_CLAIM_COUNT or len({row.get("claim_id") for row in rows}) != len(rows):
        raise ValueError("Phase 8B vertical slice requires 44 unique final claims")
    conflict_count = 0
    for row in rows:
        claim = row.get("final_claim")
        if not isinstance(claim, dict) or claim.get("claim_id") != row.get("claim_id"):
            raise ValueError("final claim record has an invalid claim binding")
        if claim.get("paper_id") not in PAPER_ORDER:
            raise ValueError(f"final claim has an unsupported paper ID: {row.get('claim_id')}")
        conflict = row.get("final_disposition") == "SOURCE_CONFLICT_RETAINED"
        if conflict:
            conflict_count += 1
            source_conflict = claim.get("source_conflict")
            if not claim.get("source_conflict_detected") or not isinstance(source_conflict, dict):
                raise ValueError(f"retained conflict lacks structured conflict data: {row.get('claim_id')}")
            if len(source_conflict.get("alternatives", [])) < 2:
                raise ValueError(f"retained conflict lacks alternatives: {row.get('claim_id')}")
        elif claim.get("source_conflict_detected"):
            raise ValueError(f"non-conflict disposition carries a conflict flag: {row.get('claim_id')}")
    if conflict_count != EXPECTED_CONFLICT_COUNT:
        raise ValueError("Phase 8B vertical slice requires exactly seven retained source conflicts")


def _validate_phase7_claims(payload: dict[str, Any]) -> list[dict[str, Any]]:
    claims = payload.get("claims")
    if not isinstance(claims, list) or len(claims) != EXPECTED_PHASE7_SENTENCE_COUNT:
        raise ValueError("representative Phase 7 section must contain exactly ten sentence claims")
    if len({row.get("sentence_id") for row in claims}) != len(claims):
        raise ValueError("Phase 7 sentence IDs are not unique")
    for row in claims:
        if not isinstance(row.get("claim_text"), str) or not row["claim_text"].strip():
            raise ValueError("Phase 7 sentence claim lacks text")
        citations = row.get("citation_ids")
        if not isinstance(citations, list) or any(citation not in PAPER_ORDER for citation in citations):
            raise ValueError("Phase 7 sentence has an unsupported citation")
    return claims


def _select_claims(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = []
    for paper_id in PAPER_ORDER:
        eligible = [
            row
            for row in rows
            if row["final_claim"]["paper_id"] == paper_id
            and row["final_disposition"] != "SOURCE_CONFLICT_RETAINED"
        ]
        eligible.sort(
            key=lambda row: (
                CLAIM_TYPE_PRIORITY.get(row["final_claim"].get("claim_type"), 99),
                row["claim_id"],
            )
        )
        if not eligible:
            raise ValueError(f"no usable claim is available for {paper_id}")
        selected.extend(eligible[:PER_PAPER_SELECTION_LIMIT])
    return selected


def _grounded_sentence(row: dict[str, Any], sentence_id: str) -> dict[str, Any]:
    claim = row["final_claim"]
    paper_id = claim["paper_id"]
    evidence = " ".join(str(claim.get("short_evidence") or "").split())
    if not evidence:
        raise ValueError(f"selected claim lacks short evidence: {row['claim_id']}")
    evidence = re.sub(r"\s*\[[A-Z0-9]+\]\s*", " ", evidence).strip()
    evidence = evidence.rstrip(". ") + f" [{paper_id}]."
    return {
        "schema_version": "1.0",
        "sentence_id": sentence_id,
        "paper_id": paper_id,
        "text": evidence,
        "citation_ids": [paper_id],
        "final_claim_ids": [row["claim_id"]],
        "final_claim_hashes": [row.get("final_claim_hash") or _canonical_hash(claim)],
        "final_dispositions": [row["final_disposition"]],
    }


def _build_revision(selected: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    sentence_rows = []
    sequence = 1
    paragraphs = []
    for paper_id in PAPER_ORDER:
        paper_sentences = []
        for row in selected:
            if row["final_claim"]["paper_id"] != paper_id:
                continue
            sentence = _grounded_sentence(row, f"P8B-S{sequence:03d}")
            sequence += 1
            sentence_rows.append(sentence)
            paper_sentences.append(sentence["text"])
        paragraphs.append(" ".join(paper_sentences))
    revision = "\n".join([f"## {SECTION_TITLE}", "", *sum(([paragraph, ""] for paragraph in paragraphs), [])])
    return revision, sentence_rows


def _build_before_section(phase7_claims: list[dict[str, Any]]) -> str:
    lines = [f"## {SECTION_TITLE}", ""]
    for row in phase7_claims:
        lines.extend([row["claim_text"].strip(), ""])
    return "\n".join(lines)


def _assess_phase7_sentences(
    phase7_claims: list[dict[str, Any]],
    final_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_paper = {
        paper_id: [row["claim_id"] for row in final_rows if row["final_claim"]["paper_id"] == paper_id]
        for paper_id in PAPER_ORDER
    }
    assessments = []
    for row in phase7_claims:
        citations = row.get("citation_ids", [])
        assessments.append(
            {
                "schema_version": "1.0",
                "phase7_claim_id": row["claim_id"],
                "phase7_sentence_id": row["sentence_id"],
                "phase7_claim_hash": row.get("claim_hash") or _canonical_hash(row),
                "citation_ids": citations,
                "assessment": "REVISE_WITH_PHASE8A_EVIDENCE" if citations else "REMOVE_UNSUPPORTED_META_NARRATION",
                "reason_code": "PHASE8A_FINAL_CLAIMS_AVAILABLE" if citations else "NO_SENTENCE_LEVEL_SCIENTIFIC_CITATION",
                "candidate_final_claim_ids": sorted(
                    {claim_id for citation in citations for claim_id in by_paper[citation]}
                ),
            }
        )
    return assessments


def _claim_mapping(
    final_rows: list[dict[str, Any]],
    sentence_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    sentence_by_claim = {
        claim_id: sentence["sentence_id"]
        for sentence in sentence_rows
        for claim_id in sentence["final_claim_ids"]
    }
    mappings = []
    for row in final_rows:
        claim = row["final_claim"]
        conflict = row["final_disposition"] == "SOURCE_CONFLICT_RETAINED"
        used = row["claim_id"] in sentence_by_claim
        if conflict:
            status = "SOURCE_CONFLICT_RETAINED_NOT_ASSERTED"
        elif used:
            status = "USED_IN_GROUNDED_REVISION"
        else:
            status = "AVAILABLE_NOT_SELECTED_IN_VERTICAL_SLICE"
        mappings.append(
            {
                "schema_version": "1.0",
                "claim_id": row["claim_id"],
                "paper_id": claim["paper_id"],
                "source_document_id": claim["source_document_id"],
                "claim_type": claim["claim_type"],
                "final_disposition": row["final_disposition"],
                "integration_status": status,
                "revised_sentence_ids": [sentence_by_claim[row["claim_id"]]] if used else [],
            }
        )
    return mappings


def _remaining_attention(final_rows: list[dict[str, Any]]) -> dict[str, Any]:
    items = []
    for row in final_rows:
        if row["final_disposition"] != "SOURCE_CONFLICT_RETAINED":
            continue
        claim = row["final_claim"]
        conflict = claim["source_conflict"]
        items.append(
            {
                "claim_id": row["claim_id"],
                "paper_id": claim["paper_id"],
                "source_document_id": claim["source_document_id"],
                "status": "SOURCE_CONFLICT_RETAINED",
                "conflict_type": conflict.get("conflict_type"),
                "alternatives": conflict.get("alternatives", []),
                "vertical_slice_action": "NOT_ASSERTED_AS_SINGLE_FACT",
            }
        )
    return {
        "schema_version": "1.0",
        "item_count": len(items),
        "items": items,
        "human_budget_remaining": 0,
        "additional_human_decisions_created": False,
        "handling": "Retain structured conflicts outside revised prose; do not select a winner.",
    }


def _write_hash_manifest(root: Path) -> None:
    paths = sorted(path for path in root.rglob("*") if path.is_file() and path.name != "HASH_MANIFEST.sha256")
    atomic_write_text(
        root / "HASH_MANIFEST.sha256",
        "\n".join(f"{sha256_file(path)}  {path.relative_to(root).as_posix()}" for path in paths) + "\n",
    )


def prepare_grounded_vertical_slice(
    *,
    repo_root: Path,
    output_parent: Path,
    run_id: str,
    final_claims_path: Path,
    closure_manifest_path: Path,
    phase7_claims_path: Path,
    expected_final_claims_sha256: str,
    expected_closure_manifest_sha256: str,
    expected_phase7_claims_sha256: str,
    repo_head: str,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output_parent = output_parent.resolve()
    final_claims_path = final_claims_path.resolve()
    closure_manifest_path = closure_manifest_path.resolve()
    phase7_claims_path = phase7_claims_path.resolve()
    if not RUN_ID_RE.fullmatch(run_id):
        raise ValueError("invalid Phase 8B vertical-slice run ID")
    if _is_within(output_parent, repo_root):
        raise ValueError("Phase 8B scientific output must remain outside the Git repository")
    run_root = output_parent / run_id
    if run_root.exists():
        raise FileExistsError(f"Phase 8B vertical-slice run already exists: {run_root}")
    input_hashes = {
        "final_claims": _verify_hash(final_claims_path, expected_final_claims_sha256, "final claims"),
        "closure_manifest": _verify_hash(closure_manifest_path, expected_closure_manifest_sha256, "closure manifest"),
        "phase7_claims": _verify_hash(phase7_claims_path, expected_phase7_claims_sha256, "Phase 7 claims"),
    }
    final_rows = _read_jsonl(final_claims_path)
    _validate_final_claims(final_rows)
    phase7_claims = _validate_phase7_claims(_read_json(phase7_claims_path))
    selected = _select_claims(final_rows)
    revision, revised_sentences = _build_revision(selected)
    before = _build_before_section(phase7_claims)
    assessments = _assess_phase7_sentences(phase7_claims, final_rows)
    mappings = _claim_mapping(final_rows, revised_sentences)
    attention = _remaining_attention(final_rows)
    if len(mappings) != EXPECTED_FINAL_CLAIM_COUNT or attention["item_count"] != EXPECTED_CONFLICT_COUNT:
        raise RuntimeError("Phase 8B claim accounting is incomplete")

    temporary = output_parent / f".{run_id}.tmp-{os.getpid()}"
    if temporary.exists():
        raise FileExistsError(f"temporary Phase 8B run already exists: {temporary}")
    for relative in ("revision", "mapping", "reports", "coordinator"):
        (temporary / relative).mkdir(parents=True, exist_ok=True)
    atomic_write_text(temporary / "revision/before_section.md", before)
    atomic_write_text(temporary / "revision/grounded_revision.md", revision)
    diff = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            revision.splitlines(keepends=True),
            fromfile="phase7_before.md",
            tofile="phase8b_grounded_revision.md",
        )
    )
    atomic_write_text(temporary / "revision/revision.diff", diff)
    atomic_write_jsonl(temporary / "mapping/phase7_sentence_assessment.jsonl", assessments)
    atomic_write_jsonl(temporary / "mapping/revised_sentences.jsonl", revised_sentences)
    atomic_write_jsonl(temporary / "mapping/claim_to_sentence_map.jsonl", mappings)
    atomic_write_json(temporary / "reports/remaining_human_attention.json", attention)
    attention_lines = [
        "# Remaining Human Attention",
        "",
        "Human budget remaining: `0`. No additional human decision was created.",
        "",
    ]
    attention_lines.extend(
        f"- `{row['claim_id']}`: `{row['conflict_type']}`; retained and not asserted as a single fact"
        for row in attention["items"]
    )
    atomic_write_text(temporary / "reports/remaining_human_attention.md", "\n".join(attention_lines) + "\n")

    integration_counts = dict(Counter(row["integration_status"] for row in mappings))
    summary = {
        "schema_version": "1.0",
        "status": "PASS",
        "stage": "PHASE8B_GROUNDED_REVISION_VERTICAL_SLICE_COMPLETE",
        "method_label": METHOD_LABEL,
        "section_count": 1,
        "section_title": SECTION_TITLE,
        "phase7_sentence_count": len(phase7_claims),
        "phase7_sentence_assessment_count": len(assessments),
        "final_claim_count": len(final_rows),
        "usable_non_conflict_claim_count": sum(row["final_disposition"] != "SOURCE_CONFLICT_RETAINED" for row in final_rows),
        "retained_source_conflict_count": attention["item_count"],
        "selected_claim_count": len(selected),
        "revised_sentence_count": len(revised_sentences),
        "claim_accounting_count": len(mappings),
        "claim_accounting_rate": 1.0,
        "integration_status_counts": integration_counts,
        "human_budget_remaining": 0,
        "additional_human_decisions_created": False,
        "network_used": False,
    }
    atomic_write_json(temporary / "reports/vertical_slice_summary.json", summary)
    summary_lines = [
        "# Phase 8B Grounded Revision Vertical Slice",
        "",
        f"- status: `{summary['status']}`",
        f"- stage: `{summary['stage']}`",
        f"- section count: `{summary['section_count']}`",
        f"- Phase 7 sentences assessed: `{len(assessments)}`",
        f"- final claims accounted: `{len(mappings)}/44`",
        f"- claims used in revision: `{len(selected)}`",
        f"- retained conflicts not asserted: `{attention['item_count']}`",
        "- network used: `false`",
        "- additional human decisions: `false`",
        "",
    ]
    atomic_write_text(temporary / "reports/vertical_slice_summary.md", "\n".join(summary_lines))

    if {
        "final_claims": sha256_file(final_claims_path),
        "closure_manifest": sha256_file(closure_manifest_path),
        "phase7_claims": sha256_file(phase7_claims_path),
    } != input_hashes:
        raise RuntimeError("Phase 8A or Phase 7 input changed during vertical-slice preparation")
    manifest = {
        "schema_version": "1.0",
        "run_id": run_id,
        "stage": summary["stage"],
        "repo_head": repo_head,
        "input_hashes": input_hashes,
        "section_count": 1,
        "final_claim_count": len(final_rows),
        "claim_accounting_count": len(mappings),
        "retained_source_conflict_count": attention["item_count"],
        "human_budget_remaining": 0,
        "additional_human_decisions_created": False,
        "network_used": False,
    }
    atomic_write_json(temporary / "coordinator/run_manifest.json", manifest)
    atomic_write_text(
        temporary / "coordinator/COORDINATOR_RESUME.md",
        "\n".join(
            [
                "# Phase 8B Grounded Revision Resume",
                "",
                f"- stage: `{summary['stage']}`",
                "- scope: one representative section vertical slice",
                f"- final claims accounted: `{len(mappings)}/44`",
                f"- source conflicts retained outside prose: `{attention['item_count']}`",
                "- next step: review the revision and mapping before expanding beyond one section",
                "",
            ]
        ),
    )
    serialized = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in temporary.rglob("*")
        if path.is_file()
    ).casefold()
    for forbidden in ("/home/", "chain_of_thought", "fully_verified"):
        if forbidden in serialized:
            raise ValueError(f"forbidden Phase 8B output token: {forbidden}")
    _write_hash_manifest(temporary)
    output_parent.mkdir(parents=True, exist_ok=True)
    os.replace(temporary, run_root)
    result = {
        **manifest,
        "run_root": str(run_root),
        "hash_manifest_sha256": sha256_file(run_root / "HASH_MANIFEST.sha256"),
        "selected_claim_count": len(selected),
    }
    return result
