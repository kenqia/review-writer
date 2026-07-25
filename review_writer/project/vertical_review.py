"""Authoritative, offline Source-to-Manuscript review projection."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any


PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
RISK_LEVELS = frozenset({"R0", "R1", "R2", "R3"})
HIGH_RISK_CATEGORIES = frozenset(
    {
        "CROSS_STUDY_COMPARISON",
        "FIGURE_TABLE_CHEMISTRY",
        "MATERIAL_ASSERTION",
        "MATERIAL_COMPARISON",
        "MECHANISM_CAUSALITY",
        "NEGATIVE_GENERALIZATION",
        "NON_PEER_REVIEWED",
        "SOURCE_CONFLICT",
        "STEREOCHEMISTRY",
        "STRUCTURE",
    }
)


class VerticalReviewError(ValueError):
    """The review projection cannot safely accept the requested state change."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def _fail(code: str, message: str) -> None:
    raise VerticalReviewError(code, message)


def _json_copy(value: Any, code: str) -> Any:
    try:
        detached = copy.deepcopy(value)
        encoded = json.dumps(
            detached,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return json.loads(encoded)
    except (TypeError, ValueError, RecursionError) as exc:
        _fail(code, "value must be finite JSON data")


def _json_bytes(value: Any) -> bytes:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise VerticalReviewError("JSON_INVALID", "value must be finite JSON data") from exc


def _jsonl_bytes(rows: list[dict[str, Any]]) -> bytes:
    try:
        lines = [
            json.dumps(
                row,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            for row in rows
        ]
    except (TypeError, ValueError) as exc:
        raise VerticalReviewError("JSONL_INVALID", "row must be finite JSON data") from exc
    return (("\n".join(lines) + "\n") if lines else "").encode("utf-8")


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def _write_json(path: Path, value: Any) -> None:
    _atomic_write(path, _json_bytes(value))


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    _atomic_write(path, _jsonl_bytes(rows))


def _read_json(path: Path, code: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VerticalReviewError(code, "required JSON state is missing or invalid") from exc


def _read_jsonl(path: Path, code: str) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        rows = [json.loads(line) for line in lines if line.strip()]
    except (OSError, json.JSONDecodeError) as exc:
        raise VerticalReviewError(code, "required JSONL state is missing or invalid") from exc
    if not all(isinstance(row, dict) for row in rows):
        _fail(code, "JSONL state must contain objects")
    return rows


def _project_state(project: Path) -> dict[str, Any]:
    state = _read_json(project / "00_brief" / "review_state.json", "PROJECT_STATE_INVALID")
    if not isinstance(state, dict) or not isinstance(state.get("project_id"), str):
        _fail("PROJECT_STATE_INVALID", "review state does not identify a project")
    return state


def initialize_review(review_root: Path, project_id: str, brief: dict) -> Path:
    """Create one deterministic review project using only authorized objects."""
    root = Path(review_root)
    if (
        not isinstance(project_id, str)
        or project_id in {".", ".."}
        or PROJECT_ID_RE.fullmatch(project_id) is None
    ):
        _fail("PROJECT_ID_INVALID", "project_id must be a portable single path component")
    brief_copy = _json_copy(brief, "BRIEF_INVALID")
    if not isinstance(brief_copy, dict):
        _fail("BRIEF_INVALID", "brief must be a JSON object")

    project = root / project_id
    state_path = project / "00_brief" / "review_state.json"
    state = {
        "brief": brief_copy,
        "project_id": project_id,
        "schema_version": "vertical-review-state.v1",
    }
    if state_path.exists():
        if _read_json(state_path, "PROJECT_STATE_INVALID") != state:
            _fail("PROJECT_ALREADY_EXISTS", "existing project state differs")
        return project
    if project.exists() and any(project.iterdir()):
        _fail("PROJECT_ALREADY_EXISTS", "nonempty project directory has no review state")

    _write_json(state_path, state)
    _write_jsonl(project / "01_evidence" / "evidence_cards.jsonl", [])
    _write_json(project / "01_evidence" / "exception_queue.json", {"exceptions": []})
    _write_jsonl(project / "02_claims" / "claim_projection.jsonl", [])
    _write_json(project / "03_review" / "risk_decisions.json", {"decisions": []})
    return project


def _source_locators(evidence_refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = ("source_id", "page", "section_or_item", "depiction_locator")
    return [{key: ref[key] for key in keys if key in ref} for ref in evidence_refs]


def _validate_candidate(candidate: Any) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        _fail("CANDIDATE_INVALID", "candidate must be a JSON object")
    study_id = candidate.get("study_id")
    claims = candidate.get("claims")
    if not isinstance(study_id, str) or not study_id.strip():
        _fail("STUDY_ID_INVALID", "candidate requires a nonempty study_id")
    if not isinstance(claims, list) or not claims:
        _fail("CLAIMS_INVALID", "candidate requires grounded claims")
    seen: set[str] = set()
    for claim in claims:
        if not isinstance(claim, dict):
            _fail("CLAIM_INVALID", "claims must be JSON objects")
        claim_id = claim.get("claim_id")
        text = claim.get("claim_text")
        refs = claim.get("evidence_refs")
        risk_level = claim.get("risk_level")
        categories = claim.get("risk_categories")
        if not isinstance(claim_id, str) or not claim_id.strip() or claim_id in seen:
            _fail("CLAIM_ID_INVALID", "claim_id values must be nonempty and unique")
        seen.add(claim_id)
        if not isinstance(text, str) or not text.strip():
            _fail("CLAIM_TEXT_INVALID", "claim_text must be nonempty")
        if risk_level not in RISK_LEVELS:
            _fail("CLAIM_RISK_INVALID", "risk_level must be R0, R1, R2, or R3")
        if (
            not isinstance(categories, list)
            or not all(isinstance(category, str) and category for category in categories)
            or len(categories) != len(set(categories))
        ):
            _fail("CLAIM_RISK_INVALID", "risk_categories must be unique nonempty strings")
        if not isinstance(refs, list) or not refs or not all(isinstance(ref, dict) for ref in refs):
            _fail("CLAIM_EVIDENCE_INVALID", "every claim requires evidence_refs")
        for ref in refs:
            source_id = ref.get("source_id")
            page = ref.get("page")
            section = ref.get("section_or_item")
            locator = ref.get("locator")
            depiction = ref.get("depiction_locator")
            if not isinstance(source_id, str) or not source_id.strip():
                _fail("CLAIM_EVIDENCE_INVALID", "evidence refs require source_id")
            if not (
                isinstance(locator, (str, dict))
                and bool(locator)
                or isinstance(page, int)
                and not isinstance(page, bool)
                and page >= 1
                and isinstance(section, str)
                and bool(section.strip())
                or isinstance(depiction, str)
                and bool(depiction.strip())
            ):
                _fail("CLAIM_LOCATOR_INVALID", "evidence refs require a provenance locator")
    return candidate


def _reduce_decision(card: dict[str, Any], claim: dict[str, Any]) -> tuple[str, str]:
    if card["r0_report"].get("status") != "R0_PASS":
        return "BLOCKED", "R0_NOT_PASS"
    if card["reviewer"].get("verdict") != "SUPPORT":
        return "BLOCKED", "REVIEWER_NOT_SUPPORT"
    if claim["risk_level"] == "R3" or set(claim["risk_categories"]) & HIGH_RISK_CATEGORIES:
        return "HUMAN_REQUIRED", "HIGH_RISK_REQUIRES_HUMAN"
    return "APPROVED", "R0_PASS_AND_REVIEWER_SUPPORT"


def _projection_for_card(card: dict[str, Any]) -> list[dict[str, Any]]:
    candidate = card["candidate"]
    projected: list[dict[str, Any]] = []
    for claim in candidate["claims"]:
        decision, reason = _reduce_decision(card, claim)
        projected.append({
            "claim_id": claim["claim_id"],
            "decision": decision,
            "decision_reason": reason,
            "evidence_refs": copy.deepcopy(claim["evidence_refs"]),
            "lineage": {
                "job_id": candidate.get("job_id"),
                "source_locators": _source_locators(claim["evidence_refs"]),
                "study_id": card["study_id"],
            },
            "original_text": claim["claim_text"],
            "risk_categories": copy.deepcopy(claim.get("risk_categories", [])),
            "risk_level": claim.get("risk_level"),
            "study_id": card["study_id"],
            "text": claim["claim_text"],
        })
    return projected


def _read_risk_decisions(project: Path) -> list[dict[str, Any]]:
    payload = _read_json(project / "03_review" / "risk_decisions.json", "RISK_DECISIONS_INVALID")
    if not isinstance(payload, dict) or not isinstance(payload.get("decisions"), list):
        _fail("RISK_DECISIONS_INVALID", "risk decisions must contain a decisions list")
    if not all(isinstance(row, dict) for row in payload["decisions"]):
        _fail("RISK_DECISIONS_INVALID", "risk decision rows must be objects")
    return payload["decisions"]


def _apply_risk_records(
    projection: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    reduced = copy.deepcopy(projection)
    by_id = {row["claim_id"]: row for row in reduced}
    targets: list[str] = []
    for record in decisions:
        claim_id = record.get("claim_id")
        action = record.get("action")
        if not isinstance(claim_id, str) or not claim_id:
            _fail("RISK_TARGET_INVALID", "risk decisions require claim_id")
        targets.append(claim_id)
        row = by_id.get(claim_id)
        if row is None:
            _fail("RISK_TARGET_UNKNOWN", "risk decision target is not in the projection")
        if row["decision"] == "BLOCKED":
            _fail("RISK_TARGET_BLOCKED", "blocked claims cannot be approved by risk review")
        if action == "APPROVE":
            row["decision"] = "APPROVED"
            row["decision_reason"] = "HUMAN_RISK_APPROVED"
            row["text"] = row["original_text"]
        elif action == "REWORD":
            approved_text = record.get("approved_text")
            if not isinstance(approved_text, str) or not approved_text.strip():
                _fail("APPROVED_TEXT_REQUIRED", "REWORD requires nonempty approved_text")
            row["decision"] = "APPROVED"
            row["decision_reason"] = "HUMAN_RISK_REWORDED"
            row["text"] = approved_text
        elif action == "EXCLUDE":
            row["decision"] = "BLOCKED"
            row["decision_reason"] = "HUMAN_RISK_EXCLUDED"
            row["text"] = row["original_text"]
        elif action == "UNRESOLVED":
            row["decision"] = "HUMAN_REQUIRED"
            row["decision_reason"] = "HUMAN_RISK_UNRESOLVED"
            row["text"] = row["original_text"]
        else:
            _fail("RISK_ACTION_INVALID", "risk action is invalid")
    if len(targets) != len(set(targets)):
        _fail("RISK_TARGET_DUPLICATE", "risk decision targets must be unique")
    return reduced


def _project_cards(
    cards: list[dict[str, Any]],
    risk_decisions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    projection = [row for card in cards for row in _projection_for_card(card)]
    claim_ids = [row["claim_id"] for row in projection]
    if len(claim_ids) != len(set(claim_ids)):
        _fail("CLAIM_ID_DUPLICATE", "claim_id values must be unique across studies")
    projection.sort(key=lambda row: row["claim_id"])
    return _apply_risk_records(projection, risk_decisions)


def _append_exception(
    project: Path,
    *,
    study_id: str | None,
    error_code: str,
    r0_status: str | None,
    reviewer_verdict: str | None,
) -> None:
    path = project / "01_evidence" / "exception_queue.json"
    queue = _read_json(path, "EXCEPTION_QUEUE_INVALID")
    if not isinstance(queue, dict) or not isinstance(queue.get("exceptions"), list):
        _fail("EXCEPTION_QUEUE_INVALID", "exception queue must contain an exceptions list")
    queue["exceptions"].append(
        {
            "error_code": error_code,
            "r0_status": r0_status,
            "reviewer_verdict": reviewer_verdict,
            "study_id": study_id or "UNKNOWN_STUDY",
        }
    )
    _write_json(path, queue)


def register_study(
    project: Path,
    candidate: dict,
    r0_report: dict,
    reviewer: dict,
) -> dict:
    """Register or replace one grounded study card and rebuild its projection."""
    project_path = Path(project)
    _project_state(project_path)
    raw_study_id = candidate.get("study_id") if isinstance(candidate, dict) else None
    raw_r0_status = r0_report.get("status") if isinstance(r0_report, dict) else None
    raw_verdict = reviewer.get("verdict") if isinstance(reviewer, dict) else None
    try:
        candidate_copy = _validate_candidate(_json_copy(candidate, "CANDIDATE_INVALID"))
        r0_copy = _json_copy(r0_report, "R0_REPORT_INVALID")
        reviewer_copy = _json_copy(reviewer, "REVIEWER_INVALID")
        if not isinstance(r0_copy, dict) or r0_copy.get("status") != "R0_PASS":
            _fail("R0_REJECTED", "study did not pass the grounding contract")
        if (
            not isinstance(reviewer_copy, dict)
            or not isinstance(reviewer_copy.get("verdict"), str)
            or not reviewer_copy["verdict"]
        ):
            _fail("REVIEWER_INVALID", "reviewer verdict must be a nonempty string")

        card = {
            "candidate": candidate_copy,
            "r0_report": r0_copy,
            "reviewer": reviewer_copy,
            "study_id": candidate_copy["study_id"],
        }
        cards_path = project_path / "01_evidence" / "evidence_cards.jsonl"
        cards = _read_jsonl(cards_path, "EVIDENCE_CARDS_INVALID")
        study_ids = [row.get("study_id") for row in cards]
        if (
            any(not isinstance(study_id, str) or not study_id for study_id in study_ids)
            or len(study_ids) != len(set(study_ids))
        ):
            _fail("EVIDENCE_CARDS_INVALID", "stored study identities are invalid")
        by_study = {row["study_id"]: row for row in cards}
        by_study[card["study_id"]] = card
        ordered_cards = [by_study[key] for key in sorted(by_study)]
        projection = _project_cards(ordered_cards, _read_risk_decisions(project_path))
    except VerticalReviewError as exc:
        _append_exception(
            project_path,
            study_id=raw_study_id if isinstance(raw_study_id, str) else None,
            error_code=exc.code,
            r0_status=raw_r0_status if isinstance(raw_r0_status, str) else None,
            reviewer_verdict=raw_verdict if isinstance(raw_verdict, str) else None,
        )
        raise

    _write_jsonl(cards_path, ordered_cards)
    _write_jsonl(project_path / "02_claims" / "claim_projection.jsonl", projection)
    return {"claim_projection": projection, "study_id": card["study_id"]}


def rebuild_projection(project: Path) -> list[dict]:
    """Rebuild the consumer projection from evidence cards and recorded decisions."""
    project_path = Path(project)
    _project_state(project_path)
    cards = _read_jsonl(
        project_path / "01_evidence" / "evidence_cards.jsonl",
        "EVIDENCE_CARDS_INVALID",
    )
    study_ids: list[str] = []
    for card in cards:
        candidate = _validate_candidate(card.get("candidate"))
        study_id = card.get("study_id")
        if study_id != candidate["study_id"] or not isinstance(card.get("r0_report"), dict):
            _fail("EVIDENCE_CARD_INVALID", "evidence card study or R0 binding is invalid")
        reviewer = card.get("reviewer")
        if not isinstance(reviewer, dict) or not isinstance(reviewer.get("verdict"), str):
            _fail("EVIDENCE_CARD_INVALID", "evidence card reviewer binding is invalid")
        study_ids.append(study_id)
    if len(study_ids) != len(set(study_ids)):
        _fail("EVIDENCE_CARDS_INVALID", "stored study identities must be unique")
    ordered_cards = sorted(cards, key=lambda card: card["study_id"])
    projection = _project_cards(ordered_cards, _read_risk_decisions(project_path))
    _write_jsonl(project_path / "02_claims" / "claim_projection.jsonl", projection)
    return projection


def _load_projection(project: Path) -> list[dict[str, Any]]:
    rows = _read_jsonl(project / "02_claims" / "claim_projection.jsonl", "PROJECTION_INVALID")
    claim_ids = [row.get("claim_id") for row in rows]
    if (
        any(not isinstance(claim_id, str) or not claim_id for claim_id in claim_ids)
        or len(claim_ids) != len(set(claim_ids))
        or any(row.get("decision") not in {"APPROVED", "BLOCKED", "HUMAN_REQUIRED"} for row in rows)
    ):
        _fail("PROJECTION_INVALID", "projection identities or decisions are invalid")
    return rows


def build_risk_packet(project: Path, low_risk_sample_rate: float = 0.10) -> dict:
    """Build one de-duplicated packet of required reviews and low-risk audit claims."""
    project_path = Path(project)
    state = _project_state(project_path)
    if (
        isinstance(low_risk_sample_rate, bool)
        or not isinstance(low_risk_sample_rate, (int, float))
        or not math.isfinite(low_risk_sample_rate)
        or not 0 <= low_risk_sample_rate <= 1
    ):
        _fail("SAMPLE_RATE_INVALID", "low-risk sample rate must be finite and within [0, 1]")
    rate = float(low_risk_sample_rate)
    projection = _load_projection(project_path)
    human = sorted(
        (row for row in projection if row["decision"] == "HUMAN_REQUIRED"),
        key=lambda row: row["claim_id"],
    )
    low_risk = sorted(
        (row for row in projection if row["decision"] == "APPROVED"),
        key=lambda row: (hashlib.sha256(row["claim_id"].encode("utf-8")).hexdigest(), row["claim_id"]),
    )
    sample_count = math.ceil(len(low_risk) * rate) if rate else 0
    selected_low_risk = low_risk[:sample_count]
    selected: dict[str, dict[str, Any]] = {}
    for row in human:
        target = copy.deepcopy(row)
        target["selection_reason"] = "HUMAN_REQUIRED"
        selected[row["claim_id"]] = target
    for row in selected_low_risk:
        target = copy.deepcopy(row)
        target["selection_reason"] = "LOW_RISK_AUDIT"
        selected.setdefault(row["claim_id"], target)
    targets = list(selected.values())
    packet = {
        "human_required_count": len(human),
        "low_risk_sample_count": len(selected_low_risk),
        "low_risk_sample_rate": rate,
        "project_id": state["project_id"],
        "schema_version": "vertical-review-risk-packet.v1",
        "target_count": len(targets),
        "targets": targets,
    }
    _write_json(project_path / "03_review" / "risk_packet.json", packet)
    return packet


def apply_risk_decisions(project: Path, decisions: dict) -> list[dict]:
    """Apply human risk choices only to projection consumer status and wording."""
    project_path = Path(project)
    state = _project_state(project_path)
    payload = _json_copy(decisions, "RISK_DECISIONS_INVALID")
    if not isinstance(payload, dict) or not isinstance(payload.get("decisions"), list):
        _fail("RISK_DECISIONS_INVALID", "decisions must contain a list")
    normalized: list[dict[str, Any]] = []
    for row in payload["decisions"]:
        if not isinstance(row, dict):
            _fail("RISK_DECISIONS_INVALID", "decision rows must be objects")
        record = {"action": row.get("action"), "claim_id": row.get("claim_id")}
        if row.get("action") == "REWORD":
            record["approved_text"] = row.get("approved_text")
        normalized.append(record)
    normalized.sort(key=lambda row: str(row.get("claim_id", "")))

    # Rebuild from cards so a prior human decision never becomes the new scientific baseline.
    cards = _read_jsonl(
        project_path / "01_evidence" / "evidence_cards.jsonl",
        "EVIDENCE_CARDS_INVALID",
    )
    base = _project_cards(sorted(cards, key=lambda card: card["study_id"]), [])
    projected = _apply_risk_records(base, normalized)
    decision_payload = {
        "decisions": normalized,
        "project_id": state["project_id"],
        "schema_version": "vertical-review-risk-decisions.v1",
    }
    _write_json(project_path / "03_review" / "risk_decisions.json", decision_payload)
    _write_jsonl(project_path / "02_claims" / "claim_projection.jsonl", projected)
    return projected


def build_writer_packet(project: Path) -> dict:
    """Write the only claim whitelist that manuscript generation may consume."""
    project_path = Path(project)
    state = _project_state(project_path)
    projection = _load_projection(project_path)
    approved = [copy.deepcopy(row) for row in projection if row["decision"] == "APPROVED"]
    excluded = [
        {
            "claim_id": row["claim_id"],
            "decision": row["decision"],
            "reason": row["decision_reason"],
            "study_id": row["study_id"],
        }
        for row in projection
        if row["decision"] != "APPROVED"
    ]
    packet = {
        "approved_claim_count": len(approved),
        "blocked_count": sum(row["decision"] == "BLOCKED" for row in projection),
        "claims": approved,
        "human_required_count": sum(
            row["decision"] == "HUMAN_REQUIRED" for row in projection
        ),
        "known_exclusions": excluded,
        "project_id": state["project_id"],
        "schema_version": "vertical-review-writer-packet.v1",
    }
    _write_json(project_path / "02_claims" / "writer_packet.json", packet)
    return packet


def benchmark_metrics(project: Path) -> dict:
    """Return deterministic counts for the authoritative evidence/claim projection."""
    project_path = Path(project)
    state = _project_state(project_path)
    cards = _read_jsonl(
        project_path / "01_evidence" / "evidence_cards.jsonl",
        "EVIDENCE_CARDS_INVALID",
    )
    queue = _read_json(
        project_path / "01_evidence" / "exception_queue.json",
        "EXCEPTION_QUEUE_INVALID",
    )
    if not isinstance(queue, dict) or not isinstance(queue.get("exceptions"), list):
        _fail("EXCEPTION_QUEUE_INVALID", "exception queue must contain an exceptions list")
    projection = _load_projection(project_path)
    return {
        "approved_claim_count": sum(row["decision"] == "APPROVED" for row in projection),
        "blocked_claim_count": sum(row["decision"] == "BLOCKED" for row in projection),
        "exception_count": len(queue["exceptions"]),
        "human_required_claim_count": sum(
            row["decision"] == "HUMAN_REQUIRED" for row in projection
        ),
        "project_id": state["project_id"],
        "projected_claim_count": len(projection),
        "registered_study_count": len(cards),
    }
