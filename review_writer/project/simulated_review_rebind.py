"""Narrow repair for a current simulated Dashboard review chain misattributed as human."""

from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from . import manuscript_v2
from .manuscript_v2 import ManuscriptV2Error, manuscript_state
from .paper_evidence import (
    PaperEvidenceError,
    apply_paper_evidence_decision,
    paper_evidence_state,
)
from .paper_evidence_store import PaperEvidenceStoreError, project_write_lock
from .section_contract import (
    PATH as CONTRACT_PATH,
    SectionContractError,
    apply_section_contract_decision,
    register_section_contracts,
    section_contract_state,
)
from .synthesis import (
    CLAIM_PATH,
    COVERAGE_PATH,
    PROTOCOL_PATH,
    SynthesisError,
    apply_comparison_protocol_decision,
    apply_synthesis_decision,
    comparison_protocol_state,
    coverage_map_state,
    register_comparison_protocol,
    register_coverage_map,
    register_synthesis_candidates,
    synthesis_state,
)
from .workflow_projection import workflow_state


DECISIONS_PATH = Path("01_evidence/paper_evidence_decisions.jsonl")
PROJECTION_PATH = Path("01_evidence/paper_evidence_projection.jsonl")
ALLOWED_ACTOR_LABEL = "dashboard-playwright-reviewer"
OLD_ACTOR = ("human_researcher", "local-researcher")
NEW_ACTOR_TYPE = "simulated_researcher_agent"
AFFECTED_PATHS = (
    DECISIONS_PATH,
    PROJECTION_PATH,
    PROTOCOL_PATH,
    COVERAGE_PATH,
    CLAIM_PATH,
    CONTRACT_PATH,
    manuscript_v2.DRAFTS_PATH,
)


