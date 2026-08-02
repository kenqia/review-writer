"""One-purpose migration for the frozen legacy three-paper deliverable project."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from . import chemical_paper, dual_source, paper_evidence, parse_quality
from . import parse_reconciliation
from .chemical_completion import ChemicalCompletionError, project_chemical_completion_state
from .chemical_paper import ChemicalPaperError, load_chemical_paper_state
from .dual_source import DualSourceError, write_dual_source_binding
from .paper_evidence import (
    PaperEvidenceError,
    apply_paper_evidence_decision,
    paper_evidence_state,
    register_paper_evidence_candidates,
)
from .paper_evidence_store import (
    PaperEvidenceStoreError,
    project_read_lock,
    project_write_lock,
)
from .parse_quality import ParseQualityError, write_parse_quality_gate
from .parse_reconciliation import (
    ParseReconciliationError,
    write_parse_reconciliation,
)
from .source_truth import (
    SOURCE_TRUTH_ROOT,
    SourceTruthError,
    canonical_digest,
    declared_study_ids,
    load_source_truth_bundle,
    write_source_truth_bundle,
)


RECEIPT_PATH = Path("00_sources/acquisition_final_receipt.json")
DECISIONS_PATH = Path("01_evidence/paper_evidence_decisions.jsonl")
PROJECTION_PATH = Path("01_evidence/paper_evidence_projection.jsonl")
EXPECTED_STUDY_COUNT = 3
EXPECTED_EVIDENCE_COUNT = 9
LEGACY_CORPUS_MARKER = {
    "corpus_kind": "legacy_three_paper",
    "variable_n": False,
    "study_count": EXPECTED_STUDY_COUNT,
}
LEGACY_SIMULATED_RESIDUAL_ACTOR = ("human_researcher", "simulated_researcher")


class DeliverableFirstMigrationError(ValueError):
    """Stable, non-sensitive refusal code for this one migration."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _root(project: Path) -> Path:
    supplied = Path(project)
    if supplied.is_symlink() or not supplied.is_dir():
        raise DeliverableFirstMigrationError("PROJECT_INVALID")
    try:
        root = supplied.resolve(strict=True)
    except OSError as exc:
        raise DeliverableFirstMigrationError("PROJECT_INVALID") from exc
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in (*directories, *files):
            if (current_path / name).is_symlink():
                raise DeliverableFirstMigrationError("PROJECT_SYMLINK_UNSAFE")
    return root


