"""Authoritative workflow projection for legacy and evidence-to-release projects."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from review_writer.project.paper_evidence import PaperEvidenceError, paper_evidence_state
from review_writer.project.parse_quality import project_parse_quality_state
from review_writer.project.source_truth import (
    SOURCE_TRUTH_ROOT,
    SourceTruthError,
    canonical_digest,
    declared_study_ids,
)


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


def _new_route_state(project: Path) -> dict[str, Any]:
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
    if parse_ready:
        try:
            evidence_state = paper_evidence_state(project)
            paper_evidence_ready = bool(evidence_state.get("workflow_can_continue"))
        except (PaperEvidenceError, OSError, ValueError, KeyError, TypeError):
            paper_evidence_error = True

    # Later tasks replace these remaining closed capabilities with validated projections.
    synthesis_ready = False
    section_contracts_ready = False
    manuscript_ready = False
    internal_draft_export_ready = False
    verified_release_ready = False

    blockers: list[str] = []
    if not source_ready:
        active_stage = "sources"
        blockers.append("SOURCE_TRUTH_MISSING_OR_INVALID")
    elif not parse_ready:
        active_stage = "parsing"
        blockers.append(
            "PARSE_QUALITY_INVALID" if parse_error else "PARSE_QUALITY_REVIEW_REQUIRED"
        )
    elif not paper_evidence_ready:
        active_stage = "evidence"
        blockers.append(
            "PAPER_EVIDENCE_INVALID"
            if paper_evidence_error
            else "PAPER_EVIDENCE_NOT_APPROVED"
        )
    elif not synthesis_ready or not section_contracts_ready:
        active_stage = "synthesis"
        blockers.append("SYNTHESIS_NOT_APPROVED")
    elif not manuscript_ready:
        active_stage = "drafting"
        blockers.append("MANUSCRIPT_NOT_APPROVED")
    else:
        active_stage = "final"
        if not internal_draft_export_ready:
            blockers.append("INTERNAL_DRAFT_EXPORT_NOT_READY")

    return _finalize(
        {
            "schema_version": "evidence-to-release-workflow-state.v1",
            "route": NEW_ROUTE,
            "active_stage": active_stage,
            "parse_ready": parse_ready,
            "paper_evidence_ready": paper_evidence_ready,
            "synthesis_ready": synthesis_ready,
            "section_contracts_ready": section_contracts_ready,
            "manuscript_ready": manuscript_ready,
            "internal_draft_export_ready": internal_draft_export_ready,
            "verified_release_ready": verified_release_ready,
            "blockers": blockers,
        }
    )


def workflow_state(project: Path) -> dict[str, Any]:
    """Project the only workflow state allowed to authorize downstream work."""

    project = project.resolve(strict=True)
    source_root = project / SOURCE_TRUTH_ROOT
    if os.path.lexists(source_root):
        return _new_route_state(project)
    return _legacy_state(project)