class SimulatedReviewRebindError(ValueError):
    """Stable, non-sensitive refusal code for the one-purpose repair."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _root(project: Path) -> Path:
    supplied = Path(project)
    if supplied.is_symlink() or not supplied.is_dir():
        raise SimulatedReviewRebindError("PROJECT_INVALID")
    try:
        root = supplied.resolve(strict=True)
    except OSError as exc:
        raise SimulatedReviewRebindError("PROJECT_INVALID") from exc
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        try:
            relative = current_path.relative_to(root)
        except ValueError:
            continue
        if relative.parts[:1] == ("04_first_draft",):
            directories[:] = []
            continue
        for name in (*directories, *files):
            if (current_path / name).is_symlink():
                raise SimulatedReviewRebindError("PROJECT_SYMLINK_UNSAFE")
    return root


def _read_json(path: Path, code: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise SimulatedReviewRebindError(code)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SimulatedReviewRebindError(code) from exc
    if not isinstance(value, dict):
        raise SimulatedReviewRebindError(code)
    return value


def _read_jsonl(path: Path, code: str) -> list[dict[str, Any]]:
    if not path.is_file() or path.is_symlink():
        raise SimulatedReviewRebindError(code)
    try:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SimulatedReviewRebindError(code) from exc
    if not rows or not all(isinstance(row, dict) for row in rows):
        raise SimulatedReviewRebindError(code)
    return rows


def _old_actor(decision: object) -> bool:
    return (
        isinstance(decision, dict)
        and (decision.get("actor_type"), decision.get("actor_label")) == OLD_ACTOR
    )


def _new_actor(decision: object, actor_label: str) -> bool:
    return (
        isinstance(decision, dict)
        and decision.get("actor_type") == NEW_ACTOR_TYPE
        and decision.get("actor_label") == actor_label
    )


def _current_chain(project: Path) -> dict[str, Any]:
    try:
        evidence = paper_evidence_state(project)
        protocol = comparison_protocol_state(project)
        coverage = coverage_map_state(project)
        synthesis = synthesis_state(project)
        contracts = section_contract_state(project)
    except (PaperEvidenceError, SynthesisError, SectionContractError, OSError, ValueError) as exc:
        raise SimulatedReviewRebindError("CHAIN_INVALID") from exc
    # Attribute failures first so an already-rebound/unknown actor cannot be
    # mistaken for an ordinary stale chain.
    actor_rows: list[object] = []
    for state, key in ((evidence, "rows"), (synthesis, "rows"), (contracts, "rows")):
        rows = state.get(key)
        if isinstance(rows, list):
            actor_rows.extend(row.get("decision") for row in rows if isinstance(row, dict))
    protocol_value = protocol.get("value")
    if isinstance(protocol_value, dict):
        actor_rows.append(protocol_value.get("decision"))
    if actor_rows and any(not _old_actor(decision) for decision in actor_rows):
        raise SimulatedReviewRebindError("CHAIN_ACTOR_NOT_ELIGIBLE")
    states = (evidence, protocol, coverage, synthesis, contracts)
    if any(not state.get("workflow_can_continue") for state in states):
        raise SimulatedReviewRebindError("CHAIN_STALE_OR_INCOMPLETE")
    evidence_rows = evidence.get("rows")
    synthesis_rows = synthesis.get("rows")
    contract_rows = contracts.get("rows")
    protocol_value = protocol.get("value")
    coverage_value = coverage.get("value")
    if (
        not isinstance(evidence_rows, list)
        or not evidence_rows
        or not isinstance(synthesis_rows, list)
        or not synthesis_rows
        or not isinstance(contract_rows, list)
        or not contract_rows
        or not isinstance(protocol_value, dict)
        or not isinstance(coverage_value, dict)
    ):
        raise SimulatedReviewRebindError("CHAIN_STALE_OR_INCOMPLETE")
    approved_rows = [*evidence_rows, *synthesis_rows, *contract_rows]
    if any(not isinstance(row, dict) or row.get("status") != "approved" for row in approved_rows):
        raise SimulatedReviewRebindError("CHAIN_NOT_ALL_APPROVED")
    return {
        "evidence": evidence,
        "protocol": protocol_value,
        "coverage": coverage_value,
        "synthesis": synthesis_rows,
        "contracts": contract_rows,
    }


_DRAFT_KEYS = {
    "schema_version",
    "section_id",
    "heading",
    "body",
    "contract_digest",
    "paper_evidence_projection_digest",
    "synthesis_projection_digest",
    "section_contract_projection_digest",
    "generation_content_agent_result_digest",
    "claim_bindings",
    "high_risk_reasons",
    "decision",
    "draft_digest",
    "status",
}


def _prepare_draft_rebind(project: Path, *, require_current: bool) -> list[dict[str, Any]]:
    try:
        rows = manuscript_v2._read_jsonl(project)
    except ManuscriptV2Error as exc:
        raise SimulatedReviewRebindError(exc.code) from exc
    if not rows:
        return []
    try:
        evidence, synthesis, contracts = manuscript_v2._states(project)
    except ManuscriptV2Error as exc:
        raise SimulatedReviewRebindError(exc.code) from exc
    updated: list[dict[str, Any]] = []
    for raw in rows:
        if raw.get("decision") is not None or raw.get("status") == "approved":
            raise SimulatedReviewRebindError("APPROVED_DRAFT_REBIND_FORBIDDEN")
        if set(raw) != _DRAFT_KEYS or raw.get("status") not in {"needs_review", "needs_human_edit"}:
            raise SimulatedReviewRebindError("SECTION_DRAFT_REBIND_INVALID")
        try:
            manuscript_v2._identifier(raw.get("section_id"), "SECTION_DRAFT_REBIND_INVALID")
            manuscript_v2._digest(
                raw.get("generation_content_agent_result_digest"),
                "SECTION_DRAFT_REBIND_INVALID",
            )
            if require_current and not manuscript_v2._draft_is_current(
                raw, evidence, synthesis, contracts
            ):
                raise SimulatedReviewRebindError("SECTION_DRAFT_STALE")
            contract = manuscript_v2._approved_contract(contracts, str(raw["section_id"]))
            bindings, high_risk = manuscript_v2._claim_bindings(
                raw.get("body"), evidence, synthesis
            )
        except ManuscriptV2Error as exc:
            raise SimulatedReviewRebindError(exc.code) from exc
        if require_current and (
            raw.get("claim_bindings") != bindings
            or raw.get("high_risk_reasons") != high_risk
        ):
            raise SimulatedReviewRebindError("SECTION_DRAFT_REBIND_INVALID")
        row = copy.deepcopy(raw)
        row.update(
            {
                "contract_digest": contract["contract_digest"],
                "paper_evidence_projection_digest": evidence["projection_digest"],
                "synthesis_projection_digest": synthesis["projection_digest"],
                "section_contract_projection_digest": contracts["projection_digest"],
                "claim_bindings": bindings,
                "high_risk_reasons": high_risk,
                "decision": None,
                "status": "needs_human_edit" if high_risk else "needs_review",
            }
        )
        row["draft_digest"] = manuscript_v2._draft_digest(row)
        if not manuscript_v2._draft_is_current(row, evidence, synthesis, contracts):
            raise SimulatedReviewRebindError("SECTION_DRAFT_REBIND_INVALID")
        updated.append(row)
    return updated


def _write_rebound_drafts(project: Path) -> int:
    rows = _prepare_draft_rebind(project, require_current=False)
    if rows:
        manuscript_v2._atomic_bytes(
            project,
            manuscript_v2.DRAFTS_PATH,
            manuscript_v2._jsonl_bytes(rows),
        )
    return len(rows)


def _latest_evidence_events(project: Path) -> dict[str, dict[str, Any]]:
    events = _read_jsonl(project / DECISIONS_PATH, "CHAIN_STALE_OR_INCOMPLETE")
    latest: dict[str, dict[str, Any]] = {}
    for event in events:
        evidence_id = event.get("evidence_id")
        if isinstance(evidence_id, str):
            latest[evidence_id] = event
    return latest


def _scientific(value: dict[str, Any], excluded: set[str]) -> dict[str, Any]:
    return {key: copy.deepcopy(item) for key, item in value.items() if key not in excluded}


def _rebuild_staging(
    project: Path, chain: dict[str, Any], actor_label: str
) -> dict[str, int]:
    actor = {"actor_type": NEW_ACTOR_TYPE, "actor_label": actor_label}
    events = _latest_evidence_events(project)
    for row in chain["evidence"]["rows"]:
        event = events.get(row["evidence_id"])
        if not isinstance(event, dict) or not _old_actor(event.get("decision")):
            raise SimulatedReviewRebindError("CHAIN_ACTOR_NOT_ELIGIBLE")
        decision = event["decision"]
        payload = {
            "evidence_id": row["evidence_id"],
            "candidate_digest": row["candidate_digest"],
            "bound_parse_object_digests": row["bound_parse_object_digests"],
            "source_pdf_sha256": row["source_pdf_sha256"],
            "action": decision["action"],
            "reason": decision["reason"],
            **actor,
        }
        if "replacement_statement" in event:
            payload["replacement_statement"] = event["replacement_statement"]
        apply_paper_evidence_decision(project, payload)

    protocol = chain["protocol"]
    protocol_decision = protocol["decision"]
    register_comparison_protocol(
        project,
        _scientific(
            protocol,
            {"paper_evidence_projection_digest", "protocol_digest", "decision", "status", "reason_code"},
        ),
    )
    apply_comparison_protocol_decision(
        project,
        {
            "action": protocol_decision["action"],
            "reason": protocol_decision["reason"],
            **actor,
        },
    )
    register_coverage_map(
        project,
        _scientific(
            chain["coverage"],
            {"comparison_protocol_digest", "status", "reason_code"},
        ),
    )

    (project / CLAIM_PATH).unlink()
    synthesis_candidates = [
        _scientific(
            row,
            {
                "paper_evidence_projection_digest",
                "comparison_protocol_digest",
                "synthesis_digest",
                "decision",
                "status",
                "reason_code",
            },
        )
        for row in chain["synthesis"]
    ]
    register_synthesis_candidates(project, {"claims": synthesis_candidates})
    for old in chain["synthesis"]:
        decision = old["decision"]
        apply_synthesis_decision(
            project,
            {
                "synthesis_id": old["synthesis_id"],
                "action": decision["action"],
                "reason": decision["reason"],
                **actor,
            },
        )

    (project / CONTRACT_PATH).unlink()
    contract_candidates = [
        _scientific(
            row,
            {
                "synthesis_projection_digest",
                "contract_digest",
                "decision",
                "status",
                "reason_code",
            },
        )
        for row in chain["contracts"]
    ]
    register_section_contracts(project, {"contracts": contract_candidates})
    for old in chain["contracts"]:
        decision = old["decision"]
        apply_section_contract_decision(
            project,
            {
                "section_id": old["section_id"],
                "action": decision["action"],
                "reason": decision["reason"],
                **actor,
            },
        )
    draft_count = _write_rebound_drafts(project)
    return {
        "evidence": len(chain["evidence"]["rows"]),
        "protocol": 1,
        "coverage": 1,
        "synthesis": len(chain["synthesis"]),
        "contracts": len(chain["contracts"]),
        "drafts": draft_count,
    }


def _validate_rebuilt(project: Path, counts: dict[str, int], actor_label: str) -> None:
    try:
        evidence = paper_evidence_state(project)
        protocol = comparison_protocol_state(project)
        coverage = coverage_map_state(project)
        synthesis = synthesis_state(project)
        contracts = section_contract_state(project)
        workflow = workflow_state(project)
        manuscript = manuscript_state(project)
    except (PaperEvidenceError, SynthesisError, SectionContractError, ManuscriptV2Error) as exc:
        raise SimulatedReviewRebindError("CHAIN_REBUILD_INVALID") from exc
    if (
        not evidence.get("workflow_can_continue")
        or not protocol.get("workflow_can_continue")
        or not coverage.get("workflow_can_continue")
        or not synthesis.get("workflow_can_continue")
        or not contracts.get("workflow_can_continue")
        or workflow.get("active_stage") != "drafting"
        or workflow.get("manuscript_ready") is not False
        or workflow.get("verified_release_ready") is not False
        or manuscript.get("workflow_can_continue") is not False
    ):
        raise SimulatedReviewRebindError("CHAIN_REBUILD_INVALID")
    decisions = [row.get("decision") for row in evidence.get("rows", [])]
    decisions.extend(row.get("decision") for row in synthesis.get("rows", []))
    decisions.extend(row.get("decision") for row in contracts.get("rows", []))
    decisions.append((protocol.get("value") or {}).get("decision"))
    if any(not _new_actor(decision, actor_label) for decision in decisions):
        raise SimulatedReviewRebindError("CHAIN_REBUILD_INVALID")
    drafts = manuscript_v2._read_jsonl(project)
    if len(drafts) != counts["drafts"] or any(
        row.get("decision") is not None
        or row.get("status") not in {"needs_review", "needs_human_edit"}
        for row in drafts
    ):
        raise SimulatedReviewRebindError("CHAIN_REBUILD_INVALID")


def _link_or_copy(source: str, destination: str) -> None:
    """Keep staging cheap while ensuring later os.replace calls isolate outputs."""
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def _ignore_legacy_draft(root: Path):
    def ignore(directory: str, names: list[str]) -> set[str]:
        if Path(directory) == root and "04_first_draft" in names:
            return {"04_first_draft"}
        return set()

    return ignore


def _snapshot(project: Path) -> dict[Path, bytes | None]:
    snapshots: dict[Path, bytes | None] = {}
    for relative in AFFECTED_PATHS:
        path = project / relative
        if os.path.lexists(path) and (path.is_symlink() or not path.is_file()):
            raise SimulatedReviewRebindError("PROJECT_SYMLINK_UNSAFE")
        snapshots[relative] = path.read_bytes() if path.is_file() else None
    return snapshots


def _atomic_replace(project: Path, relative: Path, payload: bytes) -> None:
    target = project / relative
    if target.parent.is_symlink() or not target.parent.is_dir():
        raise OSError("invalid output parent")
    fd, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _restore(project: Path, snapshots: dict[Path, bytes | None]) -> None:
    for relative, payload in snapshots.items():
        path = project / relative
        if payload is None:
            path.unlink(missing_ok=True)
        else:
            _atomic_replace(project, relative, payload)


def _commit_transaction(
    project: Path,
    before: dict[Path, bytes | None],
    after: dict[Path, bytes | None],
) -> None:
    try:
        with project_write_lock(project):
            if _snapshot(project) != before:
                raise SimulatedReviewRebindError("CHAIN_VERSION_CHANGED")
            try:
                for relative in AFFECTED_PATHS:
                    payload = after[relative]
                    if payload is None:
                        (project / relative).unlink(missing_ok=True)
                    else:
                        _atomic_replace(project, relative, payload)
            except Exception as exc:
                try:
                    _restore(project, before)
                except Exception as rollback_exc:
                    raise SimulatedReviewRebindError("REBIND_ROLLBACK_FAILED") from rollback_exc
                raise SimulatedReviewRebindError("REBIND_WRITE_FAILED") from exc
    except PaperEvidenceStoreError as exc:
        raise SimulatedReviewRebindError(exc.code) from exc


def rebind_simulated_review_chain(
    project: Path,
    *,
    actor_label: str,
    dry_run: bool = False,
) -> dict[str, object]:
    """Repair one current all-approved human/local chain as a simulated review chain."""
    if actor_label != ALLOWED_ACTOR_LABEL:
        raise SimulatedReviewRebindError("ACTOR_LABEL_NOT_ALLOWED")
    root = _root(project)
    chain = _current_chain(root)
    _prepare_draft_rebind(root, require_current=True)
    before = _snapshot(root)
    try:
        with tempfile.TemporaryDirectory(
            prefix=".review-writer-rebind-", dir=root.parent
        ) as temporary:
            staging = Path(temporary) / "project"
            shutil.copytree(
                root,
                staging,
                copy_function=_link_or_copy,
                ignore=_ignore_legacy_draft(root),
            )
            counts = _rebuild_staging(staging, chain, actor_label)
            _validate_rebuilt(staging, counts, actor_label)
            after = _snapshot(staging)
    except SimulatedReviewRebindError:
        raise
    except (
        OSError,
        PaperEvidenceError,
        SynthesisError,
        SectionContractError,
        ManuscriptV2Error,
        PaperEvidenceStoreError,
    ) as exc:
        raise SimulatedReviewRebindError("CHAIN_REBUILD_FAILED") from exc
    if dry_run:
        return {
            "status": "DRY_RUN_READY",
            "reason_code": "SIMULATED_REVIEW_CHAIN_REBIND_READY",
            "counts": counts,
        }
    _commit_transaction(root, before, after)
    return {
        "status": "REBOUND",
        "reason_code": "SIMULATED_REVIEW_CHAIN_REBOUND",
        "counts": counts,
    }
