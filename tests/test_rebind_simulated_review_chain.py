from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from review_writer.project.manuscript_v2 import (
    approve_section,
    manuscript_state,
    register_section_draft,
)
from review_writer.project.paper_evidence import (
    apply_paper_evidence_decision,
    paper_evidence_state,
    register_paper_evidence_candidates,
)
from review_writer.project.parse_quality import (
    apply_parse_quality_decision,
    parse_quality_state,
    write_parse_quality_gate,
)
from review_writer.project.section_contract import (
    apply_section_contract_decision,
    register_section_contracts,
    section_contract_state,
)
from review_writer.project.source_truth import write_source_truth_bundle
from review_writer.project.synthesis import (
    apply_comparison_protocol_decision,
    apply_synthesis_decision,
    comparison_protocol_state,
    coverage_map_state,
    register_comparison_protocol,
    register_coverage_map,
    register_synthesis_candidates,
    synthesis_state,
)
from review_writer.project.workflow_projection import workflow_state
from test_source_truth import _source_truth_project


OLD_ACTOR = {
    "actor_type": "human_researcher",
    "actor_label": "local-researcher",
}
NEW_ACTOR = {
    "actor_type": "simulated_researcher_agent",
    "actor_label": "dashboard-playwright-reviewer",
}


def _decision(row: dict[str, object], reason: str = "Source checked.") -> dict[str, object]:
    return {
        "evidence_id": row["evidence_id"],
        "candidate_digest": row["candidate_digest"],
        "bound_parse_object_digests": row["bound_parse_object_digests"],
        "source_pdf_sha256": row["source_pdf_sha256"],
        "action": "approve",
        "reason": reason,
        **OLD_ACTOR,
    }


def _complete_chain(tmp_path: Path, *, with_draft: bool = True) -> Path:
    project = _source_truth_project(tmp_path)
    write_source_truth_bundle(project, "scholarly-a")
    write_parse_quality_gate(project, "scholarly-a")
    parse = parse_quality_state(project, "scholarly-a")
    for row in parse["objects"]:
        if row["status"] == "usable":
            continue
        parse = apply_parse_quality_decision(
            project,
            "scholarly-a",
            {
                "object_id": row["object_id"],
                "object_digest": row["object_digest"],
                "gate_digest": parse["gate_digest"],
                "action": "approve_candidate_extraction",
                "note": "Original PDF compared.",
                **OLD_ACTOR,
            },
        )
    candidate = register_paper_evidence_candidates(
        project,
        "scholarly-a",
        {
            "evidence_id": "EVIDENCE-001",
            "source_id": "stud-a",
            "epistemic_type": "experimental_observation",
            "statement": "The source reported the bounded observation.",
            "locator": {
                "source_mode": "parsed_candidate",
                "page": 1,
                "section_or_item": "Results",
                "figure_or_table": None,
                "exact_quote": "The measured outcome was observed.",
            },
            "reported_conditions": ["Synthetic condition"],
            "quantitative_results": ["Synthetic result"],
            "limitations": ["Single-study observation"],
            "mechanism_grade": "not_applicable",
            "risk_classes": [],
        },
    )["candidates"][0]
    apply_paper_evidence_decision(project, _decision(candidate, "Evidence reason sentinel."))

    register_comparison_protocol(
        project,
        {
            "comparison_id": "comparison-one",
            "comparison_objects": ["scholarly-a"],
            "axes": ["reported outcome"],
            "normalization_rules": ["Keep source units."],
            "missing_value_policy": "Mark missing values.",
            "incomparability_rules": ["Do not force unlike measures."],
            "counterevidence_rules": ["Retain limitations."],
            "claim_strength": "bounded",
        },
    )
    apply_comparison_protocol_decision(
        project,
        {"action": "approve", "reason": "Protocol reason sentinel.", **OLD_ACTOR},
    )
    register_coverage_map(
        project,
        {
            "comparison_id": "comparison-one",
            "axes": [{"axis": "reported outcome", "studies": ["scholarly-a"]}],
            "known_omissions": ["Only one calibration study."],
        },
    )
    register_synthesis_candidates(
        project,
        {
            "synthesis_id": "SYNTHESIS-001",
            "proposition": "The bounded observation applies to this study.",
            "comparison_axis": "reported outcome",
            "supporting_evidence_ids": ["EVIDENCE-001"],
            "counter_evidence_ids": [],
            "applicability_boundary": "This study only.",
            "mechanism_evidence_grade": "not_applicable",
            "uncertainty": "Single-study evidence.",
            "risk_class": "scope",
            "single_study": True,
        },
    )
    apply_synthesis_decision(
        project,
        {
            "synthesis_id": "SYNTHESIS-001",
            "action": "approve",
            "reason": "Synthesis reason sentinel.",
            **OLD_ACTOR,
        },
    )
    register_section_contracts(
        project,
        {
            "section_id": "section-one",
            "research_question": "What bounded observation was reported?",
            "comparison_axes": ["reported outcome"],
            "expected_synthesis": "A single-study bounded statement.",
            "counterevidence_and_limitations": ["Only one study is represented."],
            "evidence_budget": 1,
            "synthesis_budget": 1,
            "figure_plan": [{"kind": "none", "reason": "No figure required."}],
            "allowed_wording_strength": "reported",
        },
    )
    apply_section_contract_decision(
        project,
        {
            "section_id": "section-one",
            "action": "approve",
            "reason": "Contract reason sentinel.",
            **OLD_ACTOR,
        },
    )
    if with_draft:
        register_section_draft(
            project,
            {
                "section_id": "section-one",
                "heading": "Bounded evidence",
                "body": "The source reported the product. [evidence:EVIDENCE-001]",
                "content_agent_result_digest": hashlib.sha256(b"content-result").hexdigest(),
            },
        )
    legacy = project / "04_first_draft/first_draft.md"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_bytes(b"LEGACY SENTINEL MUST NOT CHANGE")
    return project


