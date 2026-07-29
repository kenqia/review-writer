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

from .paper_evidence import PaperEvidenceError, paper_evidence_state
from .paper_evidence_store import PaperEvidenceStoreError, project_write_lock
from .source_truth import REPO_ROOT, canonical_digest
from .verification_decision import VerificationDecisionError, verification_decision

SHA256 = re.compile(r"^[0-9a-f]{64}$")
PROTOCOL_PATH = Path("02_synthesis/comparison_protocol.json")
COVERAGE_PATH = Path("02_synthesis/coverage_map.json")
CLAIM_PATH = Path("02_synthesis/synthesis_claim_projection.jsonl")


class SynthesisError(ValueError):
    def __init__(self, code: str):
        super().__init__(code); self.code = code


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


def register_comparison_protocol(project: Path, payload: object) -> dict[str, Any]:
    project = _root(project)
    if not isinstance(payload, dict): raise SynthesisError("COMPARISON_PROTOCOL_INVALID")
    value = copy.deepcopy(payload); value.setdefault("schema_version", "comparison-protocol.v1")
    value.setdefault("decision", None)
    required = {"comparison_id", "comparison_objects", "axes", "normalization_rules", "missing_value_policy", "incomparability_rules", "counterevidence_rules", "claim_strength"}
    if not required.issubset(value): raise SynthesisError("COMPARISON_PROTOCOL_INVALID")
    try:
        evidence = paper_evidence_state(project)
    except PaperEvidenceError as exc:
        raise SynthesisError("PAPER_EVIDENCE_NOT_READY") from exc
    value["paper_evidence_projection_digest"] = evidence.get("projection_digest")
    _validate(value, "comparison_protocol.v1.schema.json", "COMPARISON_PROTOCOL_INVALID")
    value["protocol_digest"] = canonical_digest(value)
    with project_write_lock(project): _write(project, PROTOCOL_PATH, value)
    return value


def apply_comparison_protocol_decision(project: Path, payload: object) -> dict[str, Any]:
    project = _root(project); protocol = _read_json(project, PROTOCOL_PATH)
    if not isinstance(protocol, dict): raise SynthesisError("COMPARISON_PROTOCOL_NOT_FOUND")
    if not isinstance(payload, dict): raise SynthesisError("COMPARISON_PROTOCOL_DECISION_INVALID")
    digest = protocol.get("protocol_digest")
    if not isinstance(digest, str): raise SynthesisError("COMPARISON_PROTOCOL_INVALID")
    protocol["decision"] = _decision(payload, digest)
    protocol["protocol_digest"] = canonical_digest({k: v for k, v in protocol.items() if k != "protocol_digest"})
    with project_write_lock(project): _write(project, PROTOCOL_PATH, protocol)
    return protocol


def comparison_protocol_state(project: Path) -> dict[str, Any]:
    value = _read_json(_root(project), PROTOCOL_PATH)
    if not isinstance(value, dict): return {"status": "needs_review", "workflow_can_continue": False, "reason_code": "COMPARISON_PROTOCOL_NOT_APPROVED"}
    try: _validate(value, "comparison_protocol.v1.schema.json", "COMPARISON_PROTOCOL_INVALID")
    except SynthesisError as exc: return {"status": "needs_review", "workflow_can_continue": False, "reason_code": exc.code}
    digest = value.get("protocol_digest")
    unsigned = {k: v for k, v in value.items() if k != "protocol_digest"}
    if not isinstance(digest, str) or digest != canonical_digest(unsigned):
        return {"status": "needs_review", "workflow_can_continue": False, "reason_code": "COMPARISON_PROTOCOL_STALE"}
    decision = value.get("decision") or {}
    ok = decision.get("action") == "approve" and value.get("paper_evidence_projection_digest") == paper_evidence_state(_root(project)).get("projection_digest")
    return {"status": "approved" if ok else "needs_review", "workflow_can_continue": ok, "reason_code": "COMPARISON_PROTOCOL_APPROVED" if ok else "COMPARISON_PROTOCOL_NOT_APPROVED", "protocol_digest": value.get("protocol_digest"), "value": value}


def register_coverage_map(project: Path, payload: object) -> dict[str, Any]:
    project = _root(project)
    if not isinstance(payload, dict): raise SynthesisError("COVERAGE_MAP_INVALID")
    value = copy.deepcopy(payload); value.setdefault("schema_version", "coverage-map.v1"); value.setdefault("corpus_kind", "calibration_corpus"); value.setdefault("known_omissions", [])
    _validate(value, "coverage_map.v1.schema.json", "COVERAGE_MAP_INVALID")
    with project_write_lock(project): _write(project, COVERAGE_PATH, value)
    return value


