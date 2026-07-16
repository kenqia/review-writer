from __future__ import annotations

import csv
import difflib
import hashlib
import html
import json
import re
import shutil
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from review_writer.phase8.ai_adjudication import atomic_write_json, atomic_write_jsonl, atomic_write_text, sha256_file
from review_writer.phase8.phase8b_grounded_revision_v2 import _chemical_tokens, _claim_text, _numeric_signature, _numeric_tokens, _supported_numeric_tokens


CONTINUOUS_MODE = "continuous_finished_review"
DEFAULT_MODE = "checkpointed"
METHOD_LABEL = "HUMAN_SPOT_CHECKED_EVIDENCE_GROUNDED_WORKING_DRAFT"
STAGE_READY = "HUMAN_FULL_TEXT_REVIEW_REQUIRED"
TITLE = "Palladium-Centered Strategies for Asymmetric Allene Synthesis: Selectivity Control, Substrate Constraints, and Mechanistic Evidence"
QODERWORK_PROMPT = """使用本项目已验证的 Phase 8A final claims，
连续生成第一份完整英文迷你综述成品。

不要在中间 checkpoint 停止。
仅在真正的科学、引用、provider 或文件 blocker 出现时停止。

输出 Markdown、ACS-style DOCX、证据表、冲突报告、
句子到 claim 映射、质量报告和运行清单。"""
EXPECTED_FINAL_CLAIMS_SHA256 = "c2aae9212fe798f94e1aca3637d6c7ee24e0f6980c89c9c1e6fc870045c80352"
EXPECTED_CLOSURE_MANIFEST_SHA256 = "cef91cc2b48fc40f20275e6db1d258d5adae3a295016d52893c2230d81d3a3cd"
CONFLICT_DISPOSITION = "SOURCE_CONFLICT_RETAINED"
REQUIRED_HEADINGS = [
    "1. Scope and Source Selection",
    "2. Catalyst and Ligand Control of Selectivity",
    "3. Substrate Architecture and Reaction Boundaries",
    "4. Mechanistic Evidence: Dynamic Intermediates, Coordination, and Competing Models",
    "5. Transferable Design Principles and Limitations",
    "6. Conclusions",
]
TABLE_FIELDS = [
    "source_study",
    "evidence_role",
    "catalytic_or_reaction_strategy",
    "representative_transformation",
    "key_supported_outcome",
    "mechanistic_or_control_evidence",
    "evidence_limitation_warning",
]
DESIGN_TABLE_FIELDS = [
    "design_lever",
    "direct_observation",
    "substrate_boundary",
    "mechanistic_evidence",
    "practical_implication",
]
FACTUAL_SENTENCE_ROLES = {
    "fact",
    "direct_result",
    "experimental_observation",
    "intermediate_isolation",
    "author_proposal",
    "review_context",
}
REQUIRED_OUTPUTS = (
    "final_review.md",
    "final_review.docx",
    "comparison_evidence_table.csv",
    "comparison_evidence_table.xlsx",
    "design_principles_table.csv",
    "full_evidence_claim_table.csv",
    "full_evidence_claim_table.xlsx",
    "conflict_report.md",
    "sentence_claim_map.jsonl",
    "quality_report.md",
    "quality_report.json",
    "generation_manifest.json",
    "run_manifest.json",
    "qoderwork_run_record.md",
    "CHANGE_SUMMARY.md",
    "TEXT_DIFF_FROM_CONTINUOUSZ.md",
    "baseline_provenance.json",
)
CURATED_PROVENANCE_CONTRACT = {
    "current_run_model_requests": 0,
    "authoring_mode": "codex_exec_curated_revision",
    "authoring_agent_model": "gpt-5.6-terra",
    "final_text_origin": "CURATED_FROM_FROZEN_FINAL_CLAIMS_NO_EXTERNAL_PROVIDER_CALL",
    "reused_upstream_generation_payload": False,
}
PROMPT_LEAKAGE_RE = re.compile(
    r"\b(?:system prompt|developer message|workflow instructions|chain-of-thought|phase\s*8|qoderwork|"
    r"claim(?:s)?|audit|closed supporting record|working synthesis|human revision instructions?)\b",
    re.I,
)
MODEL_CLAIM_FIELDS = (
    "claim_id",
    "paper_id",
    "source_document_id",
    "source_role",
    "claim_type",
    "reaction_stage",
    "reaction_entry",
    "substrate_ids",
    "reagent_or_partner_ids",
    "product_id",
    "conditions_as_reported",
    "metric_type",
    "value_as_reported",
    "unit_as_reported",
    "short_evidence",
    "epistemic_class",
    "pathway_status",
)


def delivery_stops_at_checkpoint(mode: str, blockers: list[dict[str, Any]]) -> bool:
    if mode not in {DEFAULT_MODE, CONTINUOUS_MODE}:
        raise ValueError(f"unsupported delivery mode: {mode}")
    return bool(blockers) or mode != CONTINUOUS_MODE


def verify_frozen_inputs(claims_path: Path, manifest_path: Path, expected_claims_hash: str, expected_manifest_hash: str) -> dict[str, str]:
    if not claims_path.is_file() or sha256_file(claims_path) != expected_claims_hash:
        raise ValueError("final claims hash mismatch")
    if not manifest_path.is_file() or sha256_file(manifest_path) != expected_manifest_hash:
        raise ValueError("closure manifest hash mismatch")
    return {"final_claims_sha256": expected_claims_hash, "closure_manifest_sha256": expected_manifest_hash}