def _regular_bytes(project: Path) -> dict[str, bytes]:
    return {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file() and not path.is_symlink()
    }


def _rebind(project: Path, *, dry_run: bool = False) -> dict[str, object]:
    from review_writer.project.simulated_review_rebind import rebind_simulated_review_chain

    return rebind_simulated_review_chain(
        project,
        actor_label="dashboard-playwright-reviewer",
        dry_run=dry_run,
    )


def test_rebind_appends_evidence_history_and_refreshes_current_chain(tmp_path: Path) -> None:
    project = _complete_chain(tmp_path)
    before_candidates = (project / "01_evidence/scholarly-a/paper_evidence_candidates.json").read_bytes()
    before_parse = (project / "01_evidence/source_truth/scholarly-a/parse_quality.json").read_bytes()
    before_legacy = (project / "04_first_draft/first_draft.md").read_bytes()
    old_draft = json.loads((project / "04_manuscript/section_drafts.jsonl").read_text())

    result = _rebind(project)

    decisions = [
        json.loads(line)
        for line in (project / "01_evidence/paper_evidence_decisions.jsonl").read_text().splitlines()
    ]
    assert result == {
        "status": "REBOUND",
        "reason_code": "SIMULATED_REVIEW_CHAIN_REBOUND",
        "counts": {"evidence": 1, "protocol": 1, "coverage": 1, "synthesis": 1, "contracts": 1, "drafts": 1},
    }
    assert len(decisions) == 2
    assert decisions[0]["decision"]["actor_type"] == "human_researcher"
    assert decisions[-1]["decision"]["actor_type"] == "simulated_researcher_agent"
    assert decisions[-1]["decision"]["reason"] == "Evidence reason sentinel."
    assert paper_evidence_state(project)["rows"][0]["decision"]["actor_label"] == NEW_ACTOR["actor_label"]
    assert comparison_protocol_state(project)["value"]["decision"]["actor_type"] == NEW_ACTOR["actor_type"]
    assert coverage_map_state(project)["workflow_can_continue"] is True
    assert synthesis_state(project)["rows"][0]["decision"]["actor_type"] == NEW_ACTOR["actor_type"]
    assert section_contract_state(project)["rows"][0]["decision"]["actor_type"] == NEW_ACTOR["actor_type"]
    new_draft = json.loads((project / "04_manuscript/section_drafts.jsonl").read_text())
    assert new_draft["body"] == old_draft["body"]
    assert new_draft["decision"] is None
    assert new_draft["status"] in {"needs_human_edit", "needs_review"}
    assert new_draft["draft_digest"] != old_draft["draft_digest"]
    assert (project / "01_evidence/scholarly-a/paper_evidence_candidates.json").read_bytes() == before_candidates
    assert (project / "01_evidence/source_truth/scholarly-a/parse_quality.json").read_bytes() == before_parse
    assert (project / "04_first_draft/first_draft.md").read_bytes() == before_legacy
    workflow = workflow_state(project)
    assert workflow["active_stage"] == "drafting"
    assert workflow["manuscript_ready"] is False
    assert workflow["verified_release_ready"] is False
    assert manuscript_state(project)["workflow_can_continue"] is False


