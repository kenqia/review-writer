"""Fail-closed, hash-bound comparison and synthesis contracts."""
from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .paper_evidence import (
    HONEST_PROGRESSIVE_ROUTE,
    PaperEvidenceError,
    _honest_progressive_rows,
    paper_evidence_state,
)
from .paper_evidence_store import PaperEvidenceStoreError, project_write_lock
from .chemical_completion import ChemicalCompletionError, require_honest_progressive_projection
from .source_truth import REPO_ROOT, SourceTruthError, canonical_digest, declared_study_ids, study_source_tier
from .verification_decision import VerificationDecisionError, verification_decision

SHA256 = re.compile(r"^[0-9a-f]{64}$")
PROTOCOL_PATH = Path("02_synthesis/comparison_protocol.json")
COVERAGE_PATH = Path("02_synthesis/coverage_map.json")
CLAIM_PATH = Path("02_synthesis/synthesis_claim_projection.jsonl")
EXACT_CHEMICAL_FIELD_DEPENDENCIES = frozenset({"molecule", "smiles", "molblock"})
FROZEN_REVIEW_QUESTIONS = (
    "主要键组合、反应模式及活化策略是什么？",
    "条件如何影响表现，哪些结果不可直接比较？",
    "底物范围、耐受性、选择性和局限是什么？",
    "机制证据处于什么层级，作者解释之间有哪些冲突？",
    "通用性、选择性、放大、资源效率和机制确定性还存在哪些缺口？",
)
FROZEN_REVIEW_QUESTIONS_DIGEST = canonical_digest(list(FROZEN_REVIEW_QUESTIONS))


class SynthesisError(ValueError):
    def __init__(self, code: str):
        super().__init__(code); self.code = code


def _normalize_authoritative_marker(value: dict[str, Any]) -> None:
    """Accept old callers while normalizing the one authoritative marker."""
    aliases = [key for key in ("authoritative", "run_mode") if key in value]
    if not aliases:
        return
    if "authoritative_run" in value:
        raise SynthesisError("AUTHORITATIVE_RUN_INVALID")
    if len(aliases) > 1:
        first, second = (value[key] for key in aliases)
        if first != second:
            raise SynthesisError("AUTHORITATIVE_RUN_INVALID")
    alias = aliases[0]
    value["authoritative_run"] = (
        value[alias] is True
        if alias == "authoritative"
        else value[alias] == "authoritative"
    )
    value.pop(alias, None)


def validate_authoritative_review_questions(value: object) -> dict[str, Any]:
    """Validate the frozen question contract without changing the input."""
    if not isinstance(value, dict):
        raise SynthesisError("REVIEW_QUESTIONS_INVALID")
    authoritative = value.get("authoritative_run", False)
    if not isinstance(authoritative, bool):
        raise SynthesisError("AUTHORITATIVE_RUN_INVALID")
    if not authoritative:
        return {"authoritative_run": False}
    questions = value.get("review_questions")
    if questions is None:
        raise SynthesisError("REVIEW_QUESTIONS_REQUIRED")
    if questions != list(FROZEN_REVIEW_QUESTIONS):
        raise SynthesisError("REVIEW_QUESTIONS_INVALID")
    digest = value.get("review_questions_digest")
    if digest is not None and digest != FROZEN_REVIEW_QUESTIONS_DIGEST:
        raise SynthesisError("REVIEW_QUESTIONS_STALE")
    if digest is None:
        raise SynthesisError("REVIEW_QUESTIONS_REQUIRED")
    return {
        "authoritative_run": True,
        "review_questions": list(FROZEN_REVIEW_QUESTIONS),
        "review_questions_digest": FROZEN_REVIEW_QUESTIONS_DIGEST,
    }


def _prepare_authoritative_questions(value: dict[str, Any]) -> dict[str, Any]:
    """Validate input questions before computing a protocol digest."""
    _normalize_authoritative_marker(value)
    value.setdefault("authoritative_run", False)
    if value["authoritative_run"] is not True:
        if not isinstance(value["authoritative_run"], bool):
            raise SynthesisError("AUTHORITATIVE_RUN_INVALID")
        return {"authoritative_run": False}
    questions = validate_authoritative_review_questions(
        {**value, "review_questions_digest": value.get("review_questions_digest")}
        if "review_questions_digest" in value
        else {**value, "review_questions_digest": FROZEN_REVIEW_QUESTIONS_DIGEST}
    )
    supplied_digest = value.get("review_questions_digest")
    if supplied_digest is not None and supplied_digest != FROZEN_REVIEW_QUESTIONS_DIGEST:
        raise SynthesisError("REVIEW_QUESTIONS_STALE")
    value.update(questions)
    return questions


