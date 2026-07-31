"""Researcher-only completeness gate for Chemical Paper molecule fields."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from review_writer.project.chemical_paper import (
    ChemicalPaperError,
    FIELD_NAMES,
    _atomic_json,
    _canonical_state_digest,
    _current_value,
    _molecule_by_index,
    _now,
    _state_path,
    _valid_resolved_smiles,
    _validate_state,
    _version_token,
    load_chemical_paper_state,
)
from review_writer.project.paper_evidence_store import PaperEvidenceStoreError, project_write_lock
from review_writer.project.source_truth import SourceTruthError, canonical_digest, declared_study_ids


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas/evidence/chemical_completion_gate.v2.schema.json"
ACTOR_TYPES = frozenset({"human_researcher", "simulated_researcher_agent"})


class ChemicalCompletionError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _validate_gate(value: dict[str, Any]) -> dict[str, Any]:
    try:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ChemicalCompletionError("CHEMICAL_COMPLETION_SCHEMA_INVALID") from exc
    if list(Draft202012Validator(schema).iter_errors(value)):
        raise ChemicalCompletionError("CHEMICAL_COMPLETION_STATE_INVALID")
    body = {key: item for key, item in value.items() if key != "gate_digest"}
    if canonical_digest(body) != value["gate_digest"]:
        raise ChemicalCompletionError("CHEMICAL_COMPLETION_STATE_INVALID")
    return value


def chemical_completion_state(project: Path, study_id: str) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    try:
        state = load_chemical_paper_state(root, study_id)
    except ChemicalPaperError as exc:
        raise ChemicalCompletionError(exc.code) from exc
    missing = {field: 0 for field in FIELD_NAMES}
    missing_rows: list[dict[str, Any]] = []
    for index, molecule in enumerate(state["molecules"]):
        for field in FIELD_NAMES:
            if _current_value(state, molecule, field) is None:
                missing[field] += 1
                missing_rows.append({
                    "molecule_index": index, "field": field,
                    "page": molecule["page_index"] + 1,
                    "bbox_normalized": molecule["normalized_bbox"],
                })
    history = [
        {
            "molecule_index": next(index for index, molecule in enumerate(state["molecules"]) if molecule["molecule_id"] == event["molecule_id"]),
            "field": event["field"], "value": event["value"],
            "actor_type": event["actor"]["actor_type"], "actor_label": event["actor"]["actor_label"],
            "reason": event["reason"], "pdf_locator": event["pdf_locator"],
            "recorded_at": event["recorded_at"],
        }
        for event in state["field_corrections"]
        if event["bound_import_digest"] == state["current_import_digest"]
    ]
    body: dict[str, Any] = {
        "schema_version": "chemical-completion-gate.v2", "project_id": root.name,
        "study_id": study_id, "molecule_count": len(state["molecules"]),
        "missing_name_count": missing["mol_idt"],
        "missing_resolved_smiles_count": missing["resolved_smiles"],
        "ai_authored_smiles_count": 0,
        "missing_fields": missing_rows, "history": history,
        "version_token": _version_token(state),
        "workflow_can_continue": not missing_rows,
    }
    return _validate_gate({**body, "gate_digest": canonical_digest(body)})


def _actor(payload: dict[str, Any]) -> dict[str, str]:
    actor_type, actor_label = payload.get("actor_type"), payload.get("actor_label")
    if actor_type not in ACTOR_TYPES or not isinstance(actor_label, str) or not actor_label.strip() or actor_label != actor_label.strip():
        raise ChemicalCompletionError("RESEARCHER_ACTOR_REQUIRED")
    return {"actor_type": actor_type, "actor_label": actor_label}


def _locator(value: object, page_count: int) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - {"page", "figure_label", "bbox"}:
        raise ChemicalCompletionError("PDF_LOCATOR_INVALID")
    page = value.get("page")
    if not isinstance(page, int) or isinstance(page, bool) or not 1 <= page <= page_count:
        raise ChemicalCompletionError("PDF_LOCATOR_INVALID")
    label = value.get("figure_label")
    if label is not None and (not isinstance(label, str) or not label.strip() or label != label.strip()):
        raise ChemicalCompletionError("PDF_LOCATOR_INVALID")
    bbox = value.get("bbox")
    if bbox is not None and (not isinstance(bbox, list) or len(bbox) != 4 or not all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in bbox)):
        raise ChemicalCompletionError("PDF_LOCATOR_INVALID")
    return copy.deepcopy(value)


def _value(field: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 20000:
        raise ChemicalCompletionError("CHEMICAL_FIELD_VALUE_INVALID")
    if field == "resolved_smiles" and not _valid_resolved_smiles(value):
        raise ChemicalCompletionError("SMILES_INVALID")
    return value


def apply_chemical_completion_batch(project: Path, study_id: str, payload: object) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    if not isinstance(payload, dict) or set(payload) != {"version_token", "actor_type", "actor_label", "corrections"}:
        raise ChemicalCompletionError("CHEMICAL_COMPLETION_BATCH_INVALID")
    actor = _actor(payload)
    corrections = payload.get("corrections")
    if not isinstance(corrections, list) or not corrections:
        raise ChemicalCompletionError("CHEMICAL_COMPLETION_BATCH_INVALID")
    try:
        with project_write_lock(root):
            state = load_chemical_paper_state(root, study_id)
            if payload.get("version_token") != _version_token(state):
                raise ChemicalCompletionError("STALE_CHEMICAL_COMPLETION")
            active = state["imports"][state["current_import_digest"]]
            normalized: list[tuple[dict[str, Any], str, str, str, dict[str, Any]]] = []
            seen: set[tuple[int, str]] = set()
            for row in corrections:
                if not isinstance(row, dict) or set(row) != {"molecule_index", "field", "value", "reason", "pdf_locator"}:
                    raise ChemicalCompletionError("CHEMICAL_COMPLETION_BATCH_INVALID")
                index, field = row.get("molecule_index"), row.get("field")
                if not isinstance(index, int) or isinstance(index, bool) or field not in FIELD_NAMES or (index, field) in seen:
                    raise ChemicalCompletionError("CHEMICAL_COMPLETION_BATCH_INVALID")
                seen.add((index, field))
                try:
                    molecule = _molecule_by_index(state, index)
                except ChemicalPaperError as exc:
                    raise ChemicalCompletionError(exc.code) from exc
                if _current_value(state, molecule, field) is not None:
                    raise ChemicalCompletionError("CHEMICAL_FIELD_ALREADY_COMPLETE")
                reason = row.get("reason")
                if not isinstance(reason, str) or not reason.strip() or reason != reason.strip():
                    raise ChemicalCompletionError("CHEMICAL_COMPLETION_REASON_REQUIRED")
                normalized.append((molecule, field, _value(field, row.get("value")), reason, _locator(row.get("pdf_locator"), active["page_count"])))
            updated = copy.deepcopy(state)
            for molecule, field, value, reason, locator in normalized:
                event = {
                    "molecule_id": molecule["molecule_id"], "field": field,
                    "prior_value": _current_value(updated, molecule, field), "value": value, "actor": actor, "reason": reason,
                    "pdf_locator": locator, "recorded_at": _now(),
                    "bound_import_digest": updated["current_import_digest"],
                    "bound_molecule_digest": molecule["molecule_digest"],
                    "prior_event_digest": updated["field_correction_head_digest"],
                }
                event["event_digest"] = canonical_digest(event)
                updated["field_corrections"].append(event)
                updated["field_correction_head_digest"] = event["event_digest"]
            updated["state_digest"] = _canonical_state_digest(updated)
            _validate_state(updated)
            _atomic_json(_state_path(root, study_id), updated)
    except PaperEvidenceStoreError as exc:
        raise ChemicalCompletionError(exc.code) from exc
    except ChemicalPaperError as exc:
        raise ChemicalCompletionError(exc.code) from exc
    state_view = chemical_completion_state(root, study_id)
    return {"status": "applied", "study_id": study_id, "applied_count": len(corrections), "version_token": state_view["version_token"], "gate_digest": state_view["gate_digest"]}


def require_chemical_completion_ready(project: Path, study_id: str) -> str:
    gate = chemical_completion_state(project, study_id)
    if not gate["workflow_can_continue"]:
        raise ChemicalCompletionError("CHEMICAL_COMPLETION_INCOMPLETE")
    return str(gate["gate_digest"])


def project_chemical_completion_state(project: Path) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    try:
        study_ids = declared_study_ids(root)
    except SourceTruthError as exc:
        raise ChemicalCompletionError(exc.code) from exc
    rows = []
    for study_id in study_ids:
        try:
            state = chemical_completion_state(root, study_id)
            rows.append({
                **state,
                "status": (
                    "current" if state["workflow_can_continue"] else "blocked"
                ),
                "ai_authored_smiles_count": 0,
            })
        except ChemicalCompletionError as exc:
            rows.append({
                "study_id": study_id,
                "status": "blocked",
                "workflow_can_continue": False,
                "reason_code": exc.code,
                "missing_name_count": 0,
                "missing_resolved_smiles_count": 0,
                "ai_authored_smiles_count": 0,
            })
    return {"schema_version": "chemical-completion-project-state.v2", "studies": rows, "workflow_can_continue": bool(rows) and all(row["workflow_can_continue"] for row in rows)}