def test_rebind_dry_run_has_zero_writes(tmp_path: Path) -> None:
    project = _complete_chain(tmp_path)
    before = _regular_bytes(project)

    result = _rebind(project, dry_run=True)

    assert result["status"] == "DRY_RUN_READY"
    assert _regular_bytes(project) == before


@pytest.mark.parametrize("lock_state", ["missing", "empty"])
def test_rebind_dry_run_refuses_uninitialized_lock_without_writes(
    tmp_path: Path, lock_state: str
) -> None:
    from review_writer.project.simulated_review_rebind import SimulatedReviewRebindError

    project = _complete_chain(tmp_path)
    lock_path = project / ".paper_evidence.lock"
    if lock_state == "missing":
        lock_path.unlink()
    else:
        lock_path.write_bytes(b"")
    before = _regular_bytes(project)

    with pytest.raises(
        SimulatedReviewRebindError, match="PAPER_EVIDENCE_LOCK_UNINITIALIZED"
    ):
        _rebind(project, dry_run=True)

    assert _regular_bytes(project) == before




def test_rebind_rejects_unknown_actor_without_writes(tmp_path: Path) -> None:
    from review_writer.project.simulated_review_rebind import SimulatedReviewRebindError

    project = _complete_chain(tmp_path)
    row = paper_evidence_state(project)["rows"][0]
    apply_paper_evidence_decision(
        project,
        {**_decision(row), "actor_type": "simulated_researcher_agent", "actor_label": "other-agent"},
    )
    before = _regular_bytes(project)

    with pytest.raises(SimulatedReviewRebindError, match="CHAIN_ACTOR_NOT_ELIGIBLE"):
        _rebind(project)

    assert _regular_bytes(project) == before


@pytest.mark.parametrize("case", ["stale", "incomplete"])
def test_rebind_rejects_noncurrent_or_incomplete_chain_without_writes(
    tmp_path: Path, case: str
) -> None:
    from review_writer.project.simulated_review_rebind import SimulatedReviewRebindError

    project = _complete_chain(tmp_path)
    coverage = project / "02_synthesis/coverage_map.json"
    if case == "stale":
        protocol = project / "02_synthesis/comparison_protocol.json"
        value = json.loads(protocol.read_text())
        value["paper_evidence_projection_digest"] = "0" * 64
        protocol.write_text(json.dumps(value), encoding="utf-8")
    else:
        coverage.unlink()
    before = _regular_bytes(project)

    with pytest.raises(SimulatedReviewRebindError):
        _rebind(project)

    assert _regular_bytes(project) == before


def test_rebind_rejects_approved_draft_without_writes(tmp_path: Path) -> None:
    from review_writer.project.simulated_review_rebind import SimulatedReviewRebindError

    project = _complete_chain(tmp_path)
    draft = json.loads((project / "04_manuscript/section_drafts.jsonl").read_text())
    approve_section(
        project,
        "section-one",
        OLD_ACTOR,
        reason="Human approval must remain immutable.",
        expected_draft_digest=draft["draft_digest"],
    )
    before = _regular_bytes(project)

    with pytest.raises(SimulatedReviewRebindError, match="APPROVED_DRAFT_REBIND_FORBIDDEN"):
        _rebind(project)

    assert _regular_bytes(project) == before