def _protocol_authoritative(value: object) -> bool:
    return isinstance(value, dict) and value.get("authoritative_run") is True


def _root(project: Path) -> Path:
    p = Path(project)
    if p.is_symlink() or not p.is_dir(): raise SynthesisError("PROJECT_INVALID")
    return p.resolve(strict=True)


def _schema(name: str) -> dict[str, Any]:
    try: return json.loads((REPO_ROOT / "schemas/synthesis" / name).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc: raise SynthesisError("SYNTHESIS_SCHEMA_INVALID") from exc


def _validate(value: object, name: str, code: str = "SYNTHESIS_INVALID") -> None:
    errors = list(Draft202012Validator(_schema(name)).iter_errors(value))
    if errors: raise SynthesisError(code)


def _write(project: Path, rel: Path, value: object) -> None:
    path = project / rel; path.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(path) and (path.is_symlink() or not path.is_file()): raise SynthesisError("SYNTHESIS_PATH_INVALID")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2); handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def _write_raw(project: Path, rel: Path, text: str) -> None:
    path = project / rel; path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def _write_jsonl(project: Path, rel: Path, rows: list[dict[str, Any]]) -> None:
    _write_raw(project, rel, "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for row in rows) + ("\n" if rows else ""))


def _read_json(project: Path, rel: Path) -> Any:
    path = project / rel
    if not path.is_file() or path.is_symlink(): return None
    try: return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError): raise SynthesisError("SYNTHESIS_INVALID")


def _read_jsonl(project: Path, rel: Path) -> list[dict[str, Any]]:
    path = project / rel
    if not path.is_file() or path.is_symlink(): return []
    try: rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, UnicodeError, json.JSONDecodeError) as exc: raise SynthesisError("SYNTHESIS_INVALID") from exc
    if not all(isinstance(row, dict) for row in rows): raise SynthesisError("SYNTHESIS_INVALID")
    return rows


def _decision(payload: dict[str, Any], digest: str) -> dict[str, Any]:
    action = payload.get("action", "approve")
    reason = payload.get("reason")
    if action not in {"approve", "revise_and_approve", "reject"} or not isinstance(reason, str) or not reason.strip(): raise SynthesisError("SYNTHESIS_DECISION_INVALID")
    try: return verification_decision(actor_type=payload.get("actor_type", "human_researcher"), actor_label=payload.get("actor_label", "local-researcher"), action=action, reason=reason, bound_object_digest=digest)
    except VerificationDecisionError as exc: raise SynthesisError("SYNTHESIS_DECISION_INVALID") from exc


def _valid_decision(value: object, digest: str) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("action") not in {"approve", "revise_and_approve", "reject"}:
        return False
    try:
        normalized = verification_decision(
            actor_type=value.get("actor_type"),
            actor_label=value.get("actor_label"),
            action=value.get("action"),
            reason=value.get("reason"),
            bound_object_digest=value.get("bound_object_digest"),
            bound_gate_digest=value.get("bound_gate_digest"),
            decided_at=value.get("decided_at"),
        )
    except (VerificationDecisionError, TypeError, AttributeError):
        return False
    return normalized == value and value.get("bound_object_digest") == digest


def _unsigned(value: dict[str, Any], digest_key: str) -> dict[str, Any]:
    result = {k: v for k, v in value.items() if k not in {digest_key, "status", "reason_code"}}
    result["decision"] = None
    return result


def register_comparison_protocol(project: Path, payload: object) -> dict[str, Any]:
    project = _root(project)
    if not isinstance(payload, dict): raise SynthesisError("COMPARISON_PROTOCOL_INVALID")
    value = copy.deepcopy(payload); value.setdefault("schema_version", "comparison-protocol.v1")
    value.setdefault("decision", None)
    _prepare_authoritative_questions(value)
    required = {"comparison_id", "comparison_objects", "axes", "normalization_rules", "missing_value_policy", "incomparability_rules", "counterevidence_rules", "claim_strength"}
    if not required.issubset(value): raise SynthesisError("COMPARISON_PROTOCOL_INVALID")
    try:
        evidence = paper_evidence_state(project)
    except PaperEvidenceError as exc:
        raise SynthesisError("PAPER_EVIDENCE_NOT_READY") from exc
    value["paper_evidence_projection_digest"] = evidence.get("projection_digest")
    value["protocol_digest"] = canonical_digest(_unsigned(value, "protocol_digest"))
    _validate(value, "comparison_protocol.v1.schema.json", "COMPARISON_PROTOCOL_INVALID")
    with project_write_lock(project): _write(project, PROTOCOL_PATH, value)
    return value


