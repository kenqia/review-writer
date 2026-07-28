"""Fail-closed adapter from legacy evidence cards to unverified candidates."""

from __future__ import annotations

import copy
from typing import Any


class LegacyEvidenceAdapterError(ValueError):
    """A stable legacy adapter contract failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _texts(card: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("statement", "claim_text", "text"):
        value = card.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
    candidate = card.get("candidate")
    if isinstance(candidate, dict):
        claims = candidate.get("claims")
        if isinstance(claims, list):
            for claim in claims:
                if isinstance(claim, dict) and isinstance(claim.get("claim_text"), str):
                    value = claim["claim_text"].strip()
                    if value:
                        values.append(value)
    return list(dict.fromkeys(values))


def _locators(card: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[object] = []
    direct = card.get("locator")
    if isinstance(direct, dict):
        rows.append(direct)
    refs = card.get("evidence_refs")
    if isinstance(refs, list):
        rows.extend(refs)
    candidate = card.get("candidate")
    if isinstance(candidate, dict) and isinstance(candidate.get("claims"), list):
        for claim in candidate["claims"]:
            if isinstance(claim, dict) and isinstance(claim.get("evidence_refs"), list):
                rows.extend(claim["evidence_refs"])
    allowed = ("source_id", "page", "section_or_item", "figure_or_table", "exact_quote")
    return [
        {key: copy.deepcopy(row[key]) for key in allowed if key in row}
        for row in rows
        if isinstance(row, dict)
    ]


def _risks(card: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("risk_classes", "risk_categories", "risk_hints"):
        rows = card.get(key)
        if isinstance(rows, list):
            values.extend(value.strip() for value in rows if isinstance(value, str) and value.strip())
    return list(dict.fromkeys(values))


def adapt_legacy_evidence(card: object) -> dict[str, Any]:
    """Copy only useful legacy hints while discarding all former authority."""

    if not isinstance(card, dict):
        raise LegacyEvidenceAdapterError("LEGACY_EVIDENCE_INVALID")
    texts = _texts(card)
    adapted: dict[str, Any] = {
        "origin": "legacy_candidate",
        "legacy_origin": "legacy_evidence_card",
        "status": "needs_review",
        "needs_reverification": True,
        "candidate_texts": texts,
        "locators": _locators(card),
        "risk_classes": _risks(card),
    }
    if texts:
        adapted["statement"] = texts[0]
    return adapted