def _approved_evidence(project: Path) -> dict[str, dict[str, Any]]:
    state = paper_evidence_state(project)
    return {row["evidence_id"]: row for row in state.get("rows", []) if row.get("status") == "approved"}


def register_synthesis_candidates(project: Path, payload: object) -> dict[str, Any]:
    project = _root(project); protocol = comparison_protocol_state(project)
    if not protocol.get("workflow_can_continue"): raise SynthesisError("COMPARISON_PROTOCOL_NOT_APPROVED")
    if not isinstance(payload, dict): raise SynthesisError("SYNTHESIS_INVALID")
    raw = payload.get("claims", [payload])
    if not isinstance(raw, list): raise SynthesisError("SYNTHESIS_INVALID")
    evidence = _approved_evidence(project)
    current_digest = paper_evidence_state(project).get("projection_digest")
    rows = _read_jsonl(project, CLAIM_PATH); existing = {r.get("synthesis_id"): r for r in rows}
    out = []
    for candidate in raw:
        if not isinstance(candidate, dict): raise SynthesisError("SYNTHESIS_INVALID")
        row = copy.deepcopy(candidate); row.setdefault("schema_version", "synthesis-claim.v1"); row.setdefault("decision", None); row.setdefault("counter_evidence_ids", []); row.setdefault("single_study", False); row.setdefault("paper_evidence_projection_digest", current_digest); row.setdefault("comparison_protocol_digest", protocol.get("protocol_digest"))
        supports = row.get("supporting_evidence_ids", []); counters = row.get("counter_evidence_ids", [])
        if not isinstance(supports, list) or not supports or any(eid not in evidence for eid in supports + (counters if isinstance(counters, list) else [])): raise SynthesisError("SYNTHESIS_EVIDENCE_NOT_APPROVED")
        studies = {evidence[eid]["study_id"] for eid in supports}
        if not row.get("single_study") and len(studies) < 2: raise SynthesisError("MULTI_STUDY_SUPPORT_REQUIRED")
        if row.get("single_study") and re.search(r"\b(field|generally|consensus|universal|all)\b", str(row.get("proposition", "")), re.I): raise SynthesisError("SINGLE_STUDY_OVERGENERALIZATION")
        _validate(row, "synthesis_claim.v1.schema.json")
        row["synthesis_digest"] = canonical_digest(row)
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
    row["synthesis_digest"] = canonical_digest({k: v for k, v in row.items() if k not in {"synthesis_digest", "status", "reason_code"}})
    with project_write_lock(project): _write_jsonl(project, CLAIM_PATH, rows)
    return row


def synthesis_state(project: Path) -> dict[str, Any]:
    project = _root(project); protocol = comparison_protocol_state(project); evidence = paper_evidence_state(project)
    rows = _read_jsonl(project, CLAIM_PATH); current = evidence.get("projection_digest")
    projected = []
    for row in rows:
        row = copy.deepcopy(row)
        if row.get("synthesis_digest") != canonical_digest({k: v for k, v in row.items() if k not in {"synthesis_digest", "status", "reason_code"}}): row.update(status="stale", reason_code="SYNTHESIS_DIGEST_INVALID")
        elif row.get("paper_evidence_projection_digest") != current: row.update(status="stale", reason_code="SYNTHESIS_STALE")
        elif not row.get("decision"): row.update(status="needs_review", reason_code="SYNTHESIS_REVIEW_REQUIRED")
        elif row["decision"].get("action") == "reject": row.update(status="rejected", reason_code="SYNTHESIS_REJECTED")
        else: row.update(status="approved", reason_code="SYNTHESIS_APPROVED")
        projected.append(row)
    ready = bool(projected) and protocol.get("workflow_can_continue") and all(r.get("status") in {"approved", "rejected"} for r in projected) and any(r.get("status") == "approved" for r in projected)
    return {"status": "approved" if ready else "needs_review", "workflow_can_continue": ready, "reason_code": "SYNTHESIS_APPROVED" if ready else "SYNTHESIS_NOT_APPROVED", "projection_digest": canonical_digest(projected), "rows": projected}


def require_synthesis_ready(project: Path) -> str:
    state = synthesis_state(project)
    if not state["workflow_can_continue"]: raise SynthesisError(state["reason_code"])
    return str(state["projection_digest"])