def apply_comparison_protocol_decision(project: Path, payload: object) -> dict[str, Any]:
    project = _root(project); protocol = _read_json(project, PROTOCOL_PATH)
    if not isinstance(protocol, dict): raise SynthesisError("COMPARISON_PROTOCOL_NOT_FOUND")
    if not isinstance(payload, dict): raise SynthesisError("COMPARISON_PROTOCOL_DECISION_INVALID")
    digest = protocol.get("protocol_digest")
    if not isinstance(digest, str): raise SynthesisError("COMPARISON_PROTOCOL_INVALID")
    protocol["decision"] = _decision(payload, digest)
    with project_write_lock(project): _write(project, PROTOCOL_PATH, protocol)
    return protocol


def comparison_protocol_state(project: Path) -> dict[str, Any]:
    value = _read_json(_root(project), PROTOCOL_PATH)
    if not isinstance(value, dict): return {"status": "needs_review", "workflow_can_continue": False, "reason_code": "COMPARISON_PROTOCOL_NOT_APPROVED"}
    try:
        questions = validate_authoritative_review_questions(value) if _protocol_authoritative(value) else {"authoritative_run": False}
        _validate(value, "comparison_protocol.v1.schema.json", "COMPARISON_PROTOCOL_INVALID")
    except SynthesisError as exc: return {"status": "needs_review", "workflow_can_continue": False, "reason_code": exc.code}
    digest = value.get("protocol_digest")
    unsigned = _unsigned(value, "protocol_digest")
    if not isinstance(digest, str) or digest != canonical_digest(unsigned):
        return {"status": "needs_review", "workflow_can_continue": False, "reason_code": "COMPARISON_PROTOCOL_STALE"}
    decision = value.get("decision") or {}
    ok = _valid_decision(decision, digest) and decision.get("action") == "approve" and value.get("paper_evidence_projection_digest") == paper_evidence_state(_root(project)).get("projection_digest")
    return {
        "status": "approved" if ok else "needs_review",
        "workflow_can_continue": ok,
        "reason_code": "COMPARISON_PROTOCOL_APPROVED" if ok else "COMPARISON_PROTOCOL_NOT_APPROVED",
        "protocol_digest": value.get("protocol_digest"),
        "authoritative_run": questions.get("authoritative_run", False),
        "review_questions": questions.get("review_questions"),
        "review_questions_digest": questions.get("review_questions_digest"),
        "value": value,
    }


def register_coverage_map(project: Path, payload: object) -> dict[str, Any]:
    project = _root(project)
    if not isinstance(payload, dict): raise SynthesisError("COVERAGE_MAP_INVALID")
    protocol = comparison_protocol_state(project)
    if not protocol.get("workflow_can_continue"): raise SynthesisError("COMPARISON_PROTOCOL_NOT_APPROVED")
    value = copy.deepcopy(payload); value.setdefault("schema_version", "coverage-map.v1"); value.setdefault("corpus_kind", "calibration_corpus"); value.setdefault("known_omissions", [])
    value["comparison_protocol_digest"] = protocol.get("protocol_digest")
    _validate(value, "coverage_map.v1.schema.json", "COVERAGE_MAP_INVALID")
    with project_write_lock(project): _write(project, COVERAGE_PATH, value)
    return value


def coverage_map_state(project: Path) -> dict[str, Any]:
    project = _root(project); value = _read_json(project, COVERAGE_PATH); protocol = comparison_protocol_state(project)
    if not isinstance(value, dict):
        return {"status": "needs_review", "workflow_can_continue": False, "reason_code": "COVERAGE_MAP_MISSING"}
    try: _validate(value, "coverage_map.v1.schema.json", "COVERAGE_MAP_INVALID")
    except SynthesisError as exc:
        return {"status": "needs_review", "workflow_can_continue": False, "reason_code": exc.code}
    ok = (
        protocol.get("workflow_can_continue")
        and value.get("comparison_protocol_digest") == protocol.get("protocol_digest")
        and value.get("comparison_id") == (protocol.get("value") or {}).get("comparison_id")
    )
    return {"status": "approved" if ok else "needs_review", "workflow_can_continue": bool(ok), "reason_code": "COVERAGE_MAP_APPROVED" if ok else "COVERAGE_MAP_STALE", "value": value}


