"""Typed, hash-bound single-paper evidence registration and review."""

from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator

from review_writer.project.parse_quality import (
    ParseQualityError,
    build_parse_quality_gate,
    parse_quality_state,
)
from review_writer.project.source_truth import (
    REPO_ROOT,
    SourceTruthError,
    canonical_digest,
    declared_study_ids,
    load_source_truth_bundle,
    source_truth_asset,
)
from review_writer.project.verification_decision import (
    VerificationDecisionError,
    verification_decision,
)
from review_writer.project.paper_evidence_store import (
    PaperEvidenceStoreError,
    project_write_lock,
)


PAPER_EVIDENCE_SCHEMA = REPO_ROOT / "schemas/evidence/paper_evidence.v1.schema.json"
EVIDENCE_DECISION_SCHEMA = REPO_ROOT / "schemas/evidence/evidence_decision.v1.schema.json"
DECISIONS_PATH = Path("01_evidence/paper_evidence_decisions.jsonl")
PROJECTION_PATH = Path("01_evidence/paper_evidence_projection.jsonl")
EPISTEMIC_TYPES = frozenset(
    {"experimental_observation", "author_interpretation", "proposed_mechanism"}
)
DECISION_ACTIONS = frozenset({"approve", "revise_and_approve", "reject"})
ACTOR_TYPES = frozenset({"human_researcher", "simulated_researcher_agent"})
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class PaperEvidenceError(ValueError):
    """A stable, researcher-safe paper evidence failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@contextmanager
def _mutation(project: Path):
    project = _project_root(project)
    try:
        with project_write_lock(project):
            yield project
    except PaperEvidenceStoreError as exc:
        raise PaperEvidenceError(exc.code) from exc


def _project_root(project: Path) -> Path:
    supplied = Path(project)
    if supplied.is_symlink() or not supplied.is_dir():
        raise PaperEvidenceError("PROJECT_INVALID")
    try:
        return supplied.resolve(strict=True)
    except OSError as exc:
        raise PaperEvidenceError("PROJECT_INVALID") from exc


def _identifier(value: object, code: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or "\0" in value
        or len(value) > 240
    ):
        raise PaperEvidenceError(code)
    return value


def _load_schema(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PaperEvidenceError("PAPER_EVIDENCE_SCHEMA_INVALID") from exc
    if not isinstance(value, dict):
        raise PaperEvidenceError("PAPER_EVIDENCE_SCHEMA_INVALID")
    return value


def _validate_schema(value: object, path: Path, code: str) -> None:
    errors = sorted(
        Draft202012Validator(_load_schema(path)).iter_errors(value),
        key=lambda error: [str(part) for part in error.path],
    )
    if errors:
        raise PaperEvidenceError(code)


def _ensure_output_parent(project: Path, path: Path) -> None:
    relative = path.relative_to(project)
    current = project
    for part in relative.parts[:-1]:
        current = current / part
        if os.path.lexists(current) and current.is_symlink():
            raise PaperEvidenceError("PAPER_EVIDENCE_PATH_INVALID")
        current.mkdir(exist_ok=True)
        if not current.is_dir() or current.is_symlink():
            raise PaperEvidenceError("PAPER_EVIDENCE_PATH_INVALID")


def _atomic_text(project: Path, path: Path, value: str) -> None:
    _ensure_output_parent(project, path)
    if os.path.lexists(path) and (path.is_symlink() or not path.is_file()):
        raise PaperEvidenceError("PAPER_EVIDENCE_PATH_INVALID")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    except (OSError, UnicodeError) as exc:
        raise PaperEvidenceError("PAPER_EVIDENCE_WRITE_FAILED") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _atomic_json(project: Path, path: Path, value: object) -> None:
    try:
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        ) + "\n"
    except (TypeError, ValueError) as exc:
        raise PaperEvidenceError("PAPER_EVIDENCE_INVALID") from exc
    _atomic_text(project, path, serialized)


def _atomic_jsonl(project: Path, path: Path, rows: Iterable[dict[str, Any]]) -> None:
    try:
        serialized = "".join(
            json.dumps(
                row,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
            for row in rows
        )
    except (TypeError, ValueError) as exc:
        raise PaperEvidenceError("PAPER_EVIDENCE_INVALID") from exc
    _atomic_text(project, path, serialized)


def _read_json(path: Path, missing: str, invalid: str) -> Any:
    if not path.is_file() or path.is_symlink():
        if os.path.lexists(path):
            raise PaperEvidenceError("PAPER_EVIDENCE_PATH_INVALID")
        raise PaperEvidenceError(missing)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PaperEvidenceError(invalid) from exc


def _read_jsonl(path: Path, *, missing_ok: bool = False) -> list[dict[str, Any]]:
    if not path.is_file() or path.is_symlink():
        if os.path.lexists(path):
            raise PaperEvidenceError("PAPER_EVIDENCE_PATH_INVALID")
        if missing_ok:
            return []
        raise PaperEvidenceError("PAPER_EVIDENCE_MISSING")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        rows = [json.loads(line) for line in lines if line.strip()]
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PaperEvidenceError("PAPER_EVIDENCE_INVALID") from exc
    if not all(isinstance(row, dict) for row in rows):
        raise PaperEvidenceError("PAPER_EVIDENCE_INVALID")
    return rows


def _candidate_path(project: Path, study_id: str) -> Path:
    return project / "01_evidence" / _identifier(study_id, "STUDY_ID_INVALID") / "paper_evidence_candidates.json"


def _source(project: Path, study_id: str, source_id: str) -> dict[str, Any]:
    source = _source_descriptor(project, study_id, source_id)
    try:
        source_truth_asset(project, study_id, source_id, "pdf")
    except SourceTruthError as exc:
        raise PaperEvidenceError(exc.code) from exc
    return source


def _source_descriptor(project: Path, study_id: str, source_id: str) -> dict[str, Any]:
    try:
        bundle = load_source_truth_bundle(project, study_id)
    except SourceTruthError as exc:
        raise PaperEvidenceError(exc.code) from exc
    matches = [
        row
        for row in bundle.get("sources", [])
        if isinstance(row, dict) and row.get("source_id") == source_id
    ]
    if len(matches) != 1:
        raise PaperEvidenceError("SOURCE_ID_NOT_FOUND")
    return matches[0]


def current_source_pdf_sha256(
    project: Path,
    study_id: str | None = None,
    source_id: str | None = None,
) -> str:
    """Return the verified current PDF digest when the requested source is unique."""

    project = _project_root(project)
    try:
        studies = declared_study_ids(project)
    except SourceTruthError as exc:
        raise PaperEvidenceError(exc.code) from exc
    if study_id is None:
        if len(studies) != 1:
            raise PaperEvidenceError("STUDY_ID_REQUIRED")
        study_id = studies[0]
    _identifier(study_id, "STUDY_ID_INVALID")
    if source_id is None:
        try:
            bundle = load_source_truth_bundle(project, study_id)
        except SourceTruthError as exc:
            raise PaperEvidenceError(exc.code) from exc
        sources = bundle.get("sources", [])
        if not isinstance(sources, list) or len(sources) != 1 or not isinstance(sources[0], dict):
            raise PaperEvidenceError("SOURCE_ID_REQUIRED")
        source_id = sources[0].get("source_id")
    source_id = _identifier(source_id, "SOURCE_ID_INVALID")
    source = _source(project, study_id, source_id)
    return str(source["pdf"]["sha256"])


def _parse_state(project: Path, study_id: str) -> dict[str, Any]:
    try:
        state = parse_quality_state(project, study_id)
    except ParseQualityError as exc:
        raise PaperEvidenceError(exc.code) from exc
    if not isinstance(state, dict) or not isinstance(state.get("objects"), list):
        raise PaperEvidenceError("PARSE_QUALITY_INVALID")
    return state


def _candidate_digest(row: dict[str, Any]) -> str:
    return canonical_digest(
        {key: value for key, value in row.items() if key not in {"candidate_digest", "decision"}}
    )


def _normalize_string_list(value: object, code: str) -> list[str]:
    if (
        not isinstance(value, list)
        or len(value) > 500
        or not all(
            isinstance(item, str) and item.strip() == item and 0 < len(item) <= 20000
            for item in value
        )
        or len(value) != len(set(value))
    ):
        raise PaperEvidenceError(code)
    return list(value)


def _normalize_locator(value: object, expected_mode: str) -> dict[str, Any]:
    required = {"source_mode", "page", "section_or_item", "figure_or_table", "exact_quote"}
    if not isinstance(value, dict) or set(value) != required:
        raise PaperEvidenceError("LOCATOR_INVALID")
    page = value.get("page")
    section = value.get("section_or_item")
    if (
        value.get("source_mode") != expected_mode
        or not isinstance(page, int)
        or isinstance(page, bool)
        or page < 1
        or not isinstance(section, str)
        or not section.strip()
        or section != section.strip()
    ):
        raise PaperEvidenceError("LOCATOR_INVALID")
    for key in ("figure_or_table", "exact_quote"):
        item = value.get(key)
        if item is not None and (
            not isinstance(item, str) or not item.strip() or item != item.strip() or len(item) > 20000
        ):
            raise PaperEvidenceError("LOCATOR_INVALID")
    return copy.deepcopy(value)


def _normalize_candidate(
    project: Path,
    study_id: str,
    payload: object,
    *,
    source_mode: str,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise PaperEvidenceError("PAPER_EVIDENCE_INVALID")
    allowed = {
        "evidence_id",
        "study_id",
        "source_id",
        "epistemic_type",
        "statement",
        "locator",
        "reported_conditions",
        "quantitative_results",
        "limitations",
        "mechanism_grade",
        "risk_classes",
        "bound_parse_object_digests",
        "source_pdf_sha256",
        "candidate_digest",
        "decision",
    }
    if not set(payload).issubset(allowed):
        raise PaperEvidenceError("PAPER_EVIDENCE_UNKNOWN_FIELD")
    if "epistemic_type" not in payload:
        raise PaperEvidenceError("EPISTEMIC_TYPE_REQUIRED")
    if payload.get("epistemic_type") not in EPISTEMIC_TYPES:
        raise PaperEvidenceError("EPISTEMIC_TYPE_INVALID")
    supplied_study = payload.get("study_id", study_id)
    if supplied_study != study_id:
        raise PaperEvidenceError("STUDY_ID_MISMATCH")
    evidence_id = _identifier(payload.get("evidence_id"), "EVIDENCE_ID_INVALID")
    source_id = _identifier(payload.get("source_id"), "SOURCE_ID_INVALID")
    statement = payload.get("statement")
    if (
        not isinstance(statement, str)
        or not statement.strip()
        or statement != statement.strip()
        or len(statement) > 20000
    ):
        raise PaperEvidenceError("STATEMENT_INVALID")
    locator = _normalize_locator(payload.get("locator"), source_mode)
    mechanism_grade = payload.get("mechanism_grade")
    if mechanism_grade not in {
        "not_applicable",
        "proposal",
        "indirect_support",
        "direct_support",
    }:
        raise PaperEvidenceError("MECHANISM_GRADE_INVALID")
    state = _parse_state(project, study_id)
    objects = state["objects"]
    current_digests = {
        row.get("object_digest")
        for row in objects
        if isinstance(row, dict) and isinstance(row.get("object_digest"), str)
    }
    supplied_digests = payload.get("bound_parse_object_digests")
    source_descriptor = _source_descriptor(project, study_id, source_id)
    current_objects = {
        row.get("object_digest"): row
        for row in objects
        if isinstance(row, dict) and isinstance(row.get("object_digest"), str)
    }
    if supplied_digests is None:
        bound_digests = (
            sorted(
                digest
                for digest, row in current_objects.items()
                if row.get("source_id") == source_id
            )
            if source_mode == "parsed_candidate"
            else []
        )
    else:
        bound_digests = _normalize_string_list(supplied_digests, "PARSE_OBJECT_DIGESTS_INVALID")
        if not all(SHA256_RE.fullmatch(value) for value in bound_digests):
            raise PaperEvidenceError("PARSE_OBJECT_DIGESTS_INVALID")
        bound_digests.sort()
    if source_mode == "parsed_candidate":
        if not state.get("automatic_extraction_allowed"):
            raise PaperEvidenceError("PARSED_EVIDENCE_NOT_ALLOWED")
        if not bound_digests or not set(bound_digests).issubset(current_digests):
            raise PaperEvidenceError("PARSE_OBJECT_DIGESTS_STALE")
        if any(
            current_objects[digest].get("source_id") != source_id
            for digest in bound_digests
        ):
            raise PaperEvidenceError("PARSE_OBJECT_SOURCE_MISMATCH")
    elif bound_digests:
        raise PaperEvidenceError("MANUAL_PDF_PARSE_BINDING_INVALID")
    source_sha256 = current_source_pdf_sha256(project, study_id, source_id)
    if locator["page"] > source_descriptor["page_count"]:
        raise PaperEvidenceError("LOCATOR_PAGE_INVALID")
    supplied_sha256 = payload.get("source_pdf_sha256")
    if supplied_sha256 is not None and supplied_sha256 != source_sha256:
        raise PaperEvidenceError("SOURCE_PDF_STALE")
    if payload.get("decision") is not None:
        raise PaperEvidenceError("PAPER_EVIDENCE_DECISION_FORBIDDEN")
    row: dict[str, Any] = {
        "evidence_id": evidence_id,
        "study_id": study_id,
        "source_id": source_id,
        "epistemic_type": payload["epistemic_type"],
        "statement": statement,
        "locator": locator,
        "reported_conditions": _normalize_string_list(
            payload.get("reported_conditions"), "REPORTED_CONDITIONS_INVALID"
        ),
        "quantitative_results": _normalize_string_list(
            payload.get("quantitative_results"), "QUANTITATIVE_RESULTS_INVALID"
        ),
        "limitations": _normalize_string_list(payload.get("limitations"), "LIMITATIONS_INVALID"),
        "mechanism_grade": mechanism_grade,
        "risk_classes": _normalize_string_list(payload.get("risk_classes"), "RISK_CLASSES_INVALID"),
        "bound_parse_object_digests": bound_digests,
        "source_pdf_sha256": source_sha256,
        "candidate_digest": "",
        "decision": None,
    }
    row["candidate_digest"] = _candidate_digest(row)
    supplied_digest = payload.get("candidate_digest")
    if supplied_digest is not None and supplied_digest != row["candidate_digest"]:
        raise PaperEvidenceError("CANDIDATE_DIGEST_MISMATCH")
    _validate_schema(row, PAPER_EVIDENCE_SCHEMA, "PAPER_EVIDENCE_SCHEMA_INVALID")
    return row


def _candidate_rows(payload: object) -> list[object]:
    if isinstance(payload, dict) and set(payload) == {"candidates"}:
        candidates = payload["candidates"]
        if not isinstance(candidates, list) or not candidates:
            raise PaperEvidenceError("PAPER_EVIDENCE_INVALID")
        return list(candidates)
    return [payload]


def _load_candidates(project: Path, study_id: str, *, missing_ok: bool = False) -> list[dict[str, Any]]:
    path = _candidate_path(project, study_id)
    if missing_ok and not os.path.lexists(path):
        return []
    payload = _read_json(path, "PAPER_EVIDENCE_MISSING", "PAPER_EVIDENCE_INVALID")
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema_version", "study_id", "candidates"}
        or payload.get("schema_version") != "paper-evidence-candidate-set.v1"
        or payload.get("study_id") != study_id
        or not isinstance(payload.get("candidates"), list)
        or not payload["candidates"]
    ):
        raise PaperEvidenceError("PAPER_EVIDENCE_INVALID")
    seen: set[str] = set()
    for row in payload["candidates"]:
        _validate_persisted_candidate(project, study_id, row)
        evidence_id = row.get("evidence_id")
        if evidence_id in seen:
            raise PaperEvidenceError("EVIDENCE_ID_DUPLICATE")
        seen.add(evidence_id)
    return copy.deepcopy(payload["candidates"])


def _validate_persisted_candidate(
    project: Path,
    study_id: str,
    row: object,
) -> None:
    _validate_schema(row, PAPER_EVIDENCE_SCHEMA, "PAPER_EVIDENCE_SCHEMA_INVALID")
    if not isinstance(row, dict):
        raise PaperEvidenceError("PAPER_EVIDENCE_SCHEMA_INVALID")
    if row.get("study_id") != study_id:
        raise PaperEvidenceError("PAPER_EVIDENCE_STUDY_MISMATCH")
    _identifier(row.get("evidence_id"), "EVIDENCE_ID_INVALID")
    _identifier(row.get("study_id"), "STUDY_ID_INVALID")
    _identifier(row.get("source_id"), "SOURCE_ID_INVALID")
    if not isinstance(row.get("statement"), str) or row["statement"] != row["statement"].strip():
        raise PaperEvidenceError("STATEMENT_INVALID")
    _normalize_locator(row.get("locator"), row["locator"]["source_mode"])
    for key, code in (
        ("reported_conditions", "REPORTED_CONDITIONS_INVALID"),
        ("quantitative_results", "QUANTITATIVE_RESULTS_INVALID"),
        ("limitations", "LIMITATIONS_INVALID"),
        ("risk_classes", "RISK_CLASSES_INVALID"),
    ):
        _normalize_string_list(row.get(key), code)
    _source_descriptor(project, study_id, row["source_id"])
    if row["locator"]["source_mode"] == "parsed_candidate":
        if not row["bound_parse_object_digests"]:
            raise PaperEvidenceError("PARSE_OBJECT_DIGESTS_INVALID")
    elif row["bound_parse_object_digests"]:
        raise PaperEvidenceError("MANUAL_PDF_PARSE_BINDING_INVALID")
    if row.get("decision") is not None:
        raise PaperEvidenceError("PAPER_EVIDENCE_DECISION_FORBIDDEN")
    if _candidate_digest(row) != row.get("candidate_digest"):
        raise PaperEvidenceError("CANDIDATE_DIGEST_MISMATCH")


def _check_candidate_id_conflicts(
    project: Path,
    study_id: str,
    candidates: list[dict[str, Any]],
) -> None:
    ids = [row["evidence_id"] for row in candidates]
    if len(ids) != len(set(ids)):
        raise PaperEvidenceError("EVIDENCE_ID_DUPLICATE")
    try:
        declared = declared_study_ids(project)
    except SourceTruthError as exc:
        raise PaperEvidenceError(exc.code) from exc
    for other_study_id in declared:
        if other_study_id == study_id:
            continue
        for previous in _load_candidates(project, other_study_id, missing_ok=True):
            if previous["evidence_id"] in ids:
                raise PaperEvidenceError("EVIDENCE_ID_DUPLICATE")
    existing = _load_candidates(project, study_id, missing_ok=True)
    existing_by_id = {row["evidence_id"]: row for row in existing}
    for row in candidates:
        previous = existing_by_id.get(row["evidence_id"])
        if previous is not None and previous != row:
            raise PaperEvidenceError("EVIDENCE_ID_CONFLICT")


def _merge_candidates(
    project: Path,
    study_id: str,
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    _check_candidate_id_conflicts(project, study_id, candidates)
    existing = _load_candidates(project, study_id, missing_ok=True)
    by_id = {row["evidence_id"]: row for row in existing}
    for row in candidates:
        previous = by_id.get(row["evidence_id"])
        if previous is not None and previous != row:
            raise PaperEvidenceError("EVIDENCE_ID_CONFLICT")
        by_id[row["evidence_id"]] = row
    merged = sorted(by_id.values(), key=lambda row: row["evidence_id"])
    _atomic_json(
        project,
        _candidate_path(project, study_id),
        {
            "schema_version": "paper-evidence-candidate-set.v1",
            "study_id": study_id,
            "candidates": merged,
        },
    )
    return merged


def register_paper_evidence_candidates(
    project: Path,
    study_id: str,
    payload: object,
) -> dict[str, Any]:
    """Register strict parsed candidates without granting approval."""

    project = _project_root(project)
    study_id = _identifier(study_id, "STUDY_ID_INVALID")
    raw_candidates = _candidate_rows(payload)
    # Validate before creating the lockfile so rejected cross-source input is byte-preserving.
    [
        _normalize_candidate(project, study_id, row, source_mode="parsed_candidate")
        for row in raw_candidates
    ]
    candidates = [
        _normalize_candidate(project, study_id, row, source_mode="parsed_candidate")
        for row in raw_candidates
    ]
    _check_candidate_id_conflicts(project, study_id, candidates)
    with _mutation(project) as project:
        candidates = [
            _normalize_candidate(project, study_id, row, source_mode="parsed_candidate")
            for row in raw_candidates
        ]
        merged = _merge_candidates(project, study_id, candidates)
        state = _paper_evidence_state(project, persist=True)
        return {
            "candidate_count": len(merged),
            "registered_count": len(candidates),
            "status": "needs_review",
            "study_id": study_id,
            "candidates": copy.deepcopy(candidates),
            "project_status": state["status"],
        }


def register_manual_pdf_evidence(project: Path, payload: object) -> dict[str, Any]:
    """Register one researcher-created locator against the verified original PDF."""

    project = _project_root(project)
    if not isinstance(payload, dict):
        raise PaperEvidenceError("PAPER_EVIDENCE_INVALID")
    study_id = _identifier(payload.get("study_id"), "STUDY_ID_INVALID")
    prevalidated = _normalize_candidate(
        project, study_id, payload, source_mode="original_pdf_manual"
    )
    _check_candidate_id_conflicts(project, study_id, [prevalidated])
    with _mutation(project) as project:
        state = _parse_state(project, study_id)
        actions = {
            row.get("decision", {}).get("action")
            for row in state["objects"]
            if isinstance(row, dict) and isinstance(row.get("decision"), dict)
        }
        if (
            not state.get("workflow_can_continue")
            or state.get("automatic_extraction_allowed")
            or "pdf_locator_only" not in actions
        ):
            raise PaperEvidenceError("MANUAL_PDF_EVIDENCE_NOT_ALLOWED")
        row = _normalize_candidate(project, study_id, payload, source_mode="original_pdf_manual")
        _merge_candidates(project, study_id, [row])
        _paper_evidence_state(project, persist=True)
        return copy.deepcopy(row)


def _validate_decision_event(row: object) -> dict[str, Any]:
    _validate_schema(row, EVIDENCE_DECISION_SCHEMA, "EVIDENCE_DECISION_SCHEMA_INVALID")
    assert isinstance(row, dict)
    decision = row["decision"]
    if (
        decision.get("bound_object_digest") != row.get("candidate_digest")
        or decision.get("action") not in DECISION_ACTIONS
    ):
        raise PaperEvidenceError("EVIDENCE_DECISION_BINDING_INVALID")
    return row


def _load_decisions(project: Path) -> list[dict[str, Any]]:
    rows = _read_jsonl(project / DECISIONS_PATH, missing_ok=True)
    for row in rows:
        _validate_decision_event(row)
    return rows


def _candidate_index(project: Path) -> dict[str, dict[str, Any]]:
    try:
        studies = declared_study_ids(project)
    except SourceTruthError as exc:
        raise PaperEvidenceError(exc.code) from exc
    result: dict[str, dict[str, Any]] = {}
    for study_id in studies:
        for row in _load_candidates(project, study_id, missing_ok=True):
            evidence_id = row["evidence_id"]
            if evidence_id in result:
                raise PaperEvidenceError("EVIDENCE_ID_DUPLICATE")
            result[evidence_id] = row
    return result


def _normalize_decision_payload(
    candidate: dict[str, Any], payload: object
) -> tuple[dict[str, Any], dict[str, Any]]:
    required = {
        "evidence_id",
        "candidate_digest",
        "bound_parse_object_digests",
        "source_pdf_sha256",
        "action",
        "reason",
    }
    optional = {"replacement_statement", "actor_type", "actor_label"}
    if (
        not isinstance(payload, dict)
        or not required.issubset(payload)
        or not set(payload).issubset(required | optional)
        or (("actor_type" in payload) != ("actor_label" in payload))
    ):
        raise PaperEvidenceError("EVIDENCE_DECISION_INVALID")
    action = payload.get("action")
    reason = payload.get("reason")
    replacement = payload.get("replacement_statement")
    actor_type = payload.get("actor_type", "human_researcher")
    actor_label = payload.get("actor_label", "local-researcher")
    bound_digests = payload.get("bound_parse_object_digests")
    if (
        action not in DECISION_ACTIONS
        or not isinstance(reason, str)
        or not reason.strip()
        or reason != reason.strip()
        or len(reason) > 2000
        or actor_type not in ACTOR_TYPES
        or not isinstance(actor_label, str)
        or not actor_label.strip()
        or actor_label != actor_label.strip()
        or len(actor_label) > 200
        or not isinstance(bound_digests, list)
        or bound_digests != candidate["bound_parse_object_digests"]
        or payload.get("source_pdf_sha256") != candidate["source_pdf_sha256"]
        or payload.get("candidate_digest") != candidate["candidate_digest"]
    ):
        raise PaperEvidenceError("EVIDENCE_DECISION_STALE")
    if action == "revise_and_approve":
        if (
            not isinstance(replacement, str)
            or not replacement.strip()
            or replacement != replacement.strip()
            or len(replacement) > 20000
        ):
            raise PaperEvidenceError("REPLACEMENT_STATEMENT_REQUIRED")
    elif replacement is not None:
        raise PaperEvidenceError("REPLACEMENT_STATEMENT_FORBIDDEN")
    try:
        decision = verification_decision(
            actor_type=actor_type,
            actor_label=actor_label,
            action=action,
            reason=reason,
            bound_object_digest=candidate["candidate_digest"],
        )
    except VerificationDecisionError as exc:
        raise PaperEvidenceError("EVIDENCE_DECISION_INVALID") from exc
    event = {
        "schema_version": "paper-evidence-decision.v1",
        "evidence_id": candidate["evidence_id"],
        "study_id": candidate["study_id"],
        "candidate_digest": candidate["candidate_digest"],
        "bound_parse_object_digests": list(candidate["bound_parse_object_digests"]),
        "source_pdf_sha256": candidate["source_pdf_sha256"],
        "replacement_statement": replacement,
        "decision": decision,
    }
    _validate_decision_event(event)
    semantic = {
        key: value
        for key, value in event.items()
        if key != "decision"
    }
    semantic["decision"] = {
        key: value for key, value in decision.items() if key != "decided_at"
    }
    return event, semantic


def apply_paper_evidence_decision(project: Path, payload: object) -> dict[str, Any]:
    """Append one current, hash-bound human decision and rebuild the projection."""

    project = _project_root(project)
    if not isinstance(payload, dict):
        raise PaperEvidenceError("EVIDENCE_DECISION_INVALID")
    with _mutation(project) as project:
        evidence_id = _identifier(payload.get("evidence_id"), "EVIDENCE_ID_INVALID")
        candidates = _candidate_index(project)
        candidate = candidates.get(evidence_id)
        if candidate is None:
            raise PaperEvidenceError("EVIDENCE_ID_NOT_FOUND")
        freshness, _ = _freshness(project, candidate)
        if not freshness:
            raise PaperEvidenceError("PAPER_EVIDENCE_STALE")
        event, semantic = _normalize_decision_payload(candidate, payload)
        decisions = _load_decisions(project)
        prior_for_evidence = [
            row for row in decisions if row.get("evidence_id") == evidence_id
        ]
        if prior_for_evidence:
            previous = prior_for_evidence[-1]
            previous_semantic = {key: value for key, value in previous.items() if key != "decision"}
            previous_semantic["decision"] = {
                key: value for key, value in previous["decision"].items() if key != "decided_at"
            }
            if previous.get("evidence_id") == evidence_id and previous_semantic == semantic:
                state = _paper_evidence_state(project, persist=True)
                return next(row for row in state["rows"] if row["evidence_id"] == evidence_id)
        decisions.append(event)
        _atomic_jsonl(project, project / DECISIONS_PATH, decisions)
        state = _paper_evidence_state(project, persist=True)
        return next(row for row in state["rows"] if row["evidence_id"] == evidence_id)


def _freshness(project: Path, candidate: dict[str, Any]) -> tuple[bool, str | None]:
    try:
        source = _source(project, candidate["study_id"], candidate["source_id"])
        current_sha = str(source["pdf"]["sha256"])
        state = _parse_state(project, candidate["study_id"])
    except PaperEvidenceError as exc:
        return False, exc.code
    if candidate["source_pdf_sha256"] != current_sha:
        return False, "SOURCE_PDF_STALE"
    if candidate["locator"]["page"] > source["page_count"]:
        return False, "LOCATOR_PAGE_STALE"
    if candidate["locator"]["source_mode"] == "original_pdf_manual":
        return (not candidate["bound_parse_object_digests"], "MANUAL_PDF_PARSE_BINDING_INVALID")
    reviewed_objects = {
        row.get("object_digest"): row
        for row in state["objects"]
        if isinstance(row, dict) and isinstance(row.get("object_digest"), str)
    }
    if state.get("status") == "stale":
        try:
            current_bundle = load_source_truth_bundle(project, candidate["study_id"])
            current_gate = build_parse_quality_gate(project, current_bundle)
        except (ParseQualityError, SourceTruthError) as exc:
            return False, exc.code
        current_rows = current_gate["objects"]
    else:
        current_rows = state["objects"]
    current_objects = {
        row.get("object_digest"): row
        for row in current_rows
        if isinstance(row, dict) and isinstance(row.get("object_digest"), str)
    }
    dependencies = set(candidate["bound_parse_object_digests"])
    if not dependencies.issubset(current_objects) or not dependencies.issubset(reviewed_objects):
        return False, "PARSE_OBJECT_DIGESTS_STALE"
    for digest in dependencies:
        if current_objects[digest].get("source_id") != candidate["source_id"]:
            return False, "PARSE_OBJECT_SOURCE_MISMATCH"
        decision = reviewed_objects[digest].get("decision")
        if isinstance(decision, dict) and decision.get("action") != "approve_candidate_extraction":
            return False, "PARSE_OBJECT_DECISION_STALE"
    return True, None


def _project_row(
    project: Path,
    candidate: dict[str, Any],
    decision: dict[str, Any] | None,
) -> dict[str, Any]:
    row = copy.deepcopy(candidate)
    fresh, reason = _freshness(project, candidate)
    if not fresh:
        row.update({"status": "stale", "reason_code": reason})
        return row
    if decision is None:
        row.update({"status": "needs_review", "reason_code": "PAPER_EVIDENCE_REVIEW_REQUIRED"})
        return row
    binding_matches = (
        decision["candidate_digest"] == candidate["candidate_digest"]
        and decision["bound_parse_object_digests"]
        == candidate["bound_parse_object_digests"]
        and decision["source_pdf_sha256"] == candidate["source_pdf_sha256"]
        and decision["decision"]["bound_object_digest"] == candidate["candidate_digest"]
    )
    if not binding_matches:
        row.update({"status": "stale", "reason_code": "EVIDENCE_DECISION_STALE"})
        return row
    row["decision"] = copy.deepcopy(decision["decision"])
    action = decision["decision"]["action"]
    if action == "reject":
        row.update({"status": "rejected", "reason_code": "PAPER_EVIDENCE_REJECTED"})
    else:
        if action == "revise_and_approve":
            row["statement"] = decision["replacement_statement"]
        row.update({"status": "approved", "reason_code": "PAPER_EVIDENCE_APPROVED"})
    return row


def _paper_evidence_state(project: Path, *, persist: bool) -> dict[str, Any]:
    try:
        studies = declared_study_ids(project)
    except SourceTruthError as exc:
        raise PaperEvidenceError(exc.code) from exc
    decisions = _load_decisions(project)
    latest: dict[str, dict[str, Any]] = {}
    for decision in decisions:
        latest[decision["evidence_id"]] = decision
    rows: list[dict[str, Any]] = []
    missing_studies: list[str] = []
    for study_id in studies:
        candidates = _load_candidates(project, study_id, missing_ok=True)
        if not candidates:
            missing_studies.append(study_id)
            continue
        for row in candidates:
            decision = latest.get(row["evidence_id"])
            if decision is not None and decision.get("study_id") != row["study_id"]:
                raise PaperEvidenceError("EVIDENCE_DECISION_STUDY_MISMATCH")
            rows.append(_project_row(project, row, decision))
    if len({row["evidence_id"] for row in rows}) != len(rows):
        raise PaperEvidenceError("EVIDENCE_ID_DUPLICATE")
    known_ids = {row["evidence_id"] for row in rows}
    if any(row["evidence_id"] not in known_ids for row in decisions):
        raise PaperEvidenceError("EVIDENCE_DECISION_ORPHANED")
    rows.sort(key=lambda row: (row["study_id"], row["evidence_id"]))
    counts = {
        status: sum(row["status"] == status for row in rows)
        for status in ("approved", "rejected", "needs_review", "stale")
    }
    approved_studies = {row["study_id"] for row in rows if row["status"] == "approved"}
    settled = bool(rows) and all(row["status"] in {"approved", "rejected"} for row in rows)
    ready = settled and not missing_studies and approved_studies == set(studies)
    if missing_studies:
        reason_code = "PAPER_EVIDENCE_MISSING"
    elif counts["stale"]:
        reason_code = "PAPER_EVIDENCE_STALE"
    elif counts["needs_review"]:
        reason_code = "PAPER_EVIDENCE_REVIEW_REQUIRED"
    elif approved_studies != set(studies):
        reason_code = "PAPER_EVIDENCE_APPROVED_ROW_MISSING"
    elif ready:
        reason_code = "PAPER_EVIDENCE_READY"
    else:
        reason_code = "PAPER_EVIDENCE_NOT_READY"
    projection_digest = canonical_digest(rows)
    if persist:
        _atomic_jsonl(project, project / PROJECTION_PATH, rows)
    return {
        "status": "approved" if ready else "needs_review",
        "reason_code": reason_code,
        "workflow_can_continue": ready,
        "projection_digest": projection_digest,
        "study_count": len(studies),
        "missing_study_count": len(missing_studies),
        "total_count": len(rows),
        "approved_count": counts["approved"],
        "rejected_count": counts["rejected"],
        "needs_review_count": counts["needs_review"],
        "stale_count": counts["stale"],
        "rows": rows,
    }


def paper_evidence_state(project: Path) -> dict[str, Any]:
    """Rebuild the current fail-closed evidence projection."""

    project = _project_root(project)
    return _paper_evidence_state(project, persist=False)


def require_paper_evidence_ready(project: Path) -> str:
    """Return the current projection digest only when every study is reviewed."""

    state = paper_evidence_state(project)
    if not state["workflow_can_continue"]:
        raise PaperEvidenceError(state["reason_code"])
    return str(state["projection_digest"])
