from __future__ import annotations

import difflib
import hashlib
import json
import re
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .ai_adjudication import atomic_write_json, atomic_write_jsonl, atomic_write_text, sha256_file


STAGE_READY = "PHASE8B_VERTICAL_SLICE_V2_READY_FOR_HUMAN_REVIEW"
STAGE_FAILED = "PHASE8B_VERTICAL_SLICE_V2_VALIDATION_FAILED"
METHOD_LABEL = "HUMAN_SPOT_CHECKED_AI_ADJUDICATION"
EXPECTED_FINAL_COUNT = 44
EXPECTED_NON_CONFLICT_COUNT = 37
EXPECTED_CONFLICT_COUNT = 7
CONFLICT_DISPOSITION = "SOURCE_CONFLICT_RETAINED"
FORBIDDEN_TEXT = (
    "[f3i]",
    "[f47a]",
    "[p403]",
    "publication-grade",
    "publication grade",
    "fully verified",
    "fully_verified",
    "scientifically verified",
    "scientifically_verified",
)
NUMERIC_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:\d+(?:\.\d+)?\s*:\s*\d+(?:\.\d+)?|"
    r"\d+(?:\.\d+)?\s*(?:mol\s*%|%\s*(?:ee|er|dr)?|mmol|mL|"
    r"deg\s*C|°C|h|hours?|equiv(?:alents?)?))(?![A-Za-z0-9])",
    re.IGNORECASE,
)
CHEMICAL_TOKEN_RE = re.compile(
    r"\b(?:[A-Z][a-z]?[A-Z][A-Za-z0-9]*|[A-Z][a-z]?\d[A-Za-z0-9]*|[A-Z]{2,}[A-Za-z0-9/]*)\b"
)
GENERAL_ACRONYM_ALLOWLIST = {"SI", "HPLC", "NMR"}


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _normal_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _canonical_decimal(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace("%", "")
    try:
        return format(Decimal(text).normalize(), "f")
    except (InvalidOperation, ValueError):
        return text.casefold()


def _numeric_signature(row: dict[str, Any]) -> tuple[str, ...] | None:
    claim = row["final_claim"]
    value = _canonical_decimal(claim.get("value_as_reported"))
    if value is None or claim.get("metric_type") in (None, "not_applicable"):
        return None
    return (
        str(claim.get("paper_id")),
        _normal_text(claim.get("product_id")).casefold(),
        str(claim.get("metric_type")).casefold(),
        value,
        _normal_text(claim.get("unit_as_reported")).casefold(),
    )


def _role_for_claim(claim: dict[str, Any]) -> str:
    if claim.get("paper_id") == "F3I":
        return "REVIEW_LEVEL_SUMMARY_EVIDENCE"
    claim_type = claim.get("claim_type")
    if claim_type == "optimization_result":
        return "OPTIMIZATION"
    if claim_type == "target_reaction_numeric_outcome":
        return "PRIMARY_REPORTED_RESULT" if claim.get("source_role") == "MAIN" else "CHARACTERIZATION"
    if claim_type in {"experimental_mechanistic_observation", "author_proposed_mechanism"}:
        return "MECHANISTIC_OBSERVATION"
    if claim_type == "substrate_preparation_numeric_outcome":
        return "SUBSTRATE_PREPARATION"
    return "PRIMARY_REPORTED_RESULT"


def _theme_for_claim(claim: dict[str, Any]) -> str:
    claim_type = claim.get("claim_type")
    if claim.get("paper_id") == "F3I":
        if claim_type in {"explicit_limitation", "negative_scope"}:
            return "review_landscape_and_limitations"
        if claim_type == "author_proposed_mechanism":
            return "review_level_selectivity_models"
        return "review_level_strategy_landscape"
    if claim_type in {"experimental_mechanistic_observation", "author_proposed_mechanism"}:
        return "mechanistic_interpretation_and_control"
    if claim_type in {"negative_scope", "explicit_limitation"}:
        return "scope_boundaries"
    if claim_type == "optimization_result":
        return "selectivity_and_condition_optimization"
    return "primary_asymmetric_transformation"


def _cluster_key(claim: dict[str, Any]) -> tuple[str, str]:
    product_id = _normal_text(claim.get("product_id")).casefold()
    if (
        product_id
        and claim.get("metric_type") not in (None, "not_applicable")
        and claim.get("claim_type") == "stoichiometric_result"
    ):
        return str(claim.get("paper_id")), f"numeric-product:{product_id}"
    return (
        str(claim.get("paper_id")),
        _normal_text(claim.get("reaction_entry") or claim.get("product_id") or claim.get("claim_type")).casefold(),
    )


def _duplicate_priority(row: dict[str, Any]) -> tuple[int, int, str]:
    claim = row["final_claim"]
    type_rank = {
        "optimization_result": 0,
        "target_reaction_numeric_outcome": 1,
        "stoichiometric_result": 2,
    }.get(claim.get("claim_type"), 3)
    source_rank = 0 if claim.get("source_role") == "MAIN" else 1
    return type_rank, source_rank, row["claim_id"]


def build_section_evidence_plan(final_rows: list[dict[str, Any]]) -> dict[str, Any]:
    if len(final_rows) != EXPECTED_FINAL_COUNT or len({row.get("claim_id") for row in final_rows}) != len(final_rows):
        raise ValueError("V2 evidence planning requires 44 unique final claims")
    conflicts = [row for row in final_rows if row.get("final_disposition") == CONFLICT_DISPOSITION]
    available = [row for row in final_rows if row.get("final_disposition") != CONFLICT_DISPOSITION]
    if len(available) != EXPECTED_NON_CONFLICT_COUNT or len(conflicts) != EXPECTED_CONFLICT_COUNT:
        raise ValueError("V2 evidence planning requires 37 non-conflict claims and seven retained conflicts")

    omitted: dict[str, dict[str, Any]] = {}
    duplicate_groups: list[dict[str, Any]] = []
    for row in available:
        claim = row.get("final_claim")
        if not isinstance(claim, dict) or claim.get("claim_id") != row.get("claim_id"):
            raise ValueError(f"invalid final claim binding: {row.get('claim_id')}")
        if claim.get("claim_type") == "substrate_preparation_numeric_outcome":
            omitted[row["claim_id"]] = {
                "claim_id": row["claim_id"],
                "reason_code": "OUTSIDE_REPRESENTATIVE_TARGET_REACTION_NARRATIVE",
            }
        elif row.get("final_disposition") == "HUMAN_SPOT_CHECKED_CORRECTED_ACCEPT":
            same_result_context = [
                candidate
                for candidate in available
                if candidate["claim_id"] != row["claim_id"]
                and candidate["final_claim"].get("paper_id") == claim.get("paper_id")
                and candidate["final_claim"].get("product_id") == claim.get("product_id")
                and candidate["final_claim"].get("metric_type") == claim.get("metric_type")
                and candidate["final_claim"].get("source_role") == "SI"
            ]
            if same_result_context:
                omitted[row["claim_id"]] = {
                    "claim_id": row["claim_id"],
                    "reason_code": "WEAKER_CONTEXT_THAN_EXPLICIT_SI_COMPARISON",
                    "related_claim_ids": sorted(candidate["claim_id"] for candidate in same_result_context),
                }

    by_signature: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in available:
        signature = _numeric_signature(row)
        if signature is not None:
            by_signature[signature].append(row)
    for signature, members in by_signature.items():
        if len(members) < 2:
            continue
        ordered = sorted(members, key=_duplicate_priority)
        representative = ordered[0]
        duplicate_groups.append(
            {
                "duplicate_group_id": f"DUP-{_canonical_hash(signature)[:12]}",
                "representative_claim_id": representative["claim_id"],
                "claim_ids": sorted(row["claim_id"] for row in members),
                "basis": "same paper, product, metric, reported value, and unit",
            }
        )
        for duplicate in ordered[1:]:
            omitted.setdefault(
                duplicate["claim_id"],
                {
                    "claim_id": duplicate["claim_id"],
                    "reason_code": "DUPLICATE_NUMERIC_RESULT",
                    "duplicate_of": representative["claim_id"],
                },
            )

    recommended_ids = sorted(row["claim_id"] for row in available if row["claim_id"] not in omitted)
    clusters_by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in available:
        clusters_by_key[_cluster_key(row["final_claim"])].append(row)
    evidence_clusters = []
    for (paper_id, _), members in sorted(clusters_by_key.items()):
        claim_ids = sorted(row["claim_id"] for row in members)
        selected_ids = [claim_id for claim_id in claim_ids if claim_id in recommended_ids]
        roles = sorted({_role_for_claim(row["final_claim"]) for row in members})
        themes = sorted({_theme_for_claim(row["final_claim"]) for row in members})
        evidence_clusters.append(
            {
                "cluster_id": f"EC-{_canonical_hash([paper_id, claim_ids])[:12]}",
                "paper_id": paper_id,
                "reaction_entry": members[0]["final_claim"].get("reaction_entry"),
                "claim_ids": claim_ids,
                "recommended_claim_ids": selected_ids,
                "evidence_roles": roles,
                "narrative_themes": themes,
                "selection_status": "SELECTED" if selected_ids else "OMITTED",
            }
        )

    accounting = []
    for row in final_rows:
        claim_id = row["claim_id"]
        if row["final_disposition"] == CONFLICT_DISPOSITION:
            status = "SOURCE_CONFLICT_EXCLUDED"
            reason = "SOURCE_CONFLICT_RETAINED_OUTSIDE_PROSE"
        elif claim_id in recommended_ids:
            status = "RECOMMENDED_FOR_SYNTHESIS"
            reason = "THEMATIC_EVIDENCE_PLAN_SELECTION"
        else:
            status = "AVAILABLE_NOT_SELECTED"
            reason = omitted[claim_id]["reason_code"]
        accounting.append(
            {
                "claim_id": claim_id,
                "paper_id": row["final_claim"]["paper_id"],
                "final_disposition": row["final_disposition"],
                "plan_status": status,
                "reason_code": reason,
            }
        )
    return {
        "schema_version": "2.0",
        "section_title": "Representative strategies for asymmetric allene synthesis",
        "available_non_conflict_claim_count": len(available),
        "excluded_conflict_count": len(conflicts),
        "recommended_claim_count": len(recommended_ids),
        "recommended_claim_ids": recommended_ids,
        "omitted_claims_and_reasons": [omitted[key] for key in sorted(omitted)],
        "duplicate_groups": duplicate_groups,
        "evidence_clusters": evidence_clusters,
        "claim_accounting": accounting,
        "selection_principle": "theme-and-narrative-function clustering without a fixed per-paper quota",
    }


def _issue(code: str, message: str, *, sentence_id: str | None = None) -> dict[str, Any]:
    issue = {"code": code, "message": message}
    if sentence_id:
        issue["sentence_id"] = sentence_id
    return issue


def _claim_text(row: dict[str, Any]) -> str:
    return json.dumps(row["final_claim"], ensure_ascii=False, sort_keys=True)


def _canonical_numeric_token(token: str) -> str:
    compact = re.sub(
        r"\s+",
        "",
        token.casefold().replace("°c", "degc").replace("hours", "h").replace("hour", "h"),
    )
    if ":" in compact:
        left, right = compact.split(":", maxsplit=1)
        return f"{_canonical_decimal(left)}:{_canonical_decimal(right)}"
    match = re.match(r"^(\d+(?:\.\d+)?)(.*)$", compact)
    if not match:
        return compact
    return f"{_canonical_decimal(match.group(1))}{match.group(2)}"


def _numeric_tokens(text: str) -> set[str]:
    without_citations = re.sub(r"\[\d+(?:\s*,\s*\d+)*\]", "", text)
    return {_canonical_numeric_token(match.group(0)) for match in NUMERIC_RE.finditer(without_citations)}


def _supported_numeric_tokens(rows: list[dict[str, Any]]) -> set[str]:
    tokens: set[str] = set()
    for row in rows:
        claim = row["final_claim"]
        tokens.update(_numeric_tokens(_claim_text(row)))
        value = claim.get("value_as_reported")
        unit = claim.get("unit_as_reported")
        if value is not None and unit:
            tokens.add(_canonical_numeric_token(f"{value}{unit}"))
    return tokens


def _chemical_tokens(text: str) -> set[str]:
    return {token for token in CHEMICAL_TOKEN_RE.findall(text) if token not in GENERAL_ACRONYM_ALLOWLIST}


def _citation_ids_in_text(text: str) -> set[int]:
    ids: set[int] = set()
    for group in re.findall(r"\[(\d+(?:\s*,\s*\d+)*)\]", text):
        ids.update(int(value.strip()) for value in group.split(","))
    return ids


def validate_prose_payload(
    payload: dict[str, Any],
    final_rows: list[dict[str, Any]],
    evidence_plan: dict[str, Any],
    citation_metadata: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    row_by_id = {row["claim_id"]: row for row in final_rows}
    conflict_ids = {
        row["claim_id"] for row in final_rows if row.get("final_disposition") == CONFLICT_DISPOSITION
    }
    allowed_ids = set(row_by_id) - conflict_ids
    selected = payload.get("selected_claim_ids")
    sentences = payload.get("sentences")
    paragraphs = payload.get("paragraphs")
    citation_order = payload.get("citation_order")
    omitted = payload.get("omitted_claims_and_reasons")
    if not isinstance(selected, list) or len(selected) != len(set(selected)):
        issues.append(_issue("INVALID_SELECTED_CLAIMS", "selected_claim_ids must be a unique list"))
        selected = []
    if not isinstance(sentences, list) or not sentences:
        issues.append(_issue("INVALID_SENTENCES", "sentences must be a nonempty list"))
        sentences = []
    if not isinstance(paragraphs, list) or not paragraphs:
        issues.append(_issue("INVALID_PARAGRAPHS", "paragraphs must be a nonempty list"))
        paragraphs = []
    if not isinstance(citation_order, list):
        issues.append(_issue("INVALID_CITATION_ORDER", "citation_order must be a list"))
        citation_order = []
    if not isinstance(omitted, list):
        issues.append(_issue("INVALID_OMITTED_CLAIMS", "omitted_claims_and_reasons must be a list"))
        omitted = []

    unknown_selected = set(selected) - set(row_by_id)
    if unknown_selected:
        issues.append(_issue("UNKNOWN_CLAIM_ID", f"unknown selected claim IDs: {sorted(unknown_selected)}"))
    if set(selected) & conflict_ids:
        issues.append(_issue("SOURCE_CONFLICT_IN_PROSE", "retained source-conflict claims cannot be selected"))
    if set(selected) - allowed_ids:
        issues.append(_issue("INVALID_SELECTED_CLAIMS", "selected claims must belong to the 37 non-conflict records"))
    plan_excluded_ids = {
        row.get("claim_id")
        for row in evidence_plan.get("omitted_claims_and_reasons", [])
        if isinstance(row, dict)
    }
    selected_plan_exclusions = set(selected) & plan_excluded_ids
    if selected_plan_exclusions:
        issues.append(
            _issue(
                "PLAN_EXCLUDED_CLAIM_SELECTED",
                f"evidence-plan exclusions were selected: {sorted(selected_plan_exclusions)}",
            )
        )
    omitted_ids = [row.get("claim_id") for row in omitted if isinstance(row, dict)]
    if len(omitted_ids) != len(set(omitted_ids)) or set(omitted_ids) != allowed_ids - set(selected):
        issues.append(_issue("INCOMPLETE_CLAIM_ACCOUNTING", "selected and omitted claims must partition all 37 non-conflict claims"))
    for row in omitted:
        if not isinstance(row, dict) or not row.get("reason_code"):
            issues.append(_issue("MISSING_OMISSION_REASON", "every omitted claim requires a reason_code"))

    citation_map: dict[int, str] = {}
    for item in citation_order:
        if not isinstance(item, dict) or not isinstance(item.get("citation_id"), int) or item.get("paper_id") not in citation_metadata:
            issues.append(_issue("INVALID_CITATION_ORDER", "citation_order contains an invalid entry"))
            continue
        citation_map[item["citation_id"]] = item["paper_id"]
    if sorted(citation_map) != list(range(1, len(citation_map) + 1)):
        issues.append(_issue("INVALID_CITATION_ORDER", "numeric citation IDs must be contiguous from 1"))

    sentence_ids: list[str] = []
    supported_union: set[str] = set()
    first_citation_sequence: list[int] = []
    numeric_seen: dict[tuple[str, ...], str] = {}
    for sentence in sentences:
        if not isinstance(sentence, dict):
            issues.append(_issue("INVALID_SENTENCE", "sentence entries must be objects"))
            continue
        sentence_id = sentence.get("sentence_id")
        text = _normal_text(sentence.get("text"))
        supporting_ids = sentence.get("supporting_claim_ids")
        source_papers = sentence.get("source_paper_ids")
        numeric_citations = sentence.get("numeric_citation_ids")
        bindings = sentence.get("factual_bindings")
        if not isinstance(sentence_id, str) or not sentence_id or sentence_id in sentence_ids:
            issues.append(_issue("INVALID_SENTENCE_ID", "sentence IDs must be unique nonempty strings"))
            continue
        sentence_ids.append(sentence_id)
        if not text or not isinstance(supporting_ids, list) or not supporting_ids:
            issues.append(_issue("UNBOUND_FACT_SENTENCE", "every sentence requires text and supporting claims", sentence_id=sentence_id))
            continue
        supported_union.update(supporting_ids)
        if set(supporting_ids) & conflict_ids:
            issues.append(_issue("SOURCE_CONFLICT_IN_PROSE", "a sentence cites a retained source conflict", sentence_id=sentence_id))
        if set(supporting_ids) - allowed_ids:
            issues.append(_issue("UNKNOWN_CLAIM_ID", "a sentence cites an unknown or unavailable claim", sentence_id=sentence_id))
        support_rows = [row_by_id[claim_id] for claim_id in supporting_ids if claim_id in allowed_ids]
        expected_papers = {row["final_claim"]["paper_id"] for row in support_rows}
        if not isinstance(source_papers, list) or set(source_papers) != expected_papers:
            issues.append(_issue("SOURCE_PAPER_BINDING_MISMATCH", "source_paper_ids do not match supporting claims", sentence_id=sentence_id))
        if not isinstance(numeric_citations, list) or any(not isinstance(value, int) for value in numeric_citations):
            issues.append(_issue("INVALID_NUMERIC_CITATIONS", "numeric_citation_ids must be integers", sentence_id=sentence_id))
            numeric_citations = []
        cited_papers = {citation_map.get(value) for value in numeric_citations}
        if cited_papers != expected_papers or None in cited_papers:
            issues.append(_issue("CITATION_PAPER_MISMATCH", "numeric citations do not match supporting paper IDs", sentence_id=sentence_id))
        if _citation_ids_in_text(text) != set(numeric_citations):
            issues.append(_issue("CITATION_TEXT_MISMATCH", "sentence citation markers do not match numeric_citation_ids", sentence_id=sentence_id))
        for citation_id in numeric_citations:
            if citation_id not in first_citation_sequence:
                first_citation_sequence.append(citation_id)
        unsupported_numbers = _numeric_tokens(text) - _supported_numeric_tokens(support_rows)
        if unsupported_numbers:
            issues.append(_issue("UNSUPPORTED_NUMBER", f"unsupported numeric tokens: {sorted(unsupported_numbers)}", sentence_id=sentence_id))
        support_text = " ".join(_claim_text(row) for row in support_rows).casefold()
        for token in sorted(_chemical_tokens(text)):
            if token.casefold() not in support_text:
                issues.append(_issue("UNSUPPORTED_ENTITY", f"unsupported chemical/entity token: {token}", sentence_id=sentence_id))
        if not isinstance(bindings, list) or not bindings:
            issues.append(_issue("MISSING_FACTUAL_BINDINGS", "each sentence requires factual_bindings", sentence_id=sentence_id))
        else:
            for binding in bindings:
                if not isinstance(binding, dict):
                    issues.append(_issue("INVALID_FACTUAL_BINDING", "factual binding must be an object", sentence_id=sentence_id))
                    continue
                binding_text = _normal_text(binding.get("text"))
                binding_ids = binding.get("claim_ids")
                if not binding_text or binding_text.casefold() not in text.casefold():
                    issues.append(_issue("INVALID_FACTUAL_BINDING", "binding text must occur in the sentence", sentence_id=sentence_id))
                if not isinstance(binding_ids, list) or not set(binding_ids).issubset(set(supporting_ids)):
                    issues.append(_issue("INVALID_FACTUAL_BINDING", "binding claim IDs must be sentence supports", sentence_id=sentence_id))
                    continue
                binding_source = " ".join(_claim_text(row_by_id[value]) for value in binding_ids if value in row_by_id).casefold()
                if binding_text and binding_text.casefold() not in binding_source:
                    issues.append(_issue("UNSUPPORTED_ENTITY", f"binding is absent from supporting claims: {binding_text}", sentence_id=sentence_id))
        if any(row["final_claim"].get("paper_id") == "F3I" for row in support_rows) and not re.search(
            r"\b(review|survey|overview|summar(?:y|izes|ised|ized))\b", text, re.IGNORECASE
        ):
            issues.append(_issue("REVIEW_EPISTEMIC_FRAME_MISSING", "F3I evidence must retain review-level framing", sentence_id=sentence_id))
        if "dba" in text.casefold() and "dba" not in support_text:
            issues.append(_issue("UNSUPPORTED_DBA_BINDING", "DBA is not present in the supporting claims", sentence_id=sentence_id))
        if re.search(r"\b(proves?|demonstrates? that .* causes?)\b", text, re.IGNORECASE):
            issues.append(_issue("UNSUPPORTED_CAUSAL_LANGUAGE", "causal language exceeds the structured evidence", sentence_id=sentence_id))
        for row in support_rows:
            signature = _numeric_signature(row)
            if signature is None:
                continue
            previous = numeric_seen.get(signature)
            if previous and previous != sentence_id:
                issues.append(_issue("DUPLICATE_NUMERIC_RESULT", f"numeric result already used in {previous}", sentence_id=sentence_id))
            numeric_seen[signature] = sentence_id

    if set(supported_union) != set(selected):
        issues.append(_issue("SELECTED_SUPPORT_MISMATCH", "selected_claim_ids must equal the union of sentence supports"))
    for cluster in evidence_plan.get("evidence_clusters", []):
        if not isinstance(cluster, dict):
            continue
        selected_cluster_ids = set(cluster.get("recommended_claim_ids", [])) & set(selected)
        yield_ids = {
            claim_id
            for claim_id in selected_cluster_ids
            if "yield" in str(row_by_id[claim_id]["final_claim"].get("metric_type", "")).casefold()
        }
        ee_ids = {
            claim_id
            for claim_id in selected_cluster_ids
            if row_by_id[claim_id]["final_claim"].get("metric_type") == "ee"
        }
        coreported_ids = yield_ids | ee_ids
        if yield_ids and ee_ids and not any(
            coreported_ids.issubset(set(sentence.get("supporting_claim_ids", [])))
            for sentence in sentences
            if isinstance(sentence, dict)
        ):
            issues.append(
                _issue(
                    "SPLIT_COREPORTED_METRICS",
                    f"co-reported yield and ee must share one sentence: {sorted(coreported_ids)}",
                )
            )
    paragraph_sentence_ids = [
        sentence_id
        for paragraph in paragraphs
        if isinstance(paragraph, dict)
        for sentence_id in paragraph.get("sentence_ids", [])
    ]
    if paragraph_sentence_ids != sentence_ids:
        issues.append(_issue("PARAGRAPH_SENTENCE_MISMATCH", "paragraphs must cover sentences once and in order"))
    if first_citation_sequence != list(range(1, len(first_citation_sequence) + 1)):
        issues.append(_issue("CITATION_FIRST_APPEARANCE_ORDER", "citations must be numbered by first appearance"))
    serialized = json.dumps(payload, ensure_ascii=False).casefold()
    for forbidden in FORBIDDEN_TEXT:
        if forbidden in serialized:
            issues.append(_issue("FORBIDDEN_TEXT", f"forbidden text appears: {forbidden}"))

    context_rows = [
        row
        for row in final_rows
        if row["final_claim"].get("paper_id") == "F47A"
        and _normal_text(row["final_claim"].get("product_id")).casefold() == "allene 3an"
        and row["final_claim"].get("metric_type") == "isolated_yield"
        and _canonical_decimal(row["final_claim"].get("value_as_reported")) in {"74", "76"}
    ]
    context_ids = {row["claim_id"] for row in context_rows}
    if context_ids and context_ids.issubset(set(selected)):
        explanatory = any(
            context_ids.issubset(set(sentence.get("supporting_claim_ids", [])))
            and "main text" in str(sentence.get("text", "")).casefold()
            and "si" in str(sentence.get("text", "")).casefold()
            for sentence in sentences
            if isinstance(sentence, dict)
        )
        if not explanatory:
            issues.append(
                _issue(
                    "UNEXPLAINED_MAIN_SI_RESULT_DIFFERENCE",
                    "the 76% main-text and 74% SI results require explicit source-context explanation",
                )
            )
    counts = Counter(issue["code"] for issue in issues)
    return {
        "schema_version": "2.0",
        "status": "PASS" if not issues else "FAIL",
        "issue_count": len(issues),
        "issue_code_counts": dict(sorted(counts.items())),
        "issues": issues,
        "sentence_count": len(sentences),
        "selected_claim_count": len(selected),
        "available_non_conflict_claim_count": len(allowed_ids),
        "final_claim_accounting_count": len(final_rows),
        "retained_conflict_count": len(conflict_ids),
    }


def _parse_json_content(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("model response must be a JSON object")
    return parsed


def canonicalize_model_payload(payload: dict[str, Any]) -> dict[str, Any]:
    canonical = json.loads(json.dumps(payload, ensure_ascii=False))
    citation_order = canonical.get("citation_order")
    if isinstance(citation_order, list) and all(isinstance(item, str) for item in citation_order):
        canonical["citation_order"] = [
            {"citation_id": index, "paper_id": paper_id}
            for index, paper_id in enumerate(citation_order, start=1)
        ]
    sentences = canonical.get("sentences")
    if not isinstance(sentences, list):
        sentences = []
    for sentence in sentences:
        if not isinstance(sentence, dict):
            continue
        bindings = sentence.get("factual_bindings")
        if not isinstance(bindings, list):
            continue
        normalized_bindings = []
        for binding in bindings:
            if not isinstance(binding, dict):
                normalized_bindings.append(binding)
                continue
            if {"binding_type", "bound_text_span", "claim_id"}.issubset(binding):
                normalized_bindings.append(
                    {
                        "kind": binding["binding_type"],
                        "text": binding["bound_text_span"],
                        "claim_ids": [binding["claim_id"]],
                    }
                )
            else:
                normalized_bindings.append(binding)
        sentence["factual_bindings"] = normalized_bindings
    paragraphs = canonical.get("paragraphs")
    if isinstance(paragraphs, list):
        for paragraph in paragraphs:
            if not isinstance(paragraph, dict) or isinstance(paragraph.get("sentence_ids"), list):
                continue
            paragraph_text = _normal_text(paragraph.get("text"))
            paragraph["sentence_ids"] = [
                sentence["sentence_id"]
                for sentence in sentences
                if isinstance(sentence, dict)
                and isinstance(sentence.get("sentence_id"), str)
                and _normal_text(sentence.get("text")) in paragraph_text
            ]
    return canonical


def generate_with_bounded_repair(
    provider: Any,
    request: dict[str, Any],
    final_rows: list[dict[str, Any]],
    evidence_plan: dict[str, Any],
    citation_metadata: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    attempts = []
    payload: dict[str, Any] = {}
    validation = {"status": "FAIL", "issues": [_issue("NO_RESPONSE", "no model response")], "issue_count": 1}
    current_request = request
    for attempt_number in (1, 2):
        response = provider.generate(current_request)
        attempt = {
            "attempt_number": attempt_number,
            "status": response.get("status"),
            "metadata": response.get("metadata", {}),
            "raw_content": response.get("content", ""),
        }
        attempts.append(attempt)
        provider_succeeded = response.get("status") == "ok"
        if not provider_succeeded:
            validation = {
                "status": "FAIL",
                "issue_count": 1,
                "issues": [_issue("PROVIDER_ERROR", "provider did not return a successful response")],
            }
        else:
            try:
                payload = canonicalize_model_payload(_parse_json_content(response.get("content", "")))
                validation = validate_prose_payload(payload, final_rows, evidence_plan, citation_metadata)
            except (json.JSONDecodeError, ValueError) as exc:
                validation = {
                    "status": "FAIL",
                    "issue_count": 1,
                    "issues": [_issue("INVALID_MODEL_JSON", str(exc))],
                }
        if not provider_succeeded:
            break
        if validation["status"] == "PASS":
            break
        if attempt_number == 1:
            current_request = {
                "kind": "repair",
                "original_request": request,
                "previous_output": response.get("content", ""),
                "validator_issues": validation["issues"],
                "instruction": "Return a corrected complete JSON object. Do not explain the repair.",
            }
    return {
        "payload": payload,
        "request_count": len(attempts),
        "attempts": attempts,
        "validation": validation,
    }


def build_generation_request(
    *,
    before_section: str,
    final_rows: list[dict[str, Any]],
    evidence_plan: dict[str, Any],
    citation_metadata: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    claims = [
        {"claim_id": row["claim_id"], "claim": row["final_claim"]}
        for row in final_rows
        if row["final_disposition"] != CONFLICT_DISPOSITION
    ]
    model_plan = dict(evidence_plan)
    model_plan["claim_accounting"] = [
        row for row in evidence_plan["claim_accounting"] if row["plan_status"] != "SOURCE_CONFLICT_EXCLUDED"
    ]
    return {
        "kind": "generation",
        "system": (
            "You write formal English academic review prose from a closed evidence set. "
            "Return one strict JSON object only. Never invent facts or hidden reasoning."
        ),
        "before_section": before_section,
        "final_non_conflict_claims": claims,
        "section_evidence_plan": model_plan,
        "citation_metadata": citation_metadata,
        "contract": {
            "required_keys": [
                "section_title",
                "section_outline",
                "selected_claim_ids",
                "paragraphs",
                "sentences",
                "citation_order",
                "omitted_claims_and_reasons",
            ],
            "sentence_required_keys": [
                "sentence_id",
                "text",
                "supporting_claim_ids",
                "source_paper_ids",
                "numeric_citation_ids",
                "factual_bindings",
            ],
            "paragraph_schema": {
                "required_keys": ["paragraph_id", "theme", "sentence_ids"],
                "sentence_ids": "ordered IDs from the top-level sentences array",
            },
            "factual_binding_schema": {
                "required_keys": ["kind", "text", "claim_ids"],
                "kind_values": ["chemical_entity", "catalyst", "product", "condition", "numeric_result"],
                "text": "an exact text span present in both the sentence and at least one bound claim",
            },
            "citation_schema": {
                "citation_order_entries": {"citation_id": "integer", "paper_id": "F3I | F47A | P403"},
                "rule": "Assign exactly one bibliography number per cited paper, not one number per claim.",
            },
            "writing_rules": [
                "Organize by scientific strategy, selectivity control, stereocontrol, and mechanistic relationship rather than by paper.",
                "Open with a synthesis judgment and use transitions between paragraphs.",
                "Combine yield and ee from the same reaction in one sentence.",
                "Do not repeat optimization and characterization values for the same result.",
                "Use review-level epistemic framing for every sentence supported by F3I.",
                "Do not turn observations or proposals into unsupported causation.",
                "Use numeric citations assigned by first appearance; never use paper IDs as citation markers.",
                "Exclude all source conflicts and all facts absent from the provided claims.",
                "Every sentence, including synthesis sentences, must bind at least one claim.",
                "Omitted claims must include a concise reason_code and selected plus omitted must account for all 37 claims.",
                "Never use a scientific value from an evidence-plan omitted claim, including the excluded 76% result.",
            ],
        },
    }


def _render_revision(payload: dict[str, Any]) -> str:
    by_id = {row["sentence_id"]: _normal_text(row["text"]) for row in payload["sentences"]}
    lines = [f"## {_normal_text(payload['section_title'])}", ""]
    for paragraph in payload["paragraphs"]:
        lines.extend([" ".join(by_id[sentence_id] for sentence_id in paragraph["sentence_ids"]), ""])
    return "\n".join(lines)


def _citation_outputs(
    payload: dict[str, Any], citation_metadata: dict[str, dict[str, Any]]
) -> tuple[dict[str, Any], str]:
    entries = []
    pending = False
    reference_lines = ["# References", ""]
    for order in payload["citation_order"]:
        metadata = citation_metadata[order["paper_id"]]
        complete = bool(metadata.get("authors") and metadata.get("title") and metadata.get("year") and metadata.get("journal") and metadata.get("doi"))
        pending = pending or not complete
        entry = {
            "citation_id": order["citation_id"],
            "paper_id": order["paper_id"],
            "title": metadata.get("title"),
            "authors": metadata.get("authors") or [],
            "year": metadata.get("year"),
            "journal": metadata.get("journal"),
            "doi": metadata.get("doi"),
            "metadata_status": "COMPLETE_DRAFT" if complete else "BIBLIOGRAPHY_METADATA_PENDING",
        }
        entries.append(entry)
        authors = ", ".join(entry["authors"]) if entry["authors"] else entry["paper_id"]
        doi = f" DOI: {entry['doi']}." if entry["doi"] else " BIBLIOGRAPHY_METADATA_PENDING."
        reference_lines.append(
            f"[{entry['citation_id']}] {authors}. {entry['title']}. {entry['journal']} ({entry['year']}).{doi}"
        )
    return {
        "schema_version": "2.0",
        "status": "BIBLIOGRAPHY_METADATA_PENDING" if pending else "COMPLETE_DRAFT",
        "entries": entries,
    }, "\n".join(reference_lines) + "\n"


def _write_hash_manifest(root: Path) -> str:
    paths = sorted(path for path in root.rglob("*") if path.is_file() and path.name != "HASH_MANIFEST.sha256")
    atomic_write_text(
        root / "HASH_MANIFEST.sha256",
        "\n".join(f"{sha256_file(path)}  {path.relative_to(root).as_posix()}" for path in paths) + "\n",
    )
    return sha256_file(root / "HASH_MANIFEST.sha256")


def prepare_vertical_slice_v2(
    *,
    run_root: Path,
    before_section: str,
    final_rows: list[dict[str, Any]],
    evidence_plan: dict[str, Any],
    citation_metadata: dict[str, dict[str, Any]],
    generation: dict[str, Any],
    run_manifest: dict[str, Any],
) -> dict[str, Any]:
    if run_root.exists():
        raise FileExistsError(f"V2 run already exists: {run_root}")
    validation = generation["validation"]
    payload = generation.get("payload") or {}
    stage = STAGE_READY if validation.get("status") == "PASS" else STAGE_FAILED
    for relative in ("revision", "planning", "mapping", "citations", "reports", "coordinator"):
        (run_root / relative).mkdir(parents=True, exist_ok=True)
    atomic_write_json(run_root / "planning/section_evidence_plan.json", evidence_plan)
    atomic_write_json(run_root / "reports/prose_validation.json", validation)
    for attempt_index, attempt in enumerate(generation.get("attempts", []), start=1):
        attempt_number = attempt.get("attempt_number", attempt_index)
        atomic_write_text(
            run_root / f"reports/raw_model_response_attempt_{attempt_number}.json",
            str(attempt.get("raw_content") or "") + "\n",
        )
    safe_attempts = []
    for attempt_index, attempt in enumerate(generation.get("attempts", []), start=1):
        metadata = attempt.get("metadata", {})
        telemetry = metadata.get("stream_telemetry") or metadata.get("usage") or {}
        safe_attempts.append(
            {
                "attempt_number": attempt.get("attempt_number", attempt_index),
                "status": attempt.get("status"),
                "model": metadata.get("model"),
                "region": metadata.get("region"),
                "error_type": metadata.get("error_type"),
                "endpoint": "redacted",
                "usage": {
                    "prompt_tokens": telemetry.get("prompt_tokens"),
                    "completion_tokens": telemetry.get("completion_tokens"),
                    "total_tokens": telemetry.get("total_tokens"),
                },
            }
        )
    model_manifest = {
        "schema_version": "2.0",
        "provider": "alibaba_openai_compatible",
        "model": safe_attempts[-1].get("model") if safe_attempts else None,
        "endpoint_region": safe_attempts[-1].get("region") if safe_attempts else None,
        "generation_parameters": run_manifest.get("generation_parameters", {}),
        "request_count": generation.get("request_count", 0),
        "maximum_request_count": 2,
        "capability_check": run_manifest.get("capability_check", {}),
        "attempts": safe_attempts,
        "api_key_recorded": False,
    }
    atomic_write_json(run_root / "reports/model_generation_manifest.json", model_manifest)
    if validation.get("status") == "PASS":
        revision = _render_revision(payload)
        atomic_write_text(run_root / "revision/grounded_revision_v2.md", revision)
        atomic_write_text(
            run_root / "revision/before_after_v2.diff",
            "".join(
                difflib.unified_diff(
                    before_section.splitlines(keepends=True),
                    revision.splitlines(keepends=True),
                    fromfile="phase7_before.md",
                    tofile="phase8b_grounded_revision_v2.md",
                )
            ),
        )
        atomic_write_jsonl(run_root / "mapping/sentence_claim_map_v2.jsonl", payload["sentences"])
        selected_ids = set(payload["selected_claim_ids"])
        accounting = []
        for row in evidence_plan["claim_accounting"]:
            item = dict(row)
            if row["plan_status"] == "SOURCE_CONFLICT_EXCLUDED":
                item["integration_status"] = "SOURCE_CONFLICT_RETAINED_NOT_ASSERTED"
            elif row["claim_id"] in selected_ids:
                item["integration_status"] = "USED_IN_GROUNDED_REVISION_V2"
            else:
                item["integration_status"] = "AVAILABLE_NOT_SELECTED_IN_VERTICAL_SLICE_V2"
            accounting.append(item)
        atomic_write_jsonl(run_root / "mapping/claim_accounting_v2.jsonl", accounting)
        citation_map, references = _citation_outputs(payload, citation_metadata)
        atomic_write_json(run_root / "citations/citation_map.json", citation_map)
        atomic_write_text(run_root / "citations/references.md", references)
        summary = {
            "schema_version": "2.0",
            "status": "PASS",
            "stage": stage,
            "section_count": 1,
            "paragraph_count": len(payload["paragraphs"]),
            "sentence_count": len(payload["sentences"]),
            "selected_claim_count": len(selected_ids),
            "available_non_conflict_claim_count": 37,
            "retained_conflict_count": 7,
            "final_claim_accounting_count": len(accounting),
            "sentence_mapping_count": len(payload["sentences"]),
            "citation_count": len(payload["citation_order"]),
            "bibliography_status": citation_map["status"],
            "human_decisions_created": 0,
            "whole_review_expanded": False,
        }
        atomic_write_json(run_root / "reports/vertical_slice_summary_v2.json", summary)
        improvements = [
            "Scientific themes replace source-by-source enumeration.",
            "Yield, selectivity, conditions, and mechanistic evidence are clustered before drafting.",
            "Duplicate numeric results and retained source conflicts are excluded from prose.",
            "Numeric citations are bound to supporting paper IDs.",
        ]
        packet = [
            "# Phase 8B V2 Human Review Packet",
            "",
            revision.rstrip(),
            "",
            "## Main Improvements",
            "",
            *(f"- {item}" for item in improvements),
            "",
            "## Citation Map",
            "",
            *(f"- [{entry['citation_id']}] `{entry['paper_id']}` ({entry['metadata_status']})" for entry in citation_map["entries"]),
            "",
            "## Validator",
            "",
            f"- status: `{validation['status']}`",
            f"- issues: `{validation['issue_count']}`",
            f"- bibliography: `{citation_map['status']}`",
            "- remaining attention: review prose flow and the bibliography metadata-pending marker; no claim-by-claim re-review is requested.",
            "",
            "## Decision",
            "",
            "Choose one: `ACCEPT`, `ACCEPT_WITH_MINOR_CHANGES`, or `REVISE`.",
            "",
        ]
        atomic_write_text(run_root / "reports/human_review_packet.md", "\n".join(packet))
    else:
        summary = {
            "schema_version": "2.0",
            "status": "FAIL",
            "stage": stage,
            "final_claim_accounting_count": 44,
            "whole_review_expanded": False,
        }
        atomic_write_json(run_root / "reports/vertical_slice_summary_v2.json", summary)
    manifest = {
        **run_manifest,
        "schema_version": "2.0",
        "stage": stage,
        "method_label": METHOD_LABEL,
        "final_claim_accounting_count": 44,
        "available_non_conflict_claim_count": 37,
        "retained_conflict_count": 7,
        "model_request_count": generation.get("request_count", 0),
        "validation_status": validation.get("status"),
        "human_decisions_created": 0,
        "whole_review_expanded": False,
    }
    atomic_write_json(run_root / "coordinator/run_manifest.json", manifest)
    manifest_hash = _write_hash_manifest(run_root)
    return {
        "stage": stage,
        "status": validation.get("status"),
        "run_root": str(run_root),
        "hash_manifest_sha256": manifest_hash,
    }