def _approved_evidence(project: Path) -> dict[str, dict[str, Any]]:
    state = paper_evidence_state(project)
    return {
        row["evidence_id"]: row
        for row in state.get("rows", [])
        if row.get("status") in {"approved", "CONFIRMED"}
    }


def _candidate_requires_exact_chemical_coverage(
    candidate: dict[str, Any], evidence: dict[str, dict[str, Any]]
) -> bool:
    supporting = candidate.get("supporting_evidence_ids", [])
    if not isinstance(supporting, list):
        return False
    return any(
        EXACT_CHEMICAL_FIELD_DEPENDENCIES.intersection(
            evidence.get(evidence_id, {}).get("field_dependencies", [])
        )
        for evidence_id in supporting
    )


def _require_exact_chemical_coverage(
    project: Path,
    candidates: list[dict[str, Any]],
    evidence: dict[str, dict[str, Any]],
) -> None:
    """Keep exact synthesis candidate registration behind the 80% gate."""

    if not any(
        _candidate_requires_exact_chemical_coverage(candidate, evidence)
        for candidate in candidates
    ):
        return

    if not (project / "01_evidence/dual_source").is_dir():
        return
    try:
        studies = declared_study_ids(project)
        core_studies = [
            study_id
            for study_id in studies
            if study_source_tier(project, study_id) == "core"
        ]
    except SourceTruthError as exc:
        raise SynthesisError(exc.code) from exc
    try:
        for study_id in core_studies:
            require_honest_progressive_projection(
                project, study_id, allow_provisional=False
            )
    except ChemicalCompletionError as exc:
        raise SynthesisError(exc.code) from exc


def partition_honest_progressive_evidence(rows: object) -> dict[str, Any]:
    """Partition evidence by the only downstream uses allowed by its state."""

    normalized = _honest_progressive_rows(rows)
    exact: list[dict[str, Any]] = []
    internal: list[dict[str, Any]] = []
    limitations: list[dict[str, Any]] = []
    traceability: list[dict[str, Any]] = []
    for raw in normalized:
        row = copy.deepcopy(raw)
        row.pop("traceability_ready", None)
        row.pop("provisional", None)
        status = row.get("status")
        if status == "BLOCKED":
            row["value"] = None
            limitations.append(row)
        elif status in {"CONFIRMED", "AI_PROVISIONAL"}:
            row["provisional"] = status == "AI_PROVISIONAL"
            internal.append(row)
            if status == "CONFIRMED":
                exact.append(copy.deepcopy(row))
        traceability.append(
            {
                key: copy.deepcopy(row[key])
                for key in (
                    "study_id",
                    "molecule_id",
                    "status",
                    "source_id",
                    "pdf_locator",
                    "provenance",
                    "confidence",
                )
                if key in row and row[key] is not None
            }
        )
    return {
        "route": HONEST_PROGRESSIVE_ROUTE,
        "exact_conclusions": exact,
        "internal_comparison": internal,
        "limitation_disclosures": limitations,
        "traceability": traceability,
    }


def register_synthesis_candidates(project: Path, payload: object) -> dict[str, Any]:
    project = _root(project); protocol = comparison_protocol_state(project)
    if not protocol.get("workflow_can_continue"): raise SynthesisError("COMPARISON_PROTOCOL_NOT_APPROVED")
    if protocol.get("authoritative_run") is True:
        validate_authoritative_review_questions(protocol.get("value") or protocol)
    if not isinstance(payload, dict): raise SynthesisError("SYNTHESIS_INVALID")
    raw = payload.get("claims", [payload])
    if not isinstance(raw, list): raise SynthesisError("SYNTHESIS_INVALID")
    evidence = _approved_evidence(project)
    _require_exact_chemical_coverage(project, raw, evidence)
    current_digest = paper_evidence_state(project).get("projection_digest")
    rows = _read_jsonl(project, CLAIM_PATH); existing = {r.get("synthesis_id"): r for r in rows}
    out = []
    for candidate in raw:
        if not isinstance(candidate, dict): raise SynthesisError("SYNTHESIS_INVALID")
        row = copy.deepcopy(candidate)
        if row.get("decision") is not None:
            raise SynthesisError("SYNTHESIS_DECISION_INVALID")
        row.setdefault("schema_version", "synthesis-claim.v1"); row.setdefault("decision", None); row.setdefault("counter_evidence_ids", []); row.setdefault("single_study", False); row.setdefault("paper_evidence_projection_digest", current_digest); row.setdefault("comparison_protocol_digest", protocol.get("protocol_digest"))
        supports = row.get("supporting_evidence_ids", []); counters = row.get("counter_evidence_ids", [])
        if not isinstance(supports, list) or not supports or any(eid not in evidence for eid in supports + (counters if isinstance(counters, list) else [])): raise SynthesisError("SYNTHESIS_EVIDENCE_NOT_APPROVED")
        studies = {evidence[eid]["study_id"] for eid in supports}
        if not row.get("single_study") and len(studies) < 2: raise SynthesisError("MULTI_STUDY_SUPPORT_REQUIRED")
        if row.get("single_study") and re.search(r"\b(field|generally|consensus|universal|all)\b", str(row.get("proposition", "")), re.I): raise SynthesisError("SINGLE_STUDY_OVERGENERALIZATION")
        row["synthesis_digest"] = canonical_digest(_unsigned(row, "synthesis_digest"))
        _validate(row, "synthesis_claim.v1.schema.json")
        prior = existing.get(row.get("synthesis_id"))
        if prior is not None and prior != row: raise SynthesisError("SYNTHESIS_ID_CONFLICT")
        existing[row["synthesis_id"]] = row; out.append(row)
    merged = sorted(existing.values(), key=lambda r: r.get("synthesis_id", ""))
    with project_write_lock(project): _write_jsonl(project, CLAIM_PATH, merged)
    return {"claims": out, "status": "needs_review"}


