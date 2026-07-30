"""Authoritative workflow projection for legacy and evidence-to-release projects."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from review_writer.project.paper_evidence import PaperEvidenceError, paper_evidence_state
from review_writer.project.synthesis import SynthesisError, synthesis_state
from review_writer.project.section_contract import SectionContractError, section_contract_state
from review_writer.project.parse_quality import project_parse_quality_state
from review_writer.project.source_truth import (
    SOURCE_TRUTH_ROOT,
    SourceTruthError,
    canonical_digest,
    declared_study_ids,
    study_source_tier,
)
from review_writer.project.dual_source import project_dual_source_state
from review_writer.project.chemical_completion import project_chemical_completion_state
from review_writer.project.parse_reconciliation import project_reconciliation_state


NEW_ROUTE = "evidence-to-release.v1"


def _regular_file(project: Path, relative: str) -> bool:
    path = project / relative
    return path.is_file() and not path.is_symlink()


def _read_jsonl(project: Path, relative: str) -> list[dict[str, Any]] | None:
    if not _regular_file(project, relative):
        return None
    try:
        lines = (project / relative).read_text(encoding="utf-8").splitlines()
        rows = [json.loads(line) for line in lines if line.strip()]
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not rows or not all(isinstance(row, dict) for row in rows):
        return None
    return rows


def _finalize(state: dict[str, Any]) -> dict[str, Any]:
    state["workflow_digest"] = canonical_digest(state)
    return state


def _legacy_state(project: Path) -> dict[str, Any]:
    evidence_ready = bool(_read_jsonl(project, "01_evidence/evidence_cards.jsonl"))
    manuscript_ready = _regular_file(project, "04_first_draft/first_draft.md")
    verified_release_ready = _regular_file(project, "05_final_audit/final_draft.docx")
    if manuscript_ready:
        active_stage = "final"
    elif evidence_ready:
        active_stage = "drafting"
    elif (project / "00_sources").is_dir():
        active_stage = "evidence"
    else:
        active_stage = "sources"
    return _finalize(
        {
            "schema_version": "evidence-to-release-workflow-state.v1",
            "route": "legacy",
            "active_stage": active_stage,
            "parse_ready": bool((project / "01_evidence/mineru").is_dir()),
            "paper_evidence_ready": evidence_ready,
            "synthesis_ready": evidence_ready,
            "section_contracts_ready": manuscript_ready,
            "manuscript_ready": manuscript_ready,
            "internal_draft_export_ready": manuscript_ready,
            "verified_release_ready": verified_release_ready,
            "blockers": [],
        }
    )


def _new_route_state(
    project: Path,
    *,
    precomputed_dual_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_root = project / SOURCE_TRUTH_ROOT
    bundle_paths = (
        sorted(source_root.glob("*/bundle.json"))
        if source_root.is_dir() and not source_root.is_symlink()
        else []
    )
    try:
        declared = declared_study_ids(project)
    except SourceTruthError:
        declared = []
    actual = [path.parent.name for path in bundle_paths]
    source_ready = bool(declared) and actual == declared and all(
        path.is_file() and not path.is_symlink() for path in bundle_paths
    )
    parse_ready = False
    parse_error = False
    if source_ready:
        try:
            parse_state = project_parse_quality_state(project)
            parse_ready = bool(parse_state.get("workflow_can_continue"))
            parse_error = parse_state.get("status") == "needs_attention"
        except (OSError, ValueError, KeyError, TypeError):
            parse_error = True

    paper_evidence_ready = False
    paper_evidence_error = False
    tiered_dual_route = False
    if source_ready and declared:
        try:
            tiered_dual_route = all(
                study_source_tier(project, study_id) in {"core", "background"}
                for study_id in declared
            )
        except SourceTruthError:
            tiered_dual_route = False
    dual_route = tiered_dual_route or (
        (project / "01_evidence/dual_source").is_dir()
        or (project / "01_evidence/chemical_paper").is_dir()
    )
    dual_source_ready = not dual_route
    chemical_completion_ready = not dual_route
    reconciliation_ready = not dual_route
    dual_blocker: str | None = None
    main_source_available_count = 0
    generic_source_available_count = 0
    dual_state: dict[str, Any] | None = None
    if source_ready and dual_route:
        precomputed_studies = (
            precomputed_dual_state.get("studies")
            if isinstance(precomputed_dual_state, dict)
            else None
        )
        precomputed_ids = (
            sorted(
                row.get("study_id")
                for row in precomputed_studies
                if isinstance(row, dict) and isinstance(row.get("study_id"), str)
            )
            if isinstance(precomputed_studies, list)
            else []
        )
        if (
            precomputed_dual_state is not None
            and precomputed_dual_state.get("schema_version")
            == "dual-source-project-state.v1"
            and precomputed_ids == declared
            and len(precomputed_ids) == len(precomputed_studies)
        ):
            dual_state = precomputed_dual_state
        else:
            dual_state = project_dual_source_state(project)
        main_source_available_count = int(
            dual_state.get("main_source_available_count", 0)
        )
        generic_source_available_count = int(
            dual_state.get("generic_source_available_count", 0)
        )
    if parse_ready and dual_state is not None:
        dual_source_ready = bool(dual_state.get("workflow_can_continue"))
        if not dual_source_ready:
            blocked = next((row for row in dual_state["studies"] if row["status"] == "blocked"), {})
            dual_blocker = str(blocked.get("reason_code") or "DUAL_SOURCE_NOT_READY")
        if dual_source_ready:
            completion_state = project_chemical_completion_state(project)
            chemical_completion_ready = bool(completion_state.get("workflow_can_continue"))
            if not chemical_completion_ready:
                blocked = next((row for row in completion_state["studies"] if not row.get("workflow_can_continue")), {})
                dual_blocker = str(blocked.get("reason_code") or "CHEMICAL_COMPLETION_INCOMPLETE")
        if chemical_completion_ready:
            reconciliation_state = project_reconciliation_state(project)
            reconciliation_ready = bool(reconciliation_state.get("workflow_can_continue"))
            if not reconciliation_ready:
                blocked = next((row for row in reconciliation_state["studies"] if row["status"] == "blocked"), {})
                dual_blocker = str(blocked.get("reason_code") or "PARSE_RECONCILIATION_UNRESOLVED")

    if parse_ready and dual_source_ready and chemical_completion_ready and reconciliation_ready:
        try:
            evidence_state = paper_evidence_state(project)
            paper_evidence_ready = bool(evidence_state.get("workflow_can_continue"))
        except (PaperEvidenceError, OSError, ValueError, KeyError, TypeError):
            paper_evidence_error = True

    synthesis_ready = False
    section_contracts_ready = False
    synthesis_error = False
    section_contract_error = False
    if paper_evidence_ready:
        try:
            synthesis_ready = bool(synthesis_state(project).get("workflow_can_continue"))
        except (SynthesisError, OSError, ValueError, KeyError, TypeError):
            synthesis_error = True
        if synthesis_ready:
            try:
                section_contracts_ready = bool(section_contract_state(project).get("workflow_can_continue"))
            except (SectionContractError, SynthesisError, OSError, ValueError, KeyError, TypeError):
                section_contract_error = True
    manuscript_ready = False
    internal_draft_export_ready = False
    verified_release_ready = False
    if section_contracts_ready:
        try:
            from review_writer.project.manuscript_v2 import manuscript_state

            manuscript_ready = bool(
                manuscript_state(project).get("workflow_can_continue")
            )
            internal_draft_export_ready = manuscript_ready
        except (OSError, ValueError, KeyError, TypeError):
            manuscript_ready = False
            internal_draft_export_ready = False

    blockers: list[str] = []
    if not source_ready:
        active_stage = "sources"
        blockers.append("SOURCE_TRUTH_MISSING_OR_INVALID")
    elif not parse_ready:
        active_stage = "parsing"
        blockers.append(
            "PARSE_QUALITY_INVALID" if parse_error else "PARSE_QUALITY_REVIEW_REQUIRED"
        )
    elif dual_route and not dual_source_ready:
        active_stage = "chemical_import"
        blockers.append(dual_blocker or "DUAL_SOURCE_NOT_READY")
    elif dual_route and not chemical_completion_ready:
        active_stage = "chemical_completion"
        blockers.append(dual_blocker or "CHEMICAL_COMPLETION_INCOMPLETE")
    elif dual_route and not reconciliation_ready:
        active_stage = "reconciliation"
        blockers.append(dual_blocker or "PARSE_RECONCILIATION_UNRESOLVED")
    elif not paper_evidence_ready:
        active_stage = "evidence"
        blockers.append(
            "PAPER_EVIDENCE_INVALID"
            if paper_evidence_error
            else "PAPER_EVIDENCE_NOT_APPROVED"
        )
    elif not synthesis_ready or not section_contracts_ready:
        active_stage = "synthesis"
        blockers.append("SYNTHESIS_INVALID" if synthesis_error else ("SECTION_CONTRACT_INVALID" if section_contract_error else "SYNTHESIS_NOT_APPROVED"))
    elif not manuscript_ready:
        active_stage = "drafting"
        blockers.append("MANUSCRIPT_NOT_APPROVED")
    else:
        active_stage = "final"
        if not internal_draft_export_ready:
            blockers.append("INTERNAL_DRAFT_EXPORT_NOT_READY")

    next_actions = {
        "sources": "Verify the next source PDF.",
        "parsing": "Review the next Generic parse quality item.",
        "chemical_import": "Import and bind the next required Chemical Paper ZIP.",
        "chemical_completion": "Complete the next missing molecule field from the PDF.",
        "reconciliation": "Resolve the next dual-parse conflict against the PDF.",
        "evidence": "Review the next Paper Evidence candidate.",
        "synthesis": "Review the next synthesis object.",
        "drafting": "Review the next manuscript section.",
        "final": "Review internal release readiness.",
    }
    return _finalize(
        {
            "schema_version": "evidence-to-release-workflow-state.v1",
            "route": NEW_ROUTE,
            "dual_route": dual_route,
            "active_stage": active_stage,
            "main_source_available_count": main_source_available_count,
            "generic_source_available_count": generic_source_available_count,
            "parse_ready": parse_ready,
            "dual_source_ready": dual_source_ready,
            "chemical_completion_ready": chemical_completion_ready,
            "reconciliation_ready": reconciliation_ready,
            "paper_evidence_ready": paper_evidence_ready,
            "synthesis_ready": synthesis_ready,
            "section_contracts_ready": section_contracts_ready,
            "manuscript_ready": manuscript_ready,
            "internal_draft_export_ready": internal_draft_export_ready,
            "verified_release_ready": verified_release_ready,
            "blockers": blockers,
            "unique_next_action": next_actions[active_stage],
        }
    )


def workflow_state(
    project: Path,
    *,
    precomputed_dual_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Project the only workflow state allowed to authorize downstream work."""

    project = project.resolve(strict=True)
    source_root = project / SOURCE_TRUTH_ROOT
    if os.path.lexists(source_root):
        return _new_route_state(
            project, precomputed_dual_state=precomputed_dual_state
        )
    return _legacy_state(project)