def _claim_rows(final_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if len(final_rows) != 44 or len({row.get("claim_id") for row in final_rows}) != 44:
        raise ValueError("finished review requires 44 unique closure records")
    conflicts = [row for row in final_rows if row.get("final_disposition") == CONFLICT_DISPOSITION]
    available = [row for row in final_rows if row.get("final_disposition") != CONFLICT_DISPOSITION]
    if len(available) != 37 or len(conflicts) != 7:
        raise ValueError("finished review requires 37 non-conflict and seven conflict records")
    return available, conflicts


def _duplicate_rank(row: dict[str, Any]) -> tuple[int, str]:
    claim_type = row["final_claim"].get("claim_type")
    return ({"optimization_result": 0, "target_reaction_numeric_outcome": 1}.get(claim_type, 2), row["claim_id"])


def build_finished_review_plan(final_rows: list[dict[str, Any]]) -> dict[str, Any]:
    available, conflicts = _claim_rows(final_rows)
    candidates = [row["claim_id"] for row in available]
    by_id = {row["claim_id"]: row for row in available}

    def ids(paper: str, claim_types: set[str] | None = None) -> list[str]:
        return [
            claim_id
            for claim_id in candidates
            if by_id[claim_id]["final_claim"].get("paper_id") == paper
            and (claim_types is None or by_id[claim_id]["final_claim"].get("claim_type") in claim_types)
        ]

    mechanism_types = {"author_proposed_mechanism", "experimental_mechanistic_observation", "intermediate_isolation_result", "stoichiometric_result"}
    paragraph_plan = [
        {"section": "1. Scope and Source Selection", "paragraph_purpose": "Use one broad review for context and two palladium primary studies for direct comparison.", "candidate_claim_ids": candidates, "source_paper_ids": ["F3I", "F47A", "P403"]},
        {"section": "2. Catalyst and Ligand Control of Selectivity", "paragraph_purpose": "Compare catalyst, ligand, and dynamic-intermediate controls across the palladium studies.", "candidate_claim_ids": ids("F3I") + ids("F47A") + ids("P403", {"optimization_result"}), "source_paper_ids": ["F3I", "F47A", "P403"]},
        {"section": "3. Substrate Architecture and Reaction Boundaries", "paragraph_purpose": "Connect substrate design to direct scope failures without using preparation yields as reaction outcomes.", "candidate_claim_ids": ids("F3I", {"explicit_limitation", "scope_result"}) + ids("P403", {"negative_scope", "experimental_mechanistic_observation"}), "source_paper_ids": ["F3I", "P403"]},
        {"section": "4. Mechanistic Evidence: Dynamic Intermediates, Coordination, and Competing Models", "paragraph_purpose": "Separate observations, isolated intermediates, stoichiometric tests, and author proposals.", "candidate_claim_ids": [claim_id for claim_id in candidates if by_id[claim_id]["final_claim"].get("claim_type") in mechanism_types], "source_paper_ids": ["F3I", "F47A", "P403"]},
        {"section": "5. Transferable Design Principles and Limitations", "paragraph_purpose": "Derive cross-study design implications while keeping unlike reactions non-comparable.", "candidate_claim_ids": candidates, "source_paper_ids": ["F3I", "F47A", "P403"]},
        {"section": "6. Conclusions", "paragraph_purpose": "Conclude on palladium-centered selectivity control and remaining substrate and mechanistic limits.", "candidate_claim_ids": candidates, "source_paper_ids": ["F3I", "F47A", "P403"]},
    ]
    table_mapping = [
        {"source_paper_id": paper, "candidate_claim_ids": ids(paper), "warning": "Review context only" if paper == "F3I" else "Preserve primary-study conditions and epistemic class"}
        for paper in ("F3I", "F47A", "P403")
    ]
    accounting = []
    for row in final_rows:
        if row.get("final_disposition") == CONFLICT_DISPOSITION:
            status, reason = "SOURCE_CONFLICT_EXCLUDED", "RETAINED_OUTSIDE_PROSE"
        else:
            status, reason = "CANDIDATE", "AVAILABLE_FOR_PRODUCT_QUALITY_SELECTION"
        accounting.append({"claim_id": row["claim_id"], "paper_id": row["final_claim"].get("paper_id"), "plan_status": status, "reason_code": reason})
    return {
        "schema_version": "finished-review-1.0",
        "title": TITLE,
        "available_non_conflict_claim_count": len(available),
        "retained_conflict_count": len(conflicts),
        "candidate_claim_ids": candidates,
        "candidate_claim_count": len(candidates),
        "paragraph_plan": paragraph_plan,
        "comparison_table_mapping": table_mapping,
        "claim_accounting": accounting,
    }


def build_qwen_generation_request(
    final_rows: list[dict[str, Any]],
    evidence_plan: dict[str, Any],
    bibliography_metadata: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Build the closed scientific context sent to Qwen, excluding private review data."""
    available, _conflicts = _claim_rows(final_rows)
    candidates = set(evidence_plan["candidate_claim_ids"])
    claims = [
        {field: row["final_claim"].get(field) for field in MODEL_CLAIM_FIELDS}
        for row in available
        if row["claim_id"] in candidates
    ]
    model_plan = {
        "title": evidence_plan["title"],
        "candidate_claim_ids": evidence_plan["candidate_claim_ids"],
        "paragraph_plan": evidence_plan["paragraph_plan"],
        "comparison_table_mapping": evidence_plan["comparison_table_mapping"],
        "selection_note": "All 37 non-conflict records are candidates. Select only those needed for the thematic manuscript and account for every omission; conflict records are outside this context.",
    }
    return {
        "task": "write_complete_bounded_evidence_grounded_mini_review",
        "delivery_mode": CONTINUOUS_MODE,
        "title": TITLE,
        "language": "English",
        "prose_word_range": [2000, 2400],
        "method_boundary": "representative source selection; one review for context and two palladium primary studies for comparison",
        "required_headings": REQUIRED_HEADINGS,
        "claims": claims,
        "evidence_plan": model_plan,
        "bibliography_metadata": bibliography_metadata,
        "citation_contract": "Do not write citation markers. For each fact sentence, return source_paper_ids; the coordinator adds numeric citations in first-appearance order.",
        "sentence_contract": {
            "fact": "Every scientific sentence must use a precise factual role and cite one or more supporting_claim_ids whose content fully supports that sentence.",
            "transition": "A transition sentence may have no claims but must introduce no scientific number, entity, condition, mechanism, or result.",
            "reviewer_synthesis": "A cross-study interpretation must use sentence_role=reviewer_synthesis and bind at least two non-conflict claims from at least two source papers.",
            "review_source": "Every review_context sentence supported by F3I must explicitly say review, survey, overview, or synthesis.",
        },
        "scientific_boundaries": [
            "Use only the supplied claims; do not add facts from memory.",
            "Do not use claim IDs absent from the supplied claims.",
            "Do not bind the omitted 76% result to DBA-present conditions.",
            "Treat author-proposed mechanisms as proposals, never experimental proof.",
            "Do not claim that intermediate isolation proves a catalytic pathway.",
            "Do not rank outcomes obtained under non-comparable conditions.",
            "Do not mention workflow, prompts, model behavior, phases, or internal claim IDs in sentence text.",
            "Create one original comparison table and support every row with supplied claims.",
        ],
        "output_schema": {
            "title": TITLE,
            "abstract_sentences": [
                {
                    "sentence_id": "A1",
                    "sentence_role": "direct_result|experimental_observation|intermediate_isolation|author_proposal|review_context|reviewer_synthesis|transition",
                    "text": "English sentence without citation marker",
                    "supporting_claim_ids": ["claim ID"],
                    "source_paper_ids": ["F3I|F47A|P403"],
                    "evidence_role": "short controlled description",
                }
            ],
            "keywords": ["at least three keywords"],
            "sections": [
                {
                    "heading": "one exact required heading",
                    "paragraphs": [
                        {
                            "paragraph_id": "P1",
                            "purpose": "brief purpose",
                            "sentences": ["same sentence object schema as abstract_sentences"],
                        }
                    ],
                }
            ],
            "comparison_table": [
                {**{field: "supported plain text" for field in TABLE_FIELDS}, "supporting_claim_ids": ["claim ID"]}
            ],
        },
    }


def _parse_model_payload(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    payload = json.loads(text)
    if isinstance(payload, dict) and isinstance(payload.get("review"), dict):
        payload = payload["review"]
    if not isinstance(payload, dict):
        raise ValueError("Qwen response is not a JSON object")
    return payload


def _normalize_model_payload(payload: dict[str, Any], final_rows: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = json.loads(json.dumps(payload))
    available, _conflicts = _claim_rows(final_rows)
    available_ids = {row["claim_id"] for row in available}
    selected = {
        claim_id
        for sentence in _sentences(normalized)
        if sentence.get("sentence_role") in FACTUAL_SENTENCE_ROLES | {"reviewer_synthesis"}
        for claim_id in sentence.get("supporting_claim_ids") or []
        if claim_id in available_ids
    }
    normalized["selected_claim_ids"] = sorted(selected)
    normalized["intentionally_omitted_claim_ids"] = sorted(available_ids - selected)
    return normalized


def generate_finished_review_with_bounded_repair(
    provider: Any,
    final_rows: list[dict[str, Any]],
    evidence_plan: dict[str, Any],
    bibliography_metadata: dict[str, dict[str, Any]],
    *,
    min_words: int = 1500,
    max_words: int = 2500,
) -> dict[str, Any]:
    request = build_qwen_generation_request(final_rows, evidence_plan, bibliography_metadata)
    attempts: list[dict[str, Any]] = []
    payload: dict[str, Any] | None = None
    validation: dict[str, Any] | None = None
    for attempt_number in (1, 2):
        current_request = request
        if attempt_number == 2:
            current_request = {
                "kind": "repair",
                "task": "repair_only_the_reported_blockers",
                "original_contract": request,
                "previous_payload": payload,
                "validator_blockers": validation["blockers"] if validation else [],
                "instruction": "Return the complete corrected JSON object. Preserve supported content and do not add claims.",
            }
        response = provider.generate(current_request)
        metadata = response.get("metadata") or {}
        attempts.append(
            {
                "attempt": attempt_number,
                "status": response.get("status"),
                "model": metadata.get("model"),
                "region": metadata.get("region"),
                "usage": metadata.get("stream_telemetry") or metadata.get("usage") or {},
                "warnings": response.get("warnings") or [],
            }
        )
        if response.get("status") != "ok" or not response.get("content"):
            raise RuntimeError(f"Qwen request {attempt_number} failed: {response.get('status')}")
        payload = _normalize_model_payload(_parse_model_payload(response["content"]), final_rows)
        validation = validate_finished_review_payload(
            payload,
            final_rows,
            bibliography_metadata,
            min_words=min_words,
            max_words=max_words,
        )
        if not validation["blockers"]:
            break
    if payload is None or validation is None:
        raise RuntimeError("Qwen produced no review payload")
    return {
        "payload": payload,
        "validation": validation,
        "request_count": len(attempts),
        "repair_used": len(attempts) == 2,
        "attempts": attempts,
    }


def _sentences(payload: dict[str, Any]) -> list[dict[str, Any]]:
    values = list(payload.get("abstract_sentences") or [])
    for section in payload.get("sections") or []:
        for paragraph in section.get("paragraphs") or []:
            values.extend(paragraph.get("sentences") or [])
    return values


def _word_count(payload: dict[str, Any]) -> int:
    text = " ".join(str(sentence.get("text") or "") for sentence in _sentences(payload))
    return len(re.findall(r"\b[A-Za-z][A-Za-z'’-]*\b", text))


def validate_finished_review_payload(
    payload: dict[str, Any],
    final_rows: list[dict[str, Any]],
    bibliography_metadata: dict[str, dict[str, Any]],
    *,
    min_words: int = 1500,
    max_words: int = 2500,
) -> dict[str, Any]:
    available, conflicts = _claim_rows(final_rows)
    by_id = {row["claim_id"]: row for row in final_rows}
    available_ids = {row["claim_id"] for row in available}
    conflict_ids = {row["claim_id"] for row in conflicts}
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    def block(code: str, message: str, sentence_id: str | None = None) -> None:
        item = {"code": code, "message": message}
        if sentence_id:
            item["sentence_id"] = sentence_id
        blockers.append(item)

    if payload.get("title") != TITLE:
        block("TITLE_MISMATCH", "required title is missing or changed")
    headings = [section.get("heading") for section in payload.get("sections") or []]
    if headings != REQUIRED_HEADINGS:
        block(
            "REQUIRED_SECTIONS_MISMATCH",
            f"sections must exactly match the required ordered list: {REQUIRED_HEADINGS}",
        )
    if len(payload.get("keywords") or []) < 3:
        block("MISSING_KEYWORDS", "at least three keywords are required")

    sentence_ids: set[str] = set()
    support_union: set[str] = set()
    used_papers: set[str] = set()
    for sentence in _sentences(payload):
        sentence_id = str(sentence.get("sentence_id") or "")
        text = " ".join(str(sentence.get("text") or "").split())
        role = sentence.get("sentence_role")
        support_ids = sentence.get("supporting_claim_ids") or []
        source_ids = sentence.get("source_paper_ids") or []
        if not sentence_id or sentence_id in sentence_ids:
            block("INVALID_SENTENCE_ID", "sentence IDs must be unique and nonempty", sentence_id or None)
            continue
        sentence_ids.add(sentence_id)
        if not text:
            block("EMPTY_SENTENCE", "sentence text is empty", sentence_id)
            continue
        if role == "transition":
            if support_ids or source_ids:
                block("TRANSITION_HAS_SCIENTIFIC_BINDING", "transition sentences cannot carry scientific supports", sentence_id)
            continue
        if role not in FACTUAL_SENTENCE_ROLES | {"reviewer_synthesis"} or not support_ids:
            block("UNBOUND_FACT_SENTENCE", "every factual sentence requires supporting claims", sentence_id)
            continue
        support_union.update(support_ids)
        unknown = set(support_ids) - set(by_id)
        if unknown:
            block("SUPPORTING_CLAIM_NOT_FOUND", f"unknown claim IDs: {sorted(unknown)}", sentence_id)
        if set(support_ids) & conflict_ids:
            block("SOURCE_CONFLICT_LEAKAGE", "retained source conflict used as a prose fact", sentence_id)
        support_rows = [by_id[claim_id] for claim_id in support_ids if claim_id in available_ids]
        expected_papers = {row["final_claim"].get("paper_id") for row in support_rows}
        if set(source_ids) != expected_papers:
            block("WRONG_PAPER_CITATION", "source_paper_ids do not match supporting claims", sentence_id)
        if role == "reviewer_synthesis" and (len(set(support_ids)) < 2 or len(expected_papers) < 2):
            block("INVALID_REVIEWER_SYNTHESIS", "reviewer synthesis requires at least two claims from at least two source papers", sentence_id)
        if role == "reviewer_synthesis":
            material_by_paper = sentence.get("material_supporting_claim_ids_by_paper") or {}
            for paper_id in expected_papers:
                material_claim_ids = set(material_by_paper.get(paper_id) or [])
                supported_for_paper = {
                    row["claim_id"] for row in support_rows if row["final_claim"].get("paper_id") == paper_id
                }
                if not material_claim_ids or not material_claim_ids <= supported_for_paper:
                    block(
                        "IMMATERIAL_REVIEWER_SYNTHESIS_SOURCE",
                        f"reviewer synthesis must identify material support from {paper_id}",
                        sentence_id,
                    )
        claim_types = {row["final_claim"].get("claim_type") for row in support_rows}
        if role == "intermediate_isolation" and "intermediate_isolation_result" not in claim_types:
            block("SENTENCE_ROLE_EVIDENCE_MISMATCH", "intermediate isolation role requires an isolation result", sentence_id)
        if role == "author_proposal" and "author_proposed_mechanism" not in claim_types:
            block("SENTENCE_ROLE_EVIDENCE_MISMATCH", "author proposal role requires an author-proposed mechanism", sentence_id)
        if role == "experimental_observation" and not claim_types & {"experimental_mechanistic_observation", "stoichiometric_result"}:
            block("SENTENCE_ROLE_EVIDENCE_MISMATCH", "experimental observation role requires observational or stoichiometric evidence", sentence_id)
        if role == "review_context" and any(row["final_claim"].get("paper_id") != "F3I" for row in support_rows):
            block("SENTENCE_ROLE_EVIDENCE_MISMATCH", "review context role is reserved for the review source", sentence_id)
        used_papers.update(expected_papers)
        unsupported_numbers = _numeric_tokens(text) - _supported_numeric_tokens(support_rows)
        if unsupported_numbers:
            block("UNSUPPORTED_NUMERIC_CLAIM", f"unsupported numbers: {sorted(unsupported_numbers)}", sentence_id)
        support_text = " ".join(_claim_text(row) for row in support_rows).casefold()
        for token in sorted(_chemical_tokens(text)):
            if token.casefold() not in support_text and token not in {"SI", "NMR", "HPLC"}:
                block("UNSUPPORTED_CHEMICAL_ENTITY", f"unsupported entity: {token}", sentence_id)
        if "dba" in text.casefold() and "dba" not in support_text:
            block("UNSUPPORTED_DBA_BINDING", "DBA is absent from the supporting claims", sentence_id)
        if "dba" in text.casefold() and re.search(r"\b76\s*%", text):
            block("UNSUPPORTED_DBA_BINDING", "76% cannot be bound to DBA-present conditions", sentence_id)
        if role != "reviewer_synthesis" and any(row["final_claim"].get("paper_id") == "F3I" for row in support_rows) and not re.search(r"\b(review|review-level|survey|overview|synthesis)\b", text, re.I):
            block("REVIEW_LEVEL_FRAMING_MISSING", "F3I-supported facts require review-level framing", sentence_id)
        if PROMPT_LEAKAGE_RE.search(text):
            block("PROMPT_WORKFLOW_LEAKAGE", "workflow/debug text leaked into manuscript", sentence_id)

    selected = set(payload.get("selected_claim_ids") or [])
    omitted = set(payload.get("intentionally_omitted_claim_ids") or [])
    if selected != support_union:
        block("SELECTED_CLAIM_ACCOUNTING_MISMATCH", "selected claims must equal factual sentence support union")
    if selected & conflict_ids:
        block("SOURCE_CONFLICT_LEAKAGE", "selected claims include retained source conflicts")
    if selected | omitted != available_ids or selected & omitted:
        block("INCOMPLETE_CLAIM_ACCOUNTING", "selected and intentionally omitted IDs must partition all 37 non-conflict claims")

    table_rows = payload.get("comparison_table") or []
    if not table_rows:
        block("MISSING_COMPARISON_TABLE", "one original comparison table is required")
    for index, table_row in enumerate(table_rows, start=1):
        missing = [field for field in TABLE_FIELDS if not str(table_row.get(field) or "").strip()]
        if missing:
            block("INCOMPLETE_COMPARISON_TABLE_ROW", f"row {index} missing fields: {missing}")
        table_supports = set(table_row.get("supporting_claim_ids") or [])
        if not table_supports or table_supports - available_ids or table_supports & conflict_ids:
            block("INVALID_COMPARISON_TABLE_SUPPORT", f"row {index} has invalid supporting claims")

    required_bibliography_fields = {"authors", "title", "journal", "year", "volume", "issue", "pages", "doi"}
    for paper_id in sorted(used_papers):
        metadata = bibliography_metadata.get(paper_id) or {}
        missing = sorted(field for field in required_bibliography_fields if metadata.get(field) in (None, "", []))
        if missing:
            block("INCOMPLETE_REFERENCE", f"{paper_id} missing bibliography fields: {missing}")
    words = _word_count(payload)
    if words < min_words or words > max_words:
        block("WORD_COUNT_OUT_OF_RANGE", f"prose word count {words} is outside {min_words}-{max_words}")
    if set(bibliography_metadata) - used_papers:
        warnings.append({"code": "BIBLIOGRAPHY_SOURCE_NOT_USED", "paper_ids": sorted(set(bibliography_metadata) - used_papers)})
    return {
        "schema_version": "finished-review-1.0",
        "status": "PASS" if not blockers else "FAIL",
        "blocker_count": len(blockers),
        "blockers": blockers,
        "warning_count": len(warnings),
        "warnings": warnings,
        "word_count": words,
        "sentence_count": len(sentence_ids),
        "fact_sentence_count": sum(sentence.get("sentence_role") in FACTUAL_SENTENCE_ROLES for sentence in _sentences(payload)),
        "reviewer_synthesis_sentence_count": sum(sentence.get("sentence_role") == "reviewer_synthesis" for sentence in _sentences(payload)),
        "transition_sentence_count": sum(sentence.get("sentence_role") == "transition" for sentence in _sentences(payload)),
        "selected_claim_count": len(selected),
        "retained_conflict_count": len(conflicts),
    }


def _citation_order(payload: dict[str, Any], final_rows: list[dict[str, Any]], bibliography_metadata: dict[str, dict[str, Any]]) -> tuple[dict[str, int], dict[int, str]]:
    by_id = {row["claim_id"]: row for row in final_rows}
    paper_order: list[str] = []
    for sentence in _sentences(payload):
        for claim_id in sentence.get("supporting_claim_ids") or []:
            row = by_id.get(claim_id)
            paper_id = row["final_claim"].get("paper_id") if row else None
            if paper_id and paper_id not in paper_order:
                paper_order.append(paper_id)
    for paper_id in bibliography_metadata:
        if paper_id not in paper_order:
            paper_order.append(paper_id)
    by_paper = {paper_id: index for index, paper_id in enumerate(paper_order, start=1)}
    return by_paper, {value: key for key, value in by_paper.items()}


def _render_sentence(sentence: dict[str, Any], citations: dict[str, int]) -> str:
    text = " ".join(str(sentence.get("text") or "").split()).rstrip()
    if sentence.get("sentence_role") == "transition":
        return text
    markers = " ".join(f"[{citations[paper_id]}]" for paper_id in sentence.get("source_paper_ids") or [])
    return f"{text.rstrip('.')} {markers}."


def _render_reference(number: int, metadata: dict[str, Any]) -> str:
    authors = "; ".join(metadata["authors"])
    return (
        f"[{number}] {authors}. {metadata['title']}. {metadata['journal']} "
        f"{metadata['year']}, {metadata['volume']} ({metadata['issue']}), {metadata['pages']}. "
        f"DOI: {metadata['doi']}"
    )


def render_final_review(payload: dict[str, Any], final_rows: list[dict[str, Any]], bibliography_metadata: dict[str, dict[str, Any]]) -> tuple[str, dict[str, int]]:
    citations, papers_by_number = _citation_order(payload, final_rows, bibliography_metadata)
    lines = [f"# {TITLE}", "", "## Abstract", ""]
    lines.append(" ".join(_render_sentence(sentence, citations) for sentence in payload.get("abstract_sentences") or []))
    lines.extend(["", "## Keywords", "", "; ".join(payload.get("keywords") or []), ""])
    for section in payload.get("sections") or []:
        heading = section["heading"]
        lines.extend([f"## {heading}", ""])
        for paragraph in section.get("paragraphs") or []:
            lines.append(" ".join(_render_sentence(sentence, citations) for sentence in paragraph.get("sentences") or []))
            lines.append("")
        if heading == "5. Transferable Design Principles and Limitations":
            lines.extend(["Table 1. Transferable design principles for palladium-centered asymmetric allene synthesis.", ""])
            design_rows = payload.get("design_principles_table") or [
                {
                    "design_lever": row.get("catalytic_or_reaction_strategy"),
                    "direct_observation": row.get("key_supported_outcome"),
                    "substrate_boundary": row.get("representative_transformation"),
                    "mechanistic_evidence": row.get("mechanistic_or_control_evidence"),
                    "practical_implication": row.get("evidence_limitation_warning"),
                    "supporting_claim_ids": row.get("supporting_claim_ids") or [],
                }
                for row in payload.get("comparison_table") or []
            ]
            header = [field.replace("_", " ").title() for field in DESIGN_TABLE_FIELDS]
            lines.append("| " + " | ".join(header) + " |")
            lines.append("| " + " | ".join("---" for _ in header) + " |")
            by_id = {row["claim_id"]: row for row in final_rows}
            for row in design_rows:
                paper_ids = []
                for claim_id in row.get("supporting_claim_ids") or []:
                    paper_id = by_id[claim_id]["final_claim"].get("paper_id")
                    if paper_id not in paper_ids:
                        paper_ids.append(paper_id)
                values = [str(row.get(field) or "").replace("|", "\\|") for field in DESIGN_TABLE_FIELDS]
                values[0] = f"{values[0]} {' '.join(f'[{citations[p]}]' for p in paper_ids)}"
                lines.append("| " + " | ".join(values) + " |")
            lines.append("")
    lines.extend(["## References", ""])
    for number in sorted(papers_by_number):
        lines.extend([_render_reference(number, bibliography_metadata[papers_by_number[number]]), ""])
    return "\n".join(lines).rstrip() + "\n", citations


def _write_minimal_xlsx(path: Path, header: list[str], rows: list[list[str]]) -> None:
    def cell(column: int, row: int, value: str) -> str:
        letters = ""
        current = column
        while current:
            current, remainder = divmod(current - 1, 26)
            letters = chr(65 + remainder) + letters
        style = 1 if row == 1 else 2
        return f'<c r="{letters}{row}" s="{style}" t="inlineStr"><is><t>{html.escape(value)}</t></is></c>'

    sheet_rows = []
    for row_index, values in enumerate([header, *rows], start=1):
        row_attributes = ' ht="30" customHeight="1"' if row_index == 1 else ""
        cells = "".join(cell(index, row_index, str(value)) for index, value in enumerate(values, start=1))
        sheet_rows.append(f'<row r="{row_index}"{row_attributes}>{cells}</row>')
    widths = []
    for index, name in enumerate(header, start=1):
        observed = max([len(str(name)), *(len(str(row[index - 1])) for row in rows if index <= len(row))], default=len(str(name)))
        widths.append(f'<col min="{index}" max="{index}" width="{min(48, max(12, observed * 0.85)):.1f}" customWidth="1"/>')
    last_column = ""
    current = len(header)
    while current:
        current, remainder = divmod(current - 1, 26)
        last_column = chr(65 + remainder) + last_column
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        f'<cols>{"".join(widths)}</cols><sheetData>{"".join(sheet_rows)}</sheetData>'
        f'<autoFilter ref="A1:{last_column}{len(rows) + 1}"/></worksheet>'
    )
    workbook = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Evidence" sheetId="1" r:id="rId1"/></sheets></workbook>'
    relationships = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>'
    package_rels = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'
    styles = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF1F4E78"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment wrapText="1" vertical="center"/></xf><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf></cellXfs></styleSheet>'
    content_types = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>'
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", package_rels)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        archive.writestr("xl/styles.xml", styles)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)


def _render_conflicts(conflicts: list[dict[str, Any]]) -> str:
    lines = ["# Retained Source-Internal Conflicts", "", "These records remain unresolved source-internal conflicts. The review does not select a winner.", ""]
    for row in conflicts:
        claim = row["final_claim"]
        lines.extend([f"## {row['claim_id']}", "", f"- Source: `{claim.get('source_document_id')}`", f"- Conflict type: `{(claim.get('source_conflict') or {}).get('conflict_type')}`"])
        for index, alternative in enumerate((claim.get("source_conflict") or {}).get("alternatives") or [], start=1):
            lines.append(f"- Alternative {index}: `{alternative.get('reported_value')}`")
        lines.extend(["- Winner: not selected", "- Review impact: excluded from factual prose and retained as an evidence warning.", ""])
    return "\n".join(lines)


def _render_quality(report: dict[str, Any]) -> str:
    lines = ["# Finished Review Quality Report", "", f"- status: `{report['status']}`", f"- blockers: `{report['blocker_count']}`", f"- warnings: `{report['warning_count']}`", f"- prose words: `{report['word_count']}`", f"- fact sentences: `{report['fact_sentence_count']}`", f"- selected claims: `{report['selected_claim_count']}`", f"- retained conflicts outside prose: `{report['retained_conflict_count']}`", "", "## BLOCKER", ""]
    lines.extend(f"- `{item['code']}`: {item['message']}" for item in report["blockers"])
    if not report["blockers"]:
        lines.append("- none")
    lines.extend(["", "## WARNING", ""])
    lines.extend(f"- `{item['code']}`: {item}" for item in report["warnings"])
    if not report["warnings"]:
        lines.append("- none")
    lines.extend(["", "## INFO", "", f"- method: `{METHOD_LABEL}`", "- This is a bounded evidence-grounded working draft, not publication-grade validation.", ""])
    return "\n".join(lines)


def _resolved_claim_accounting(payload: dict[str, Any], final_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = set(payload.get("selected_claim_ids") or [])
    duplicate_ids: set[str] = set()
    by_signature: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for row in final_rows:
        if row.get("final_disposition") == CONFLICT_DISPOSITION:
            continue
        signature = _numeric_signature(row)
        if signature:
            by_signature.setdefault(signature, []).append(row)
    for members in by_signature.values():
        if len(members) > 1:
            duplicate_ids.update(row["claim_id"] for row in sorted(members, key=_duplicate_rank)[1:])

    accounting = []
    for row in final_rows:
        claim = row["final_claim"]
        claim_id = row["claim_id"]
        if row.get("final_disposition") == CONFLICT_DISPOSITION:
            status, accounting_status, reason = "SOURCE_CONFLICT_EXCLUDED", "retained_conflict", "RETAINED_OUTSIDE_MANUSCRIPT"
        elif claim_id in selected:
            status, accounting_status, reason = "SELECTED", "used", "USED_IN_MANUSCRIPT"
        elif claim.get("claim_type") == "substrate_preparation_numeric_outcome":
            status, accounting_status, reason = "INTENTIONALLY_OMITTED", "intentionally_omitted", "SUBSTRATE_PREPARATION_NOT_NEEDED_FOR_CONSTRAINT_ANALYSIS"
        elif claim.get("paper_id") == "F47A" and str(claim.get("value_as_reported")) == "76":
            status, accounting_status, reason = "INTENTIONALLY_OMITTED", "intentionally_omitted", "AVOID_UNSUPPORTED_DBA_CONDITION_TRANSFER"
        elif claim_id in duplicate_ids:
            status, accounting_status, reason = "INTENTIONALLY_OMITTED", "intentionally_omitted", "DUPLICATE_REPORTED_RESULT"
        else:
            status, accounting_status, reason = "INTENTIONALLY_OMITTED", "intentionally_omitted", "EDITORIAL_FOCUS"
        accounting.append(
            {
                "claim_id": claim_id,
                "paper_id": claim.get("paper_id"),
                "plan_status": status,
                "accounting_status": accounting_status,
                "reason_code": reason,
            }
        )
    return accounting


def write_failed_generation_diagnostic(
    *,
    output_root: Path,
    payload: dict[str, Any],
    final_rows: list[dict[str, Any]],
    bibliography_metadata: dict[str, dict[str, Any]],
    validation: dict[str, Any],
    generation_manifest: dict[str, Any],
) -> Path:
    """Persist a complete failed candidate before the bounded generator exits."""
    output_root = Path(output_root).resolve()
    if output_root.exists():
        raise ValueError(f"failed generation diagnostic already exists: {output_root}")
    output_root.mkdir(parents=True)
    markdown, _citations = render_final_review(payload, final_rows, bibliography_metadata)
    atomic_write_text(output_root / "candidate_review.md", markdown)
    atomic_write_json(output_root / "model_payload.json", payload)
    atomic_write_json(output_root / "validation.json", validation)
    atomic_write_json(output_root / "generation_manifest.json", generation_manifest)
    manifest_lines = [
        f"{sha256_file(path)}  {path.name}"
        for path in sorted(output_root.iterdir())
        if path.is_file() and path.name != "HASH_MANIFEST.sha256"
    ]
    atomic_write_text(output_root / "HASH_MANIFEST.sha256", "\n".join(manifest_lines) + "\n")
    return output_root


def export_qoderwork_flat_package(source_root: Path, flat_root: Path) -> dict[str, Any]:
    """Copy a closed review package into a standalone, collision-safe flat directory."""
    source_root = Path(source_root).resolve()
    flat_root = Path(flat_root).resolve()
    if not source_root.is_dir():
        raise ValueError(f"finished review package does not exist: {source_root}")
    if flat_root.exists():
        raise ValueError(f"flat QoderWork export already exists: {flat_root}")

    source_files = [
        path for path in sorted(source_root.rglob("*"))
        if path.is_file() and path.name != "HASH_MANIFEST.sha256"
    ]
    flat_root.mkdir(parents=True)
    copied_files: list[dict[str, str]] = []
    for source_path in source_files:
        relative_path = source_path.relative_to(source_root).as_posix()
        flat_name = relative_path.replace("/", "__")
        destination = flat_root / flat_name
        if destination.exists():
            raise ValueError(f"flat export filename collision: {flat_name}")
        shutil.copy2(source_path, destination)
        copied_files.append(
            {
                "source_relative_path": relative_path,
                "flat_relative_path": flat_name,
                "sha256": sha256_file(destination),
            }
        )

    atomic_write_json(
        flat_root / "flat_export_manifest.json",
        {
            "schema_version": "qoderwork-flat-export-1.0",
            "source_package": source_root.name,
            "copied_file_count": len(copied_files),
            "copied_files": copied_files,
        },
    )
    manifest_lines = [
        f"{sha256_file(path)}  {path.name}"
        for path in sorted(flat_root.iterdir())
        if path.is_file() and path.name != "HASH_MANIFEST.sha256"
    ]
    atomic_write_text(flat_root / "HASH_MANIFEST.sha256", "\n".join(manifest_lines) + "\n")
    return {"flat_root": str(flat_root), "copied_file_count": len(copied_files)}


def write_finished_review_package(
    *,
    output_root: Path,
    repository_root: Path,
    payload: dict[str, Any],
    final_rows: list[dict[str, Any]],
    bibliography_metadata: dict[str, dict[str, Any]],
    evidence_plan: dict[str, Any],
    generation_manifest: dict[str, Any],
    replay_performed: bool = False,
    replay_note: str = "QoderWork replay was not performed for this local curated revision.",
    docx_source: Path,
    docx_integrity: dict[str, Any] | None = None,
    baseline_markdown: Path | None = None,
    min_words: int = 1500,
    max_words: int = 2500,
) -> dict[str, Any]:
    output_root = Path(output_root).resolve()
    repository_root = Path(repository_root).resolve()
    if not repository_root.is_dir():
        raise ValueError(f"repository root does not exist: {repository_root}")
    if output_root.exists():
        raise ValueError(f"finished review output already exists: {output_root}")
    if baseline_markdown is None:
        raise ValueError("baseline Markdown is required for a finished package")
    baseline_path = Path(baseline_markdown).resolve()
    if not baseline_path.is_file():
        raise ValueError(f"baseline Markdown does not exist: {baseline_path}")
    try:
        baseline_source_path = baseline_path.relative_to(repository_root).as_posix()
    except ValueError as exc:
        raise ValueError("baseline Markdown must be located under the explicit repository root") from exc
    baseline_sha256 = sha256_file(baseline_path)
    report = validate_finished_review_payload(payload, final_rows, bibliography_metadata, min_words=min_words, max_words=max_words)
    if report["blockers"]:
        raise ValueError(f"finished review has blockers: {[item['code'] for item in report['blockers']]}")
    curated_markers = {
        field: expected
        for field, expected in CURATED_PROVENANCE_CONTRACT.items()
        if field != "authoring_mode" and generation_manifest.get(field) == expected
    }
    if generation_manifest.get("authoring_mode") == CURATED_PROVENANCE_CONTRACT["authoring_mode"] or curated_markers:
        wrong_values = {
            field: {"expected": expected, "actual": generation_manifest.get(field)}
            for field, expected in CURATED_PROVENANCE_CONTRACT.items()
            if generation_manifest.get(field) != expected
        }
        if wrong_values:
            raise ValueError(f"generation manifest does not satisfy curated provenance contract: {wrong_values}")
    if docx_integrity is not None and docx_integrity.get("status") != "PASS":
        raise ValueError("finished review DOCX integrity check failed")
    report["docx_integrity"] = docx_integrity or {"status": "NOT_CHECKED"}
    for directory in ("planning", "draft", "final", "citations", "evidence", "audit", "03_figure_redraw"):
        (output_root / directory).mkdir(parents=True, exist_ok=True)
    markdown, citations = render_final_review(payload, final_rows, bibliography_metadata)
    atomic_write_text(output_root / "final_review.md", markdown)
    atomic_write_text(output_root / "final/final_review.md", markdown)
    baseline_text = baseline_path.read_text(encoding="utf-8")
    diff = difflib.unified_diff(
        baseline_text.splitlines(),
        markdown.splitlines(),
        fromfile=baseline_source_path,
        tofile="product-quality-v4/final_review.md",
        lineterm="",
    )
    atomic_write_text(output_root / "TEXT_DIFF_FROM_CONTINUOUSZ.md", "\n".join(diff) + "\n")
    atomic_write_json(
        output_root / "baseline_provenance.json",
        {
            "baseline_source_repo_relative_path": baseline_source_path,
            "baseline_sha256": baseline_sha256,
        },
    )
    shutil.copy2(docx_source, output_root / "final_review.docx")
    shutil.copy2(docx_source, output_root / "final/final_review.docx")
    accounting = _resolved_claim_accounting(payload, final_rows)
    resolved_plan = {**evidence_plan, "claim_accounting": accounting}
    atomic_write_json(output_root / "planning/evidence_plan.json", resolved_plan)
    atomic_write_json(output_root / "draft/model_payload.json", payload)

    table_header = [*TABLE_FIELDS, "supporting_claim_ids"]
    table_rows = [[str(row.get(field) or "") for field in TABLE_FIELDS] + [";".join(row.get("supporting_claim_ids") or [])] for row in payload["comparison_table"]]
    with (output_root / "comparison_evidence_table.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(table_header)
        writer.writerows(table_rows)
    _write_minimal_xlsx(output_root / "comparison_evidence_table.xlsx", table_header, table_rows)
    design_rows = payload.get("design_principles_table") or [
        {
            "design_lever": row.get("catalytic_or_reaction_strategy"),
            "direct_observation": row.get("key_supported_outcome"),
            "substrate_boundary": row.get("representative_transformation"),
            "mechanistic_evidence": row.get("mechanistic_or_control_evidence"),
            "practical_implication": row.get("evidence_limitation_warning"),
            "supporting_claim_ids": row.get("supporting_claim_ids") or [],
        }
        for row in payload["comparison_table"]
    ]
    design_header = [*DESIGN_TABLE_FIELDS, "supporting_claim_ids"]
    with (output_root / "design_principles_table.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(design_header)
        writer.writerows([[str(row.get(field) or "") for field in DESIGN_TABLE_FIELDS] + [";".join(row.get("supporting_claim_ids") or [])] for row in design_rows])

    sentence_usage: dict[str, list[str]] = {}
    for sentence in _sentences(payload):
        for claim_id in sentence.get("supporting_claim_ids") or []:
            sentence_usage.setdefault(claim_id, []).append(sentence["sentence_id"])
    accounting_by_id = {row["claim_id"]: row for row in accounting}
    full_header = ["claim_id", "paper_id", "selection_status", "reason_code", "claim_type", "reaction_stage", "metric_type", "value_as_reported", "unit_as_reported", "short_evidence", "sentence_ids"]
    full_rows = []
    for row in final_rows:
        claim = row["final_claim"]
        resolved = accounting_by_id[row["claim_id"]]
        full_rows.append([
            row["claim_id"],
            str(claim.get("paper_id") or ""),
            resolved["plan_status"],
            resolved["reason_code"],
            str(claim.get("claim_type") or ""),
            str(claim.get("reaction_stage") or ""),
            str(claim.get("metric_type") or ""),
            str(claim.get("value_as_reported") if claim.get("value_as_reported") is not None else ""),
            str(claim.get("unit_as_reported") or ""),
            str(claim.get("short_evidence") or ""),
            ";".join(sentence_usage.get(row["claim_id"], [])),
        ])
    with (output_root / "full_evidence_claim_table.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(full_header)
        writer.writerows(full_rows)
    _write_minimal_xlsx(output_root / "full_evidence_claim_table.xlsx", full_header, full_rows)
    conflicts = [row for row in final_rows if row.get("final_disposition") == CONFLICT_DISPOSITION]
    atomic_write_text(output_root / "conflict_report.md", _render_conflicts(conflicts))

    sentence_records = []
    for sentence in _sentences(payload):
        sentence_records.append(
            {
                "sentence_id": sentence["sentence_id"],
                "sentence_text": _render_sentence(sentence, citations),
                "sentence_role": sentence["sentence_role"],
                "supporting_claim_ids": sentence.get("supporting_claim_ids") or [],
                "source_paper_ids": sentence.get("source_paper_ids") or [],
                "numeric_citations": [citations[paper_id] for paper_id in sentence.get("source_paper_ids") or []],
                "evidence_role": sentence.get("evidence_role"),
            }
        )
    atomic_write_jsonl(output_root / "sentence_claim_map.jsonl", sentence_records)
    atomic_write_json(output_root / "citations/citation_map.json", {str(value): key for key, value in citations.items()})
    atomic_write_json(output_root / "citations/bibliography_metadata.json", bibliography_metadata)
    atomic_write_json(output_root / "evidence/final_claim_accounting.json", accounting)
    atomic_write_json(output_root / "quality_report.json", report)
    atomic_write_text(output_root / "quality_report.md", _render_quality(report))
    atomic_write_json(output_root / "audit/quality_report.json", report)
    atomic_write_text(output_root / "audit/quality_report.md", _render_quality(report))
    atomic_write_json(output_root / "generation_manifest.json", generation_manifest)
    atomic_write_text(
        output_root / "03_figure_redraw/skip_reason.md",
        "No source-paper figures are included because this product-quality revision prioritizes prose, provenance, and a compact original design-principles table.\n",
    )
    atomic_write_text(
        output_root / "qoderwork_run_record.md",
        "# QoderWork Run Record\n\n"
        f"- replay_performed: `{str(replay_performed).lower()}`\n"
        f"- replay_note: {replay_note}\n"
        "- repository skill source: `qoderwork/skills/chem-review-orchestrator/SKILL.md`\n"
        f"- current-run model requests: `{generation_manifest['current_run_model_requests']}`\n\n"
        "## Manual QoderWork Prompt\n\n"
        f"```text\n{QODERWORK_PROMPT}\n```\n",
    )
    run_manifest = {
        "schema_version": "finished-review-1.0",
        "stage": STAGE_READY,
        "method_label": METHOD_LABEL,
        "title": TITLE,
        "word_count": report["word_count"],
        "sentence_count": report["sentence_count"],
        "selected_claim_count": report["selected_claim_count"],
        "retained_conflict_count": len(conflicts),
        "scientific_blocker_count": report["blocker_count"],
        "docx_integrity": report["docx_integrity"],
        "replay_performed": replay_performed,
        "replay_note": replay_note,
        "baseline_source_repo_relative_path": baseline_source_path,
        "baseline_sha256": baseline_sha256,
        "generation": generation_manifest,
    }
    atomic_write_json(output_root / "run_manifest.json", run_manifest)
    selected_count = sum(row["plan_status"] == "SELECTED" for row in accounting)
    omitted_count = sum(row["plan_status"] == "INTENTIONALLY_OMITTED" for row in accounting)
    atomic_write_text(
        output_root / "CHANGE_SUMMARY.md",
        "# Product-Quality Revision Summary\n\n"
        f"- Retitled and reorganized the manuscript into six chemistry-problem-driven sections.\n"
        f"- Revised prose length: {report['word_count']} words.\n"
        f"- Non-conflict accounting: {selected_count} selected, {omitted_count} intentionally omitted, 37 total candidates.\n"
        f"- Retained conflicts outside manuscript prose: {len(conflicts)}.\n"
        "- Added structured reviewer-synthesis provenance, a five-column DOCX design table, and a full XLSX claim ledger.\n"
        f"- Final product status: `{STAGE_READY}`; no acceptance decision is recorded.\n",
    )
    manifest_lines = []
    for path in sorted(output_root.rglob("*")):
        if path.is_file() and path.name != "HASH_MANIFEST.sha256":
            manifest_lines.append(f"{sha256_file(path)}  {path.relative_to(output_root).as_posix()}")
    atomic_write_text(output_root / "HASH_MANIFEST.sha256", "\n".join(manifest_lines) + "\n")
    return {**run_manifest, "output_root": str(output_root)}