def apply_synthesis_decision(project: Path, payload: object) -> dict[str, Any]:
    project = _root(project)
    if not isinstance(payload, dict): raise SynthesisError("SYNTHESIS_DECISION_INVALID")
    rows = _read_jsonl(project, CLAIM_PATH); sid = payload.get("synthesis_id")
    row = next((r for r in rows if r.get("synthesis_id") == sid), None)
    if row is None: raise SynthesisError("SYNTHESIS_ID_NOT_FOUND")
    if row.get("paper_evidence_projection_digest") != paper_evidence_state(project).get("projection_digest"): raise SynthesisError("SYNTHESIS_STALE")
    row["decision"] = _decision(payload, row["synthesis_digest"]); row["status"] = "approved" if row["decision"]["action"] != "reject" else "rejected"
    with project_write_lock(project): _write_jsonl(project, CLAIM_PATH, rows)
    return row


def synthesis_state(project: Path) -> dict[str, Any]:
    project = _root(project); protocol = comparison_protocol_state(project); evidence = paper_evidence_state(project)
    rows = _read_jsonl(project, CLAIM_PATH); current = evidence.get("projection_digest")
    current_protocol = protocol.get("protocol_digest")
    projected = []
    for row in rows:
        row = copy.deepcopy(row)
        if row.get("comparison_protocol_digest") != protocol.get("protocol_digest"): row.update(status="stale", reason_code="SYNTHESIS_PROTOCOL_STALE")
        elif row.get("synthesis_digest") != canonical_digest(_unsigned(row, "synthesis_digest")): row.update(status="stale", reason_code="SYNTHESIS_DIGEST_INVALID")
        elif row.get("paper_evidence_projection_digest") != current: row.update(status="stale", reason_code="SYNTHESIS_STALE")
        elif row.get("comparison_protocol_digest") != current_protocol: row.update(status="stale", reason_code="SYNTHESIS_PROTOCOL_STALE")
        elif not row.get("decision"): row.update(status="needs_review", reason_code="SYNTHESIS_REVIEW_REQUIRED")
        elif not _valid_decision(row["decision"], row["synthesis_digest"]): row.update(status="stale", reason_code="SYNTHESIS_DECISION_INVALID")
        elif row["decision"].get("action") == "reject": row.update(status="rejected", reason_code="SYNTHESIS_REJECTED")
        else: row.update(status="approved", reason_code="SYNTHESIS_APPROVED")
        projected.append(row)
    ready = bool(projected) and protocol.get("workflow_can_continue") and all(r.get("status") in {"approved", "rejected"} for r in projected) and any(r.get("status") == "approved" for r in projected)
    return {"status": "approved" if ready else "needs_review", "workflow_can_continue": ready, "reason_code": "SYNTHESIS_APPROVED" if ready else "SYNTHESIS_NOT_APPROVED", "projection_digest": canonical_digest(projected), "rows": projected}


def require_synthesis_ready(project: Path) -> str:
    state = synthesis_state(project)
    if not state["workflow_can_continue"]: raise SynthesisError(state["reason_code"])
    return str(state["projection_digest"])