def _read_json(path: Path, code: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise DeliverableFirstMigrationError(code)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DeliverableFirstMigrationError(code) from exc
    if not isinstance(value, dict):
        raise DeliverableFirstMigrationError(code)
    return value


def _json_bytes(value: object) -> bytes:
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


def _atomic_replace(project: Path, relative: Path, payload: bytes) -> None:
    target = project / relative
    if target.parent.is_symlink() or not target.parent.is_dir():
        raise OSError("invalid migration output parent")
    descriptor, name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _actor_pair(value: object) -> tuple[object, object]:
    if not isinstance(value, dict):
        return (None, None)
    return value.get("actor_type"), value.get("actor_label")


def _require_simulated_actor(value: object, code: str) -> None:
    actor_type, actor_label = _actor_pair(value)
    if (
        actor_type != "simulated_researcher_agent"
        or not isinstance(actor_label, str)
        or not actor_label.strip()
    ):
        raise DeliverableFirstMigrationError(code)


def _require_preservable_chemical_actor(value: object) -> None:
    pair = _actor_pair(value)
    if pair == LEGACY_SIMULATED_RESIDUAL_ACTOR:
        return
    _require_simulated_actor(value, "LEGACY_CHEMICAL_ACTOR_NOT_ELIGIBLE")


def _candidate_path(study_id: str) -> Path:
    return Path("01_evidence") / study_id / "paper_evidence_candidates.json"


def _source_bundle_path(study_id: str) -> Path:
    return SOURCE_TRUTH_ROOT / study_id / "bundle.json"


def _parse_gate_path(study_id: str) -> Path:
    return SOURCE_TRUTH_ROOT / study_id / "parse_quality.json"


def _chemical_state_path(study_id: str) -> Path:
    return Path("01_evidence/chemical_paper") / study_id / "state.json"


def _dual_binding_path(study_id: str) -> Path:
    return Path("01_evidence/dual_source") / study_id / "binding.json"


def _reconciliation_path(study_id: str) -> Path:
    return Path("01_evidence/parse_reconciliation") / study_id / "registry.json"


def _affected_paths(studies: list[str]) -> tuple[Path, ...]:
    return (
        RECEIPT_PATH,
        DECISIONS_PATH,
        PROJECTION_PATH,
        *(_source_bundle_path(study_id) for study_id in studies),
        *(_parse_gate_path(study_id) for study_id in studies),
        *(_chemical_state_path(study_id) for study_id in studies),
        *(_dual_binding_path(study_id) for study_id in studies),
        *(_reconciliation_path(study_id) for study_id in studies),
        *(_candidate_path(study_id) for study_id in studies),
    )


def _snapshot(project: Path, paths: tuple[Path, ...]) -> dict[Path, bytes | None]:
    result: dict[Path, bytes | None] = {}
    for relative in paths:
        path = project / relative
        if os.path.lexists(path) and (path.is_symlink() or not path.is_file()):
            raise DeliverableFirstMigrationError("PROJECT_SYMLINK_UNSAFE")
        result[relative] = path.read_bytes() if path.is_file() else None
    return result


def _static_candidate(candidate: object, study_id: str) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        raise DeliverableFirstMigrationError("LEGACY_EVIDENCE_INVALID")
    try:
        paper_evidence._validate_schema(
            candidate,
            paper_evidence.PAPER_EVIDENCE_SCHEMA,
            "PAPER_EVIDENCE_SCHEMA_INVALID",
        )
        paper_evidence._identifier(candidate.get("evidence_id"), "EVIDENCE_ID_INVALID")
        paper_evidence._identifier(candidate.get("source_id"), "SOURCE_ID_INVALID")
        locator = candidate.get("locator")
        if not isinstance(locator, dict):
            raise PaperEvidenceError("LOCATOR_INVALID")
        paper_evidence._normalize_locator(locator, str(locator.get("source_mode")))
    except PaperEvidenceError as exc:
        raise DeliverableFirstMigrationError("LEGACY_EVIDENCE_INVALID") from exc
    if (
        candidate.get("study_id") != study_id
        or candidate.get("decision") is not None
        or paper_evidence._candidate_digest(candidate)
        != candidate.get("candidate_digest")
    ):
        raise DeliverableFirstMigrationError("LEGACY_EVIDENCE_INVALID")
    return copy.deepcopy(candidate)


def _load_static_candidates(project: Path, study_id: str) -> list[dict[str, Any]]:
    payload = _read_json(
        project / _candidate_path(study_id), "LEGACY_EVIDENCE_INVALID"
    )
    if (
        set(payload) != {"schema_version", "study_id", "candidates"}
        or payload.get("schema_version") != "paper-evidence-candidate-set.v1"
        or payload.get("study_id") != study_id
        or not isinstance(payload.get("candidates"), list)
        or not payload["candidates"]
    ):
        raise DeliverableFirstMigrationError("LEGACY_EVIDENCE_INVALID")
    return [_static_candidate(row, study_id) for row in payload["candidates"]]


def _strict_rows(
    bundles: dict[str, dict[str, Any]],
    candidates: dict[str, list[dict[str, Any]]],
    decisions: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for study_id in sorted(candidates):
        bundle = bundles[study_id]
        sources = {
            row.get("source_id"): row
            for row in bundle.get("sources", [])
            if isinstance(row, dict) and isinstance(row.get("source_id"), str)
        }
        for candidate in candidates[study_id]:
            evidence_id = candidate["evidence_id"]
            source = sources.get(candidate["source_id"])
            decision = decisions.get(evidence_id)
            locator = candidate.get("locator")
            if (
                not isinstance(source, dict)
                or source.get("document_role") not in {"MAIN", "SI"}
                or not isinstance(source.get("pdf"), dict)
                or source["pdf"].get("sha256")
                != candidate.get("source_pdf_sha256")
                or not isinstance(locator, dict)
                or not isinstance(locator.get("page"), int)
                or isinstance(locator.get("page"), bool)
                or locator["page"] < 1
                or locator["page"] > source.get("page_count", 0)
                or not isinstance(locator.get("section_or_item"), str)
                or not locator["section_or_item"].strip()
                or (
                    locator.get("figure_or_table") is not None
                    and (
                        not isinstance(locator.get("figure_or_table"), str)
                        or not locator["figure_or_table"].strip()
                    )
                )
                or not isinstance(locator.get("exact_quote"), str)
                or not locator["exact_quote"].strip()
                or not isinstance(decision, dict)
            ):
                raise DeliverableFirstMigrationError("STRICT_EVIDENCE_TRACE_INVALID")
            bound_decision = decision.get("decision")
            _require_simulated_actor(
                bound_decision,
                "LEGACY_EVIDENCE_ACTOR_NOT_ELIGIBLE",
            )
            if (
                decision.get("candidate_digest") != candidate["candidate_digest"]
                or decision.get("bound_parse_object_digests")
                != candidate["bound_parse_object_digests"]
                or decision.get("source_pdf_sha256")
                != candidate["source_pdf_sha256"]
                or not isinstance(bound_decision, dict)
                or bound_decision.get("bound_object_digest")
                != candidate["candidate_digest"]
                or bound_decision.get("action") not in {
                    "approve",
                    "revise_and_approve",
                }
            ):
                raise DeliverableFirstMigrationError("STRICT_EVIDENCE_TRACE_INVALID")
            locator_body = {
                "source_id": candidate["source_id"],
                "document_role": source["document_role"],
                "source_pdf_sha256": candidate["source_pdf_sha256"],
                "page": locator["page"],
                "section_or_item": locator["section_or_item"],
                "figure_or_table": locator["figure_or_table"],
            }
            rows.append(
                {
                    "schema_version": "deliverable-first-strict-evidence.v1",
                    "evidence_id": evidence_id,
                    "study_id": study_id,
                    **locator_body,
                    "excerpt_hash": hashlib.sha256(
                        locator["exact_quote"].encode("utf-8")
                    ).hexdigest(),
                    "locator_hash": canonical_digest(locator_body),
                    "decision_actor_type": bound_decision["actor_type"],
                    "decision_actor_label": bound_decision["actor_label"],
                    "decision_action": bound_decision["action"],
                }
            )
    rows.sort(key=lambda row: (row["study_id"], row["evidence_id"]))
    if len(rows) != EXPECTED_EVIDENCE_COUNT:
        raise DeliverableFirstMigrationError("STRICT_EVIDENCE_COUNT_INVALID")
    return rows


def _latest_decisions(project: Path) -> dict[str, dict[str, Any]]:
    try:
        events = paper_evidence._load_decisions(project)
    except PaperEvidenceError as exc:
        raise DeliverableFirstMigrationError("LEGACY_EVIDENCE_INVALID") from exc
    latest: dict[str, dict[str, Any]] = {}
    for event in events:
        evidence_id = event.get("evidence_id")
        if not isinstance(evidence_id, str) or evidence_id in latest:
            raise DeliverableFirstMigrationError("LEGACY_EVIDENCE_HISTORY_NOT_ELIGIBLE")
        latest[evidence_id] = copy.deepcopy(event)
    return latest


def _static_chain(project: Path, *, expected_source_project_id: str) -> dict[str, Any]:
    if (
        not isinstance(expected_source_project_id, str)
        or not expected_source_project_id.strip()
        or expected_source_project_id != expected_source_project_id.strip()
        or project.name == expected_source_project_id
    ):
        raise DeliverableFirstMigrationError("PROJECT_ID_MIGRATION_INVALID")
    receipt = _read_json(project / RECEIPT_PATH, "ACQUISITION_FINAL_RECEIPT_INVALID")
    marker_keys = set(LEGACY_CORPUS_MARKER)
    present_marker_keys = marker_keys.intersection(receipt)
    if present_marker_keys and (
        present_marker_keys != marker_keys
        or any(receipt.get(key) != value for key, value in LEGACY_CORPUS_MARKER.items())
    ):
        raise DeliverableFirstMigrationError("LEGACY_THREE_PAPER_MARKER_NOT_ELIGIBLE")
    studies_value = receipt.get("studies")
    if not isinstance(studies_value, list):
        raise DeliverableFirstMigrationError("LEGACY_THREE_PAPER_NOT_ELIGIBLE")
    studies = [
        row.get("study_id") for row in studies_value if isinstance(row, dict)
    ]
    if (
        len(studies) != EXPECTED_STUDY_COUNT
        or len(set(studies)) != EXPECTED_STUDY_COUNT
        or any(not isinstance(study_id, str) or not study_id for study_id in studies)
    ):
        raise DeliverableFirstMigrationError("LEGACY_THREE_PAPER_NOT_ELIGIBLE")
    studies = sorted(studies)
    try:
        if sorted(declared_study_ids(project)) != studies:
            raise DeliverableFirstMigrationError("LEGACY_THREE_PAPER_NOT_ELIGIBLE")
    except SourceTruthError as exc:
        raise DeliverableFirstMigrationError("LEGACY_THREE_PAPER_NOT_ELIGIBLE") from exc

    bundles: dict[str, dict[str, Any]] = {}
    candidates: dict[str, list[dict[str, Any]]] = {}
    chemical_states: dict[str, dict[str, Any]] = {}
    for study_id in studies:
        try:
            bundle = load_source_truth_bundle(project, study_id)
        except SourceTruthError as exc:
            raise DeliverableFirstMigrationError("LEGACY_SOURCE_TRUTH_INVALID") from exc
        if (
            bundle.get("project_id") != expected_source_project_id
            or bundle.get("study_id") != study_id
        ):
            raise DeliverableFirstMigrationError("LEGACY_SOURCE_TRUTH_NOT_ELIGIBLE")
        bundles[study_id] = copy.deepcopy(bundle)

        gate = _read_json(
            project / _parse_gate_path(study_id), "LEGACY_PARSE_QUALITY_INVALID"
        )
        try:
            parse_quality._validate_gate(gate)
        except ParseQualityError as exc:
            raise DeliverableFirstMigrationError("LEGACY_PARSE_QUALITY_INVALID") from exc
        if gate.get("bundle_digest") != bundle.get("bundle_digest"):
            raise DeliverableFirstMigrationError("LEGACY_PARSE_QUALITY_INVALID")
        for row in gate.get("objects", []):
            if isinstance(row, dict) and row.get("decision") is not None:
                _require_simulated_actor(
                    row["decision"], "LEGACY_PARSE_ACTOR_NOT_ELIGIBLE"
                )

        raw_state = _read_json(
            project / _chemical_state_path(study_id),
            "LEGACY_CHEMICAL_STATE_INVALID",
        )
        try:
            state = chemical_paper._validate_state(raw_state)
        except ChemicalPaperError as exc:
            raise DeliverableFirstMigrationError("LEGACY_CHEMICAL_STATE_INVALID") from exc
        if (
            state.get("project_id") != expected_source_project_id
            or state.get("study_id") != study_id
            or state.get("source_truth_bundle_digest") != bundle.get("bundle_digest")
            or len(state.get("imports", {})) != 1
        ):
            raise DeliverableFirstMigrationError("LEGACY_CHEMICAL_STATE_NOT_ELIGIBLE")
        for event in state["imports"].values():
            _require_simulated_actor(
                event.get("actor"), "LEGACY_CHEMICAL_ACTOR_NOT_ELIGIBLE"
            )
        for event in [*state["field_corrections"], *state["element_reviews"]]:
            _require_preservable_chemical_actor(event.get("actor"))
        chemical_states[study_id] = state

        binding = _read_json(
            project / _dual_binding_path(study_id), "LEGACY_DUAL_BINDING_INVALID"
        )
        registry = _read_json(
            project / _reconciliation_path(study_id),
            "LEGACY_RECONCILIATION_INVALID",
        )
        try:
            dual_source._validate(binding)
            parse_reconciliation._validate(registry)
        except (DualSourceError, ParseReconciliationError) as exc:
            raise DeliverableFirstMigrationError("LEGACY_DUAL_CHAIN_INVALID") from exc
        if (
            binding.get("project_id") != expected_source_project_id
            or registry.get("project_id") != expected_source_project_id
        ):
            raise DeliverableFirstMigrationError("LEGACY_DUAL_CHAIN_NOT_ELIGIBLE")
        for row in registry.get("objects", []):
            if isinstance(row, dict) and row.get("decision") is not None:
                _require_simulated_actor(
                    row["decision"], "LEGACY_RECONCILIATION_ACTOR_NOT_ELIGIBLE"
                )
        candidates[study_id] = _load_static_candidates(project, study_id)

    if sum(len(rows) for rows in candidates.values()) != EXPECTED_EVIDENCE_COUNT:
        raise DeliverableFirstMigrationError("STRICT_EVIDENCE_COUNT_INVALID")
    decisions = _latest_decisions(project)
    candidate_ids = {
        row["evidence_id"] for rows in candidates.values() for row in rows
    }
    if set(decisions) != candidate_ids:
        raise DeliverableFirstMigrationError("LEGACY_EVIDENCE_HISTORY_NOT_ELIGIBLE")
    strict_rows = _strict_rows(bundles, candidates, decisions)
    return {
        "receipt": receipt,
        "studies": studies,
        "bundles": bundles,
        "chemical_states": chemical_states,
        "candidates": candidates,
        "decisions": decisions,
        "strict_rows": strict_rows,
    }


def _rebind_chemical_state(
    state: dict[str, Any],
    *,
    project_id: str,
    source_truth_bundle_digest: str,
) -> dict[str, Any]:
    current = chemical_paper._validate_state(copy.deepcopy(state))
    if len(current["imports"]) != 1:
        raise DeliverableFirstMigrationError("LEGACY_CHEMICAL_STATE_NOT_ELIGIBLE")
    old_import_digest = current["current_import_digest"]
    old_import = current["imports"][old_import_digest]
    import_body = {
        key: copy.deepcopy(value)
        for key, value in old_import.items()
        if key
        not in {
            "import_digest",
            "imported_at",
            "actor",
            "prior_import_event_digest",
            "import_event_digest",
        }
    }
    import_body["source_truth_bundle_digest"] = source_truth_bundle_digest
    new_import_digest = canonical_digest(import_body)
    new_import = {
        **import_body,
        "import_digest": new_import_digest,
        "imported_at": old_import["imported_at"],
        "actor": copy.deepcopy(old_import["actor"]),
        "prior_import_event_digest": None,
    }
    new_import["import_event_digest"] = canonical_digest(new_import)

    correction_digest_map: dict[str, str] = {}
    corrections: list[dict[str, Any]] = []
    correction_head: str | None = None
    for old_event in current["field_corrections"]:
        if old_event["bound_import_digest"] != old_import_digest:
            raise DeliverableFirstMigrationError("LEGACY_CHEMICAL_STATE_NOT_ELIGIBLE")
        event = copy.deepcopy(old_event)
        event["bound_import_digest"] = new_import_digest
        event["prior_event_digest"] = correction_head
        old_event_digest = event.pop("event_digest")
        event["event_digest"] = canonical_digest(event)
        correction_digest_map[old_event_digest] = event["event_digest"]
        correction_head = event["event_digest"]
        corrections.append(event)

    reviews: list[dict[str, Any]] = []
    review_head: str | None = None
    for old_event in current["element_reviews"]:
        if old_event["bound_import_digest"] != old_import_digest:
            raise DeliverableFirstMigrationError("LEGACY_CHEMICAL_STATE_NOT_ELIGIBLE")
        event = copy.deepcopy(old_event)
        event["bound_import_digest"] = new_import_digest
        event["prior_event_digest"] = review_head
        resolution_digest = event.get("bound_resolution_event_digest")
        if resolution_digest is not None:
            replacement = correction_digest_map.get(resolution_digest)
            if replacement is None:
                raise DeliverableFirstMigrationError(
                    "LEGACY_CHEMICAL_STATE_NOT_ELIGIBLE"
                )
            event["bound_resolution_event_digest"] = replacement
        event.pop("event_digest")
        event["event_digest"] = canonical_digest(event)
        review_head = event["event_digest"]
        reviews.append(event)

    rebound = copy.deepcopy(current)
    rebound.update(
        {
            "project_id": project_id,
            "source_truth_bundle_digest": source_truth_bundle_digest,
            "current_import_digest": new_import_digest,
            "imports": {new_import_digest: new_import},
            "field_corrections": corrections,
            "field_correction_head_digest": correction_head,
            "element_reviews": reviews,
            "element_review_head_digest": review_head,
        }
    )
    rebound["state_digest"] = chemical_paper._canonical_state_digest(rebound)
    try:
        return chemical_paper._validate_state(rebound)
    except ChemicalPaperError as exc:
        raise DeliverableFirstMigrationError("CHEMICAL_REBIND_INVALID") from exc


def _candidate_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    excluded = {"candidate_digest", "decision", "dual_parse_bindings"}
    return {
        key: copy.deepcopy(value)
        for key, value in candidate.items()
        if key not in excluded
    }


def _rebuild_staging(staging: Path, chain: dict[str, Any]) -> dict[str, Any]:
    receipt = copy.deepcopy(chain["receipt"])
    receipt.update(LEGACY_CORPUS_MARKER)
    _atomic_replace(staging, RECEIPT_PATH, _json_bytes(receipt))

    rebuilt_bundles: dict[str, dict[str, Any]] = {}
    for study_id in chain["studies"]:
        previous_bundle = chain["bundles"][study_id]
        try:
            bundle = write_source_truth_bundle(staging, study_id)
        except SourceTruthError as exc:
            raise DeliverableFirstMigrationError("SOURCE_TRUTH_REBUILD_FAILED") from exc
        previous_semantics = {
            key: value
            for key, value in previous_bundle.items()
            if key not in {"project_id", "bundle_digest"}
        }
        current_semantics = {
            key: value
            for key, value in bundle.items()
            if key not in {"project_id", "bundle_digest"}
        }
        if previous_semantics != current_semantics:
            raise DeliverableFirstMigrationError("SOURCE_TRUTH_SEMANTICS_CHANGED")
        rebuilt_bundles[study_id] = bundle
        try:
            gate = write_parse_quality_gate(staging, study_id)
        except ParseQualityError as exc:
            raise DeliverableFirstMigrationError("PARSE_QUALITY_REBUILD_FAILED") from exc
        if not gate.get("workflow_can_continue"):
            raise DeliverableFirstMigrationError("PARSE_QUALITY_REBUILD_INVALID")
        for row in gate.get("objects", []):
            if isinstance(row, dict) and row.get("decision") is not None:
                _require_simulated_actor(
                    row["decision"], "LEGACY_PARSE_ACTOR_NOT_ELIGIBLE"
                )

    # Source lookup is project-wide: every bundle must carry the target project
    # identity before any one Chemical state can be validated against the index.
    for study_id in chain["studies"]:
        rebound = _rebind_chemical_state(
            chain["chemical_states"][study_id],
            project_id=staging.name,
            source_truth_bundle_digest=str(
                rebuilt_bundles[study_id]["bundle_digest"]
            ),
        )
        chemical_paper._atomic_json(
            staging / _chemical_state_path(study_id), rebound
        )

    try:
        for study_id in chain["studies"]:
            load_chemical_paper_state(staging, study_id)
        # The fixed-309 completion digest is project-wide, so all three states
        # must be current before any downstream binding is derived.
        for study_id in chain["studies"]:
            write_dual_source_binding(staging, study_id)
        for study_id in chain["studies"]:
            write_parse_reconciliation(staging, study_id)
    except (
        ChemicalPaperError,
        DualSourceError,
        ParseReconciliationError,
    ) as exc:
        raise DeliverableFirstMigrationError("DUAL_CHAIN_REBUILD_FAILED") from exc

    for study_id in chain["studies"]:
        (staging / _candidate_path(study_id)).unlink()
    (staging / DECISIONS_PATH).unlink()
    (staging / PROJECTION_PATH).unlink(missing_ok=True)

    rebound_candidates: dict[str, dict[str, Any]] = {}
    try:
        for study_id in chain["studies"]:
            result = register_paper_evidence_candidates(
                staging,
                study_id,
                {
                    "candidates": [
                        _candidate_payload(row)
                        for row in chain["candidates"][study_id]
                    ]
                },
            )
            rebound_candidates.update(
                {row["evidence_id"]: row for row in result["candidates"]}
            )
        for evidence_id in sorted(rebound_candidates):
            candidate = rebound_candidates[evidence_id]
            old_event = chain["decisions"][evidence_id]
            old_decision = old_event["decision"]
            payload = {
                "evidence_id": evidence_id,
                "candidate_digest": candidate["candidate_digest"],
                "bound_parse_object_digests": candidate[
                    "bound_parse_object_digests"
                ],
                "source_pdf_sha256": candidate["source_pdf_sha256"],
                "action": old_decision["action"],
                "reason": old_decision["reason"],
                "actor_type": old_decision["actor_type"],
                "actor_label": old_decision["actor_label"],
            }
            if old_event.get("replacement_statement") is not None:
                payload["replacement_statement"] = old_event["replacement_statement"]
            apply_paper_evidence_decision(staging, payload)
    except PaperEvidenceError as exc:
        raise DeliverableFirstMigrationError("EVIDENCE_REBUILD_FAILED") from exc

    report = strict_evidence_trace(staging)
    if report["rows"] != chain["strict_rows"]:
        raise DeliverableFirstMigrationError("STRICT_EVIDENCE_TRACE_CHANGED")
    try:
        chemical = project_chemical_completion_state(staging)
    except ChemicalCompletionError as exc:
        raise DeliverableFirstMigrationError("CHEMICAL_COMPLETION_REBUILD_FAILED") from exc
    if chemical.get("confirmed_count"):
        raise DeliverableFirstMigrationError("CONFIRMED_STATE_CREATED")
    return report


def _link_or_copy(source: str, destination: str) -> None:
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def _restore(project: Path, snapshot: dict[Path, bytes | None]) -> None:
    for relative, payload in snapshot.items():
        path = project / relative
        if payload is None:
            path.unlink(missing_ok=True)
        else:
            _atomic_replace(project, relative, payload)


def _commit(
    project: Path,
    before: dict[Path, bytes | None],
    after: dict[Path, bytes | None],
) -> None:
    try:
        with project_write_lock(project):
            if _snapshot(project, tuple(before)) != before:
                raise DeliverableFirstMigrationError("MIGRATION_VERSION_CHANGED")
            try:
                for relative, payload in after.items():
                    if payload is None:
                        (project / relative).unlink(missing_ok=True)
                    else:
                        _atomic_replace(project, relative, payload)
            except Exception as exc:
                try:
                    _restore(project, before)
                except Exception as rollback_exc:
                    raise DeliverableFirstMigrationError(
                        "MIGRATION_ROLLBACK_FAILED"
                    ) from rollback_exc
                raise DeliverableFirstMigrationError("MIGRATION_WRITE_FAILED") from exc
    except PaperEvidenceStoreError as exc:
        raise DeliverableFirstMigrationError(exc.code) from exc


def strict_evidence_trace(project: Path) -> dict[str, Any]:
    """Validate current Evidence and return hashes without exposing source excerpts."""

    root = _root(project)
    try:
        state = paper_evidence_state(root)
    except PaperEvidenceError as exc:
        raise DeliverableFirstMigrationError("STRICT_EVIDENCE_NOT_CURRENT") from exc
    if (
        not state.get("workflow_can_continue")
        or len(state.get("rows", [])) != EXPECTED_EVIDENCE_COUNT
        or any(row.get("status") != "approved" for row in state.get("rows", []))
    ):
        raise DeliverableFirstMigrationError("STRICT_EVIDENCE_NOT_CURRENT")
    try:
        studies = sorted(declared_study_ids(root))
        bundles = {
            study_id: load_source_truth_bundle(root, study_id)
            for study_id in studies
        }
    except SourceTruthError as exc:
        raise DeliverableFirstMigrationError("STRICT_EVIDENCE_TRACE_INVALID") from exc
    candidates = {
        study_id: _load_static_candidates(root, study_id) for study_id in studies
    }
    decisions = _latest_decisions(root)
    rows = _strict_rows(bundles, candidates, decisions)
    return {
        "schema_version": "deliverable-first-strict-evidence-trace.v1",
        "evidence_count": len(rows),
        "rows": rows,
        "trace_digest": canonical_digest(rows),
    }


def migrate_legacy_three_paper_project(
    project: Path,
    *,
    expected_source_project_id: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Atomically rebind one renamed, frozen legacy three-paper project."""

    root = _root(project)
    guard_lock = project_read_lock if dry_run else project_write_lock
    try:
        with guard_lock(root):
            chain = _static_chain(
                root, expected_source_project_id=expected_source_project_id
            )
            affected_paths = _affected_paths(chain["studies"])
            before = _snapshot(root, affected_paths)
    except PaperEvidenceStoreError as exc:
        raise DeliverableFirstMigrationError(exc.code) from exc

    try:
        with tempfile.TemporaryDirectory(
            prefix=".deliverable-first-migration-", dir=root.parent
        ) as temporary:
            staging = Path(temporary) / root.name
            shutil.copytree(root, staging, copy_function=_link_or_copy)
            trace = _rebuild_staging(staging, chain)
            after = _snapshot(staging, affected_paths)
    except DeliverableFirstMigrationError:
        raise
    except (OSError, ValueError) as exc:
        raise DeliverableFirstMigrationError("MIGRATION_REBUILD_FAILED") from exc

    changed_paths = sorted(
        relative.as_posix()
        for relative in affected_paths
        if before[relative] != after[relative]
    )
    report = {
        "status": "DRY_RUN_READY" if dry_run else "MIGRATED",
        "reason_code": (
            "DELIVERABLE_FIRST_LEGACY_MIGRATION_READY"
            if dry_run
            else "DELIVERABLE_FIRST_LEGACY_MIGRATED"
        ),
        "source_project_id": expected_source_project_id,
        "project_id": root.name,
        "study_count": len(chain["studies"]),
        "evidence_count": len(chain["strict_rows"]),
        "strict_evidence_count": trace["evidence_count"],
        "strict_trace_digest": trace["trace_digest"],
        "changed_paths": changed_paths,
    }
    if dry_run:
        return report
    _commit(root, before, after)
    current = strict_evidence_trace(root)
    if current["trace_digest"] != trace["trace_digest"]:
        raise DeliverableFirstMigrationError("MIGRATION_COMMIT_INVALID")
    return report