def test_rebind_rolls_back_every_file_after_injected_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from review_writer.project import simulated_review_rebind as rebind

    project = _complete_chain(tmp_path)
    before = _regular_bytes(project)
    original = rebind._atomic_replace
    calls = 0

    def fail_third(root: Path, relative: Path, payload: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("injected transaction failure")
        original(root, relative, payload)

    monkeypatch.setattr(rebind, "_atomic_replace", fail_third)
    with pytest.raises(rebind.SimulatedReviewRebindError, match="REBIND_WRITE_FAILED"):
        _rebind(project)

    assert _regular_bytes(project) == before


def test_rebind_rejects_symlink_output_without_writes(tmp_path: Path) -> None:
    from review_writer.project.simulated_review_rebind import SimulatedReviewRebindError

    project = _complete_chain(tmp_path)
    coverage = project / "02_synthesis/coverage_map.json"
    outside = tmp_path / "outside-coverage.json"
    outside.write_bytes(coverage.read_bytes())
    coverage.unlink()
    coverage.symlink_to(outside)
    before = _regular_bytes(project)

    with pytest.raises(SimulatedReviewRebindError, match="PROJECT_SYMLINK_UNSAFE"):
        _rebind(project)

    assert coverage.is_symlink()
    assert _regular_bytes(project) == before


def test_rebind_detects_concurrent_version_change_before_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from review_writer.project import simulated_review_rebind as rebind

    project = _complete_chain(tmp_path)
    protocol = project / "02_synthesis/comparison_protocol.json"
    concurrent = protocol.read_bytes() + b"\n"
    original_snapshot = rebind._snapshot
    calls = 0

    def concurrent_snapshot(root: Path):
        nonlocal calls
        result = original_snapshot(root)
        calls += 1
        if root == project and calls == 2:
            protocol.write_bytes(concurrent)
        return result

    monkeypatch.setattr(rebind, "_snapshot", concurrent_snapshot)
    with pytest.raises(rebind.SimulatedReviewRebindError, match="CHAIN_VERSION_CHANGED"):
        _rebind(project)

    assert protocol.read_bytes() == concurrent


def test_rebind_rejects_decision_change_after_chain_read_before_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from review_writer.project import simulated_review_rebind as rebind

    project = _complete_chain(tmp_path)
    original_chain = rebind._current_chain
    concurrent_bytes: dict[str, bytes] = {}

    def chain_then_concurrent_decision(root: Path):
        chain = original_chain(root)
        row = paper_evidence_state(root)["rows"][0]
        decision_path = root / "01_evidence/paper_evidence_decisions.jsonl"
        events = [json.loads(line) for line in decision_path.read_text().splitlines()]
        event = json.loads(json.dumps(events[-1]))
        event["decision"]["reason"] = "Concurrent decision after chain read."
        event["decision"]["decided_at"] = "2099-01-01T00:00:00+00:00"
        decision_path.write_text(
            "\n".join(json.dumps(item, sort_keys=True) for item in [*events, event]) + "\n"
        )
        concurrent_bytes["all"] = _regular_bytes(root)[
            "01_evidence/paper_evidence_decisions.jsonl"
        ]
        return chain

    before = _regular_bytes(project)
    monkeypatch.setattr(rebind, "_current_chain", chain_then_concurrent_decision)

    with pytest.raises(rebind.SimulatedReviewRebindError, match="CHAIN_VERSION_CHANGED"):
        _rebind(project)

    after = _regular_bytes(project)
    assert after["01_evidence/paper_evidence_decisions.jsonl"] == concurrent_bytes["all"]
    for relative, payload in before.items():
        if relative != "01_evidence/paper_evidence_decisions.jsonl":
            assert after[relative] == payload


def test_rebind_cli_stdout_contains_only_status_reason_and_counts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts.project import main

    project = _complete_chain(tmp_path)

    assert main(
        [
            "rebind-simulated-review-chain",
            "--project",
            str(project),
            "--actor-label",
            "dashboard-playwright-reviewer",
            "--dry-run",
        ]
    ) == 0
    output = json.loads(capsys.readouterr().out)
    assert set(output) == {"status", "reason_code", "counts"}
    assert output["status"] == "DRY_RUN_READY"
    encoded = json.dumps(output)
    assert str(project) not in encoded
    assert "sentinel" not in encoded.casefold()
